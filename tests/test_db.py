"""Database tests. Skipped unless DATABASE_URL points at a Postgres + TimescaleDB server.

They run in a separate throwaway database (`<name>_test`), never the one in DATABASE_URL.
"""

import os

import numpy as np
import pandas as pd
import pytest

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set (start it with `docker compose up -d db`)", allow_module_level=True)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from bot_arena.db import repository as repo
from bot_arena.engine import run_backtest
from bot_arena.strategies import RandomMonkey, SpyHodler


@pytest.fixture(scope="module")
def test_url():
    base = conninfo_to_dict(os.environ["DATABASE_URL"])
    name = f"{base.get('dbname', 'arena')}_test"
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
            "TRUNCATE journal, equity_snapshots, trades, risk_events, positions, bots, runs, bars RESTART IDENTITY"
        )
        conn.commit()
        repo.set_kill_switch(conn, False, "")
        yield conn


def synthetic(n=60):
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-05", periods=n, freq="B", tz="UTC")
    closes = pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(rng.normal(0.001, 0.01, n))) for s in ["SPY", "QQQ", "AAA"]}, index=idx
    )
    return closes, closes


def test_migrate_is_idempotent(conn):
    assert repo.migrate(conn) == []
    tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"runs", "bots", "trades", "equity_snapshots", "risk_events", "bars", "kill_switch"} <= tables
    hypertables = {
        r[0] for r in conn.execute("SELECT hypertable_name FROM timescaledb_information.hypertables")
    }
    assert {"equity_snapshots", "bars"} <= hypertables


def test_save_backtest_round_trips(conn):
    opens, closes = synthetic()
    results = [run_backtest(bot, opens, closes, 1000) for bot in (SpyHodler(), RandomMonkey(3))]
    run_id = repo.save_backtest(conn, results, {"slippage_bps": 5}, 1000)

    for r in results:
        bot_id, status = conn.execute(
            "SELECT id, status FROM bots WHERE run_id = %s AND name = %s", (run_id, r.strategy.name)
        ).fetchone()
        assert status == r.status
        n_snap = conn.execute("SELECT count(*) FROM equity_snapshots WHERE bot_id = %s", (bot_id,)).fetchone()
        n_trades = conn.execute("SELECT count(*) FROM trades WHERE bot_id = %s", (bot_id,)).fetchone()
        assert n_snap[0] == len(r.equity)
        assert n_trades[0] == len(r.fills)
    params = conn.execute("SELECT params FROM runs WHERE id = %s", (run_id,)).fetchone()[0]
    assert params == {"slippage_bps": 5}


def test_leaderboard_is_best_first(conn):
    opens, closes = synthetic()
    results = [run_backtest(bot, opens, closes, 1000) for bot in (SpyHodler(), RandomMonkey(3))]
    run_id = repo.save_backtest(conn, results, {}, 1000)
    board = repo.leaderboard(conn, run_id)
    expected = sorted(results, key=lambda r: -r.equity.iloc[-1])
    assert [row[0] for row in board] == [r.strategy.name for r in expected]
    assert board[0][3] == pytest.approx(expected[0].equity.iloc[-1])


def test_bars_upsert_and_load(conn):
    idx = pd.MultiIndex.from_product(
        [["AAA", "BBB"], pd.date_range("2026-01-05", periods=3, freq="B", tz="UTC")],
        names=["symbol", "timestamp"],
    )
    bars = pd.DataFrame(
        {"open": 1.0, "high": 2.0, "low": 0.5, "close": np.arange(6, dtype=float), "volume": 100.0}, index=idx
    )
    assert repo.save_bars(conn, bars) == 6
    bars["close"] += 10  # same keys again: must update, not duplicate
    repo.save_bars(conn, bars)

    loaded = repo.load_bars(conn, ["AAA", "BBB"], pd.Timestamp("2026-01-01", tz="UTC"))
    pd.testing.assert_frame_equal(loaded, bars, check_freq=False)
    only_a = repo.load_bars(conn, ["AAA"], pd.Timestamp("2026-01-06", tz="UTC"))
    assert len(only_a) == 2


def test_kill_switch_toggle(conn):
    assert repo.get_kill_switch(conn) == (False, "")
    repo.set_kill_switch(conn, True, "testing")
    assert repo.get_kill_switch(conn) == (True, "testing")
    repo.set_kill_switch(conn, False)
    assert repo.get_kill_switch(conn) == (False, "")
