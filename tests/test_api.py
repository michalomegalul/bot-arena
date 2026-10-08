"""API tests against a real database. Skipped unless DATABASE_URL is set (it is in CI)."""

import os

import numpy as np
import pandas as pd
import pytest

if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set", allow_module_level=True)

import psycopg
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from bot_arena.api import app as app_module
from bot_arena.api.app import create_app
from bot_arena.db import repository as repo
from bot_arena.engine import run_backtest
from bot_arena.risk import RiskLimits
from bot_arena.strategies import Momentum, RandomMonkey, SpyHodler


@pytest.fixture(scope="module")
def url():
    base = conninfo_to_dict(os.environ["DATABASE_URL"])
    name = f"{base.get('dbname', 'arena')}_apitest"
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        admin.execute(f'CREATE DATABASE "{name}"')
    yield make_conninfo(**{**base, "dbname": name})
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="module")
def seeded(url):
    """One saved backtest with three bots and price bars."""
    rng = np.random.default_rng(4)
    idx = pd.date_range("2026-01-05 05:00", periods=80, freq="B", tz="UTC")  # Alpaca-style timestamps
    closes = pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(rng.normal(0.001, 0.015, 80))) for s in ["AAA", "QQQ", "SPY"]}, index=idx
    )
    norm = closes.copy()
    norm.index = norm.index.normalize()
    results = [
        run_backtest(bot, norm, norm, 1000, 5.0, 0.0, RiskLimits())
        for bot in [SpyHodler(), Momentum(fast=5, slow=20), RandomMonkey(seed=1)]
    ]
    bars = closes.stack().rename("close").to_frame()
    bars.index.names = ["timestamp", "symbol"]
    bars = bars.reorder_levels(["symbol", "timestamp"]).sort_index()
    for col in ["open", "high", "low"]:
        bars[col] = bars["close"]
    bars["volume"] = 1000.0
    with repo.connect(url) as conn:
        repo.migrate(conn)
        run_id = repo.save_backtest(conn, results, {"test": True}, 1000)
        repo.save_bars(conn, bars)
        repo.save_bars(conn, bars)  # twice: must not create duplicate days
    return run_id, {r.strategy.name: r for r in results}


@pytest.fixture
def client(url, seeded):
    with TestClient(create_app(url, web_dir=None)) as c:
        yield c


def test_health_and_runs(client, seeded):
    run_id, _ = seeded
    assert client.get("/api/health").json() == {"ok": True}
    runs = client.get("/api/runs").json()
    assert [r["id"] for r in runs] == [run_id]
    assert client.get("/api/runs/default").json()["kind"] == "backtest"


def test_leaderboard_matches_the_backtest(client, seeded):
    run_id, results = seeded
    board = client.get(f"/api/runs/{run_id}/leaderboard").json()
    assert [b["rank"] for b in board["bots"]] == [1, 2, 3]
    equities = [b["equity"] for b in board["bots"]]
    assert equities == sorted(equities, reverse=True)
    for bot in board["bots"]:
        result = results[bot["name"]]
        assert bot["equity"] == pytest.approx(result.equity.iloc[-1])
        assert bot["trades"] == len(result.fills)
        assert bot["is_benchmark"] == (bot["name"] == "SPY Hodler")
        assert len(bot["sparkline"]) == 30
    assert board["as_of"] == "2026-04-24"


def test_equity_trades_and_filters(client, seeded):
    run_id, results = seeded
    series = client.get(f"/api/runs/{run_id}/equity").json()
    assert {s["name"]: len(s["points"]) for s in series} == {n: 80 for n in results}
    assert series[0]["points"][0]["t"] == "2026-01-05"

    trades = client.get(f"/api/runs/{run_id}/trades", params={"limit": 5}).json()
    assert len(trades) == 5
    assert [t["t"] for t in trades] == sorted((t["t"] for t in trades), reverse=True)
    monkey = next(
        b for b in client.get(f"/api/runs/{run_id}/leaderboard").json()["bots"] if "Monkey" in b["name"]
    )
    only = client.get(f"/api/runs/{run_id}/trades", params={"bot_id": monkey["id"], "limit": 1000}).json()
    assert {t["bot"] for t in only} == {"Random Monkey"}
    assert len(only) == len(results["Random Monkey"].fills)


def test_bot_detail_and_prices(client, seeded):
    run_id, _ = seeded
    bot_id = client.get(f"/api/runs/{run_id}/leaderboard").json()["bots"][0]["id"]
    detail = client.get(f"/api/runs/{run_id}/bots/{bot_id}").json()
    assert detail["summary"]["id"] == bot_id
    assert detail["positions"] == []  # backtests don't store holdings

    prices = client.get("/api/prices/spy").json()
    days = [p["t"] for p in prices]
    assert len(days) == 80 and days == sorted(set(days))  # one row per day, despite saving twice
    assert len(client.get("/api/prices/SPY", params={"start": "2026-04-20", "end": "2026-04-22"}).json()) == 3


@pytest.mark.parametrize(
    "path", ["/api/runs/999/leaderboard", "/api/runs/999/equity", "/api/runs/1/bots/999", "/api/prices/NOPE"]
)
def test_unknown_things_are_404(client, path):
    response = client.get(path)
    assert response.status_code == 404 and "detail" in response.json()


def test_there_are_no_write_endpoints(client):
    for path, methods in [(r.path, getattr(r, "methods", set())) for r in client.app.routes]:
        if path.startswith("/api"):
            assert not methods & {"POST", "PUT", "PATCH", "DELETE"}, path


def test_feed_pushes_new_trades(client, seeded, url, monkeypatch):
    run_id, _ = seeded
    monkeypatch.setattr(app_module, "FEED_POLL_SECONDS", 0.05)
    bot_id = client.get(f"/api/runs/{run_id}/leaderboard").json()["bots"][0]["id"]
    with client.websocket_connect(f"/api/runs/{run_id}/feed") as ws:
        with repo.connect(url) as conn:
            conn.execute(
                "INSERT INTO trades (bot_id, ts, symbol, side, shares, price, fee) "
                "VALUES (%s, '2026-04-27', 'AAA', 'buy', 2, 10, 0)",
                (bot_id,),
            )
            conn.commit()
        message = ws.receive_json()
    assert message["type"] == "trade"
    assert message["trade"]["symbol"] == "AAA" and message["trade"]["value"] == 20
    with repo.connect(url) as conn:
        conn.execute("DELETE FROM trades WHERE ts = '2026-04-27'")
        conn.commit()


def test_feed_for_unknown_run_closes(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect("/api/runs/999/feed") as ws:
        ws.receive_json()
    assert closed.value.code == 4404
