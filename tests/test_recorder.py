"""Recorder tests. Skipped unless DATABASE_URL points at a Postgres + TimescaleDB server.

They run in a separate throwaway database (`<name>_rectest`), never the one in DATABASE_URL.
"""

import os

import pytest

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set (start it with `docker compose up -d db`)", allow_module_level=True)

import pandas as pd
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from bot_arena.broker import Fill, Portfolio
from bot_arena.db import repository as repo
from bot_arena.pipeline import events
from bot_arena.pipeline.log import MemoryLog
from bot_arena.pipeline.recorder import Recorder, record_available, stored_offset

TOPIC = "arena.paper.test"


@pytest.fixture(scope="module")
def test_url():
    base = conninfo_to_dict(os.environ["DATABASE_URL"])
    name = f"{base.get('dbname', 'arena')}_rectest"
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.execute(f'CREATE DATABASE "{name}"')
    yield make_conninfo(**{**base, "dbname": name})
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def conn(test_url):
    with repo.connect(test_url) as conn:
        repo.migrate(conn)
        conn.execute(
            "TRUNCATE equity_snapshots, trades, risk_events, positions, bots, runs, bars, log_offsets "
            "RESTART IDENTITY"
        )
        conn.commit()
        yield conn


def day_log() -> MemoryLog:
    """Two days of a 2-bot paper run, in the order the pipeline writes them."""
    d1, d2 = "2026-10-06", "2026-10-07"
    ts2 = pd.Timestamp(d2, tz="UTC")
    return MemoryLog(
        [
            events.run(d1, ["Hodler", "Monkey"], 1000.0, 5, 0, emojis={"Hodler": "🐢"}),
            events.bar("SPY", "2026-10-05", 99.0, 100.0, warmup=True),
            events.bar("SPY", d1, 100.0, 101.0, high=102.0, low=99.5, volume=5e6),
            events.close(d1, ["SPY"]),
            events.portfolio("Hodler", d1, Portfolio(1000.0, {}, 1000.0, {})),
            events.portfolio("Monkey", d1, Portfolio(1000.0, {}, 1000.0, {})),
            events.decision("Hodler", d1, {"SPY": 1.0}, "active"),
            events.decision("Monkey", d1, {"SPY": 0.5}, "active"),
            events.bar("SPY", d2, 102.0, 103.0),
            events.close(d2, ["SPY"]),
            events.fill("Hodler", 0, Fill(ts2, "SPY", "buy", 9.8, 102.05, 0.0)),
            events.fill("Monkey", 0, Fill(ts2, "SPY", "buy", 4.9, 102.05, 0.0)),
            events.portfolio("Hodler", d2, Portfolio(0.0, {"SPY": 9.8}, 1009.4, {"SPY": 1.0})),
            events.portfolio("Monkey", d2, Portfolio(500.0, {"SPY": 4.9}, 1004.7, {"SPY": 0.502})),
            events.risk("Monkey", 0, "eliminated", "down 31% from peak", d2),
            events.decision("Monkey", d2, {}, "eliminated"),
        ]
    )


def counts(conn) -> dict[str, int]:
    tables = ["runs", "bots", "trades", "equity_snapshots", "risk_events", "bars", "positions"]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def test_records_a_paper_run(conn):
    log = day_log()
    assert record_available(Recorder(conn, TOPIC), log, "rec", 0) == len(log.events)

    run_id, kind, start, end, params = conn.execute(
        "SELECT id, kind, start_date::text, end_date::text, params FROM runs WHERE topic = %s", (TOPIC,)
    ).fetchone()
    assert (kind, start, end) == ("paper", "2026-10-06", "2026-10-07")
    assert params["cash"] == 1000.0 and "bots" not in params

    rows = conn.execute("SELECT name, emoji, status, starting_cash::float FROM bots").fetchall()
    bots = {name: tuple(rest) for name, *rest in rows}
    assert bots["Hodler"] == ("🐢", "active", 1000.0)
    assert bots["Monkey"][1] == "eliminated"

    assert counts(conn) == {
        "runs": 1,
        "bots": 2,
        "trades": 2,
        "equity_snapshots": 4,
        "risk_events": 1,
        "bars": 2,
        "positions": 2,
    }
    # Warmup bars aren't recorded; live bars keep their OHLCV.
    bar = conn.execute("SELECT open, high, low, close, volume FROM bars ORDER BY ts LIMIT 1").fetchone()
    assert bar == (100.0, 102.0, 99.5, 101.0, 5e6)
    equity, exposure = conn.execute(
        "SELECT equity, exposure FROM equity_snapshots s JOIN bots b ON b.id = s.bot_id "
        "WHERE b.name = 'Monkey' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    assert equity == pytest.approx(1004.7) and exposure == pytest.approx(1 - 500 / 1004.7)
    assert repo.leaderboard(conn, run_id)[0][0] == "Hodler"
    assert stored_offset(conn, "rec") == len(log.events)


def test_recording_the_same_events_twice_changes_nothing(conn):
    log = day_log()
    record_available(Recorder(conn, TOPIC), log, "rec", 0)
    before = counts(conn)
    # A crash before the offset was saved: everything gets recorded again, by a fresh recorder.
    record_available(Recorder(conn, TOPIC), log, "rec", 0)
    assert counts(conn) == before


def test_resumes_from_the_stored_offset(conn):
    log = day_log()
    first_day = MemoryLog(log.events[:8])
    assert record_available(Recorder(conn, TOPIC), first_day, "rec", 0) == 8
    assert counts(conn)["equity_snapshots"] == 2

    recorder = Recorder(conn, TOPIC)  # restart: picks up the run from the database
    assert recorder.run_id is not None and set(recorder.bot_ids) == {"Hodler", "Monkey"}
    offset = record_available(recorder, log, "rec", stored_offset(conn, "rec"))
    assert offset == len(log.events)
    assert counts(conn)["trades"] == 2 and counts(conn)["equity_snapshots"] == 4


def test_nothing_new_is_a_no_op(conn):
    log = day_log()
    end = record_available(Recorder(conn, TOPIC), log, "rec", 0)
    assert record_available(Recorder(conn, TOPIC), log, "rec", end) == end


def test_events_for_unknown_bots_are_ignored(conn):
    log = day_log()
    log.append(events.portfolio("Ghost", "2026-10-07", Portfolio(1.0, {}, 1.0, {})))
    record_available(Recorder(conn, TOPIC), log, "rec", 0)
    assert counts(conn)["equity_snapshots"] == 4


def test_backtest_rows_still_work_alongside(conn):
    """Old backtest rows have no event_id (NULL), which must not clash with each other."""
    run_id = conn.execute("INSERT INTO runs (kind) VALUES ('backtest') RETURNING id").fetchone()[0]
    bot_id = conn.execute(
        "INSERT INTO bots (run_id, name, starting_cash) VALUES (%s, 'B', 1000) RETURNING id", (run_id,)
    ).fetchone()[0]
    for _ in range(2):
        conn.execute(
            "INSERT INTO trades (bot_id, ts, symbol, side, shares, price) VALUES (%s, now(), 'X', 'buy', 1, 1)",
            (bot_id,),
        )
    conn.commit()
    assert counts(conn)["trades"] == 2
