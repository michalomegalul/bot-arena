"""Raw-SQL access to the arena database (psycopg 3, no ORM)."""

import os
from datetime import datetime
from importlib import resources

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from bot_arena.engine import BacktestResult


def connect(url: str | None = None) -> psycopg.Connection:
    """Connect using `url` or the DATABASE_URL environment variable (.env is loaded)."""
    load_dotenv()
    url = url or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("Missing DATABASE_URL. See .env.example (and `docker compose up -d db`).")
    return psycopg.connect(url)


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply any migrations that haven't run yet, in order. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    files = sorted(
        (f for f in resources.files("bot_arena.db.migrations").iterdir() if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    applied = []
    for f in files:
        if f.name in done:
            continue
        with conn.transaction():
            conn.execute(f.read_text())
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
        applied.append(f.name)
    conn.commit()
    return applied


def save_backtest(
    conn: psycopg.Connection, results: list[BacktestResult], params: dict, starting_cash: float
) -> int:
    """Store a whole backtest (every bot's trades, equity curve and risk events). Returns the run id."""
    dates = [d for r in results for d in (r.equity.index.min(), r.equity.index.max())]
    with conn.transaction():
        run_id = conn.execute(
            "INSERT INTO runs (kind, params, start_date, end_date) VALUES ('backtest', %s, %s, %s) RETURNING id",
            (Jsonb(params), min(dates).date() if dates else None, max(dates).date() if dates else None),
        ).fetchone()[0]
        for r in results:
            bot_id = conn.execute(
                "INSERT INTO bots (run_id, name, emoji, status, starting_cash) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (run_id, r.strategy.name, r.strategy.emoji, r.status, starting_cash),
            ).fetchone()[0]
            with conn.cursor() as cur:
                with cur.copy("COPY equity_snapshots (bot_id, ts, equity, exposure) FROM STDIN") as copy:
                    for ts, equity in r.equity.items():
                        copy.write_row((bot_id, _ts(ts), float(equity), float(r.exposure[ts])))
                with cur.copy(
                    "COPY trades (bot_id, ts, symbol, side, shares, price, fee) FROM STDIN"
                ) as copy:
                    for f in r.fills:
                        copy.write_row(
                            (bot_id, _ts(f.date), f.symbol, f.side, float(f.shares), float(f.price), f.fee)
                        )
                cur.executemany(
                    "INSERT INTO risk_events (bot_id, ts, kind, detail) VALUES (%s, %s, %s, %s)",
                    [(bot_id, _ts(e.date), e.kind, e.detail) for e in r.events],
                )
    conn.commit()
    return run_id


def save_bars(conn: psycopg.Connection, bars: pd.DataFrame) -> int:
    """Upsert daily bars (indexed by symbol, timestamp, as from Alpaca). Returns rows written."""
    rows = [
        (sym, _ts(ts), float(b.open), float(b.high), float(b.low), float(b.close), float(b.volume))
        for (sym, ts), b in bars.iterrows()
    ]
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO bars (symbol, ts, open, high, low, close, volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (symbol, ts) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high, "
            "low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume",
            rows,
        )
    conn.commit()
    return len(rows)


def load_bars(conn: psycopg.Connection, symbols: list[str], start: datetime) -> pd.DataFrame:
    """Bars for `symbols` from `start`, indexed by (symbol, timestamp) like data.load_bars()."""
    rows = conn.execute(
        "SELECT symbol, ts, open, high, low, close, volume FROM bars "
        "WHERE symbol = ANY(%s) AND ts >= %s ORDER BY symbol, ts",
        (symbols, start),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index(["symbol", "timestamp"])


def get_kill_switch(conn: psycopg.Connection) -> tuple[bool, str]:
    engaged, reason = conn.execute("SELECT engaged, reason FROM kill_switch WHERE id = 1").fetchone()
    return engaged, reason


def set_kill_switch(conn: psycopg.Connection, engaged: bool, reason: str = "") -> None:
    conn.execute(
        "UPDATE kill_switch SET engaged = %s, reason = %s, updated_at = now() WHERE id = 1",
        (engaged, reason),
    )
    conn.commit()


def leaderboard(conn: psycopg.Connection, run_id: int) -> list[tuple[str, str, str, float]]:
    """(name, emoji, status, final equity) for every bot in a run, best first."""
    return conn.execute(
        """
        SELECT b.name, b.emoji, b.status, last.equity
        FROM bots b
        JOIN LATERAL (
            SELECT equity FROM equity_snapshots s WHERE s.bot_id = b.id ORDER BY s.ts DESC LIMIT 1
        ) last ON TRUE
        WHERE b.run_id = %s
        ORDER BY last.equity DESC
        """,
        (run_id,),
    ).fetchall()


def recent_runs(conn: psycopg.Connection, limit: int = 10) -> list[tuple]:
    """(id, kind, started_at, start_date, end_date) of the newest runs."""
    return conn.execute(
        "SELECT id, kind, started_at, start_date, end_date FROM runs ORDER BY id DESC LIMIT %s", (limit,)
    ).fetchall()


def _ts(value) -> datetime:
    """pandas Timestamp -> timezone-aware datetime (naive ones are taken as UTC)."""
    ts = pd.Timestamp(value)
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts).to_pydatetime()


class DbKillSwitch:
    """The kill switch row, for the risk manager.

    Fails closed: if the database can't be read, it reports "engaged" and trading halts.
    """

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def check(self) -> str | None:
        try:
            engaged, reason = get_kill_switch(self.conn)
        except psycopg.Error as exc:
            try:
                self.conn.rollback()
            except psycopg.Error:
                pass
            return f"kill switch unreadable ({type(exc).__name__}), halting to be safe"
        return (reason or "engaged in the database") if engaged else None
