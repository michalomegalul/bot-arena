"""Mirrors the event log into Postgres, for the UI and for queries.

It only reads the log (never appends), so it isn't a pipeline Service. Every write is
idempotent: trades and risk events carry their event id, equity snapshots are keyed by
(bot, day), and the next log offset is saved in the same transaction as the rows. After a
crash it resumes where the last commit left off, and anything recorded twice is ignored.
"""

import logging
import time

import psycopg
from psycopg.types.json import Jsonb

from bot_arena.pipeline import events
from bot_arena.pipeline.events import Event
from bot_arena.pipeline.log import EventLog

log_ = logging.getLogger(__name__)

BATCH = 500  # commit at least this often while catching up


class Recorder:
    def __init__(self, conn: psycopg.Connection, topic: str):
        self.conn, self.topic = conn, topic
        self.run_id: int | None = None
        self.bot_ids: dict[str, int] = {}
        self._load_run()

    def handle(self, event: Event) -> None:
        if event.type == events.RUN:
            self._record_run(event)
        elif self.run_id is None:
            return  # nothing to attach it to (the log should start with a run event)
        elif event.type == events.BAR and not event.data.get("warmup"):
            self._record_bar(event)
        elif event.type == events.CLOSE:
            self.conn.execute("UPDATE runs SET end_date = %s WHERE id = %s", (event.date, self.run_id))
        elif event.type == events.PORTFOLIO and (bot_id := self._bot(event)):
            self._record_portfolio(bot_id, event)
        elif event.type == events.FILL and (bot_id := self._bot(event)):
            d = event.data
            self.conn.execute(
                "INSERT INTO trades (bot_id, ts, symbol, side, shares, price, fee, event_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
                (
                    bot_id,
                    event.timestamp,
                    d["symbol"],
                    d["side"],
                    d["shares"],
                    d["price"],
                    d["fee"],
                    event.id,
                ),
            )
        elif event.type == events.RISK and (bot_id := self._bot(event)):
            self.conn.execute(
                "INSERT INTO risk_events (bot_id, ts, kind, detail, event_id) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
                (bot_id, event.timestamp, event.data["kind"], event.data["detail"], event.id),
            )
            if event.data["kind"] == "eliminated":
                self.conn.execute("UPDATE bots SET status = 'eliminated' WHERE id = %s", (bot_id,))

    def save_offset(self, consumer: str, next_offset: int) -> None:
        """Store the resume point and commit everything recorded so far, atomically."""
        self.conn.execute(
            "INSERT INTO log_offsets (consumer, next_offset) VALUES (%s, %s) "
            "ON CONFLICT (consumer) DO UPDATE SET next_offset = EXCLUDED.next_offset, updated_at = now()",
            (consumer, next_offset),
        )
        self.conn.commit()

    # --- per event type ---

    def _record_run(self, event: Event) -> None:
        d = event.data
        params = {k: v for k, v in d.items() if k != "bots"}
        self.conn.execute(
            "INSERT INTO runs (kind, params, start_date, topic) VALUES ('paper', %s, %s, %s) "
            "ON CONFLICT (topic) DO NOTHING",
            (Jsonb(params), event.date, self.topic),
        )
        run_id = self.conn.execute("SELECT id FROM runs WHERE topic = %s", (self.topic,)).fetchone()[0]
        emojis = d.get("emojis", {})
        for name in d["bots"]:
            self.conn.execute(
                "INSERT INTO bots (run_id, name, emoji, starting_cash) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (run_id, name) DO NOTHING",
                (run_id, name, emojis.get(name, ""), d["cash"]),
            )
        self._load_run()

    def _record_bar(self, event: Event) -> None:
        d = event.data
        high = d.get("high", max(d["open"], d["close"]))
        low = d.get("low", min(d["open"], d["close"]))
        self.conn.execute(
            "INSERT INTO bars (symbol, ts, open, high, low, close, volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (symbol, ts) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high, "
            "low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume",
            (event.key, event.timestamp, d["open"], high, low, d["close"], d.get("volume", 0.0)),
        )

    def _record_portfolio(self, bot_id: int, event: Event) -> None:
        d = event.data
        exposure = 1 - d["cash"] / d["equity"] if d["equity"] else 0.0
        self.conn.execute(
            "INSERT INTO equity_snapshots (bot_id, ts, equity, exposure) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (bot_id, ts) DO UPDATE SET equity = EXCLUDED.equity, exposure = EXCLUDED.exposure",
            (bot_id, event.timestamp, d["equity"], exposure),
        )
        # Current holdings, for the UI.
        self.conn.execute("DELETE FROM positions WHERE bot_id = %s", (bot_id,))
        for symbol, shares in d["positions"].items():
            self.conn.execute(
                "INSERT INTO positions (bot_id, symbol, shares) VALUES (%s, %s, %s)", (bot_id, symbol, shares)
            )

    # --- helpers ---

    def _load_run(self) -> None:
        row = self.conn.execute("SELECT id FROM runs WHERE topic = %s", (self.topic,)).fetchone()
        if row:
            self.run_id = row[0]
            rows = self.conn.execute("SELECT name, id FROM bots WHERE run_id = %s", (self.run_id,))
            self.bot_ids = dict(rows.fetchall())

    def _bot(self, event: Event) -> int | None:
        bot_id = self.bot_ids.get(event.key)
        if bot_id is None:
            log_.warning("%s for unknown bot %r ignored", event.type, event.key)
        return bot_id


def stored_offset(conn: psycopg.Connection, consumer: str) -> int:
    row = conn.execute("SELECT next_offset FROM log_offsets WHERE consumer = %s", (consumer,)).fetchone()
    return row[0] if row else 0


def record_available(recorder: Recorder, log: EventLog, consumer: str, start: int) -> int:
    """Record everything from `start` up to the log's current end. Returns the new next offset."""
    end = log.end_offset()
    if end <= start:
        return start
    pending = 0
    for offset, event in log.read(start, end):
        recorder.handle(event)
        pending += 1
        if pending >= BATCH:
            recorder.save_offset(consumer, offset + 1)
            pending = 0
    recorder.save_offset(consumer, end)
    return end


def run_recorder(
    conn: psycopg.Connection, log: EventLog, topic: str, consumer: str = "recorder", poll_seconds: float = 2
) -> None:
    """Follow the log forever, resuming from the last committed offset."""
    recorder = Recorder(conn, topic)
    offset = stored_offset(conn, consumer)
    log_.info("recording %s from offset %d", topic, offset)
    while True:
        try:
            offset = record_available(recorder, log, consumer, offset)
        except psycopg.Error:
            log_.exception("recording failed; rolling back and retrying from offset %d", offset)
            conn.rollback()
            recorder = Recorder(conn, topic)
            offset = stored_offset(conn, consumer)
        time.sleep(poll_seconds)
