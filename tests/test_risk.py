import pandas as pd
import pytest

from bot_arena.broker import Portfolio
from bot_arena.engine import run_backtest
from bot_arena.risk import LocalKillSwitch, RiskLimits, RiskManager
from bot_arena.strategies.base import Strategy

DAY = pd.Timestamp("2026-01-05")


def pf(equity=1000.0, **weights):
    return Portfolio(
        cash=equity * (1 - sum(weights.values())),
        positions={s: 1.0 for s in weights},
        equity=equity,
        weights=weights,
    )


class Switch:
    def __init__(self):
        self.reason = None

    def check(self):
        return self.reason


def manager(**limits):
    return RiskManager("bot", RiskLimits(**limits))


# --- position limits ---


def test_single_stocks_are_capped_but_index_funds_are_not():
    approved = manager().review({"NVDA": 0.6, "SPY": 0.4}, pf(), DAY)
    assert approved == {"NVDA": 0.25, "SPY": 0.4}
    assert manager().review({"SPY": 1.0}, pf(), DAY) == {"SPY": 1.0}


def test_clipping_is_logged():
    risk = manager()
    risk.review({"NVDA": 0.6}, pf(), DAY)
    (event,) = risk.events
    assert event.kind == "clipped" and "NVDA" in event.detail


def test_too_many_positions_keeps_the_biggest():
    approved = manager(max_positions=2).review({"A": 0.1, "B": 0.2, "C": 0.15}, pf(), DAY)
    assert approved == {"B": 0.2, "C": 0.15}


def test_unknown_symbols_are_dropped():
    risk = manager(allowed_symbols=frozenset({"AAPL"}))
    assert risk.review({"AAPL": 0.2, "GME": 0.2}, pf(), DAY) == {"AAPL": 0.2}
    assert risk.events[0].kind == "dropped"


@pytest.mark.parametrize(
    "targets",
    [{"A": -0.1}, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25, "E": 0.25}, {"A": float("nan")}],
)
def test_invalid_orders_are_rejected_without_crashing(targets):
    risk = manager()
    assert risk.review(targets, pf(), DAY) is None
    assert risk.events[0].kind == "rejected"


def test_risk_never_increases_what_a_bot_asked_for():
    asked = {"A": 0.1, "SPY": 0.3}
    assert manager().review(asked, pf(), DAY) == asked


# --- drawdown breaker ---


def test_drawdown_breaker_eliminates_and_sells_everything():
    risk = manager(max_drawdown=0.30)
    risk.review(None, pf(1000, A=0.2), DAY)
    risk.review(None, pf(1500, A=0.2), DAY)  # new peak
    assert risk.review({"A": 0.25}, pf(1060, A=0.2), DAY) == {"A": 0.25}  # -29%: still alive
    assert risk.review({"A": 0.25}, pf(1050, A=0.2), DAY) == {}  # -30%: out
    assert risk.eliminated and risk.events[-1].kind == "eliminated"


def test_eliminated_bot_stays_frozen_even_after_a_recovery():
    risk = manager(max_drawdown=0.30)
    risk.review(None, pf(1000), DAY)
    risk.review(None, pf(600, A=0.5), DAY)
    assert risk.review({"A": 0.25}, pf(2000), DAY) is None  # sold out, flat: nothing more to do
    assert risk.review({"A": 0.25}, pf(2000, A=0.1), DAY) == {}  # still holding: keep selling


# --- kill switch ---


def test_kill_switch_blocks_everything_including_selling():
    switch = Switch()
    risk = RiskManager("bot", RiskLimits(), switch)
    switch.reason = "manual stop"
    assert risk.review({"SPY": 1.0}, pf(), DAY) is None
    assert risk.review({}, pf(SPY=1.0), DAY) is None


def test_kill_switch_beats_the_drawdown_breaker():
    switch = Switch()
    risk = RiskManager("bot", RiskLimits(max_drawdown=0.1), switch)
    risk.review(None, pf(1000, A=0.2), DAY)
    switch.reason = "stop"
    assert risk.review(None, pf(500, A=0.2), DAY) is None  # no forced selling while halted
    assert not risk.eliminated


def test_kill_switch_logs_only_when_it_changes():
    switch = Switch()
    risk = RiskManager("bot", RiskLimits(), switch)
    switch.reason = "stop"
    for _ in range(5):
        risk.review({"SPY": 1.0}, pf(), DAY)
    switch.reason = None
    assert risk.review({"SPY": 1.0}, pf(), DAY) == {"SPY": 1.0}
    assert [e.detail for e in risk.events] == ["all trading halted: stop", "released, trading resumes"]


def test_local_kill_switch_file_and_env(tmp_path, monkeypatch):
    switch = LocalKillSwitch(path=tmp_path / "KILL", env_var="TEST_KILL")
    assert switch.check() is None
    (tmp_path / "KILL").write_text("market is on fire\n")
    assert switch.check() == "market is on fire"
    (tmp_path / "KILL").unlink()
    monkeypatch.setenv("TEST_KILL", "1")
    assert switch.check() == "TEST_KILL is set"


# --- inside a backtest ---


class AllIn(Strategy):
    name, emoji = "all in", "🎰"

    def decide(self, history, portfolio):
        return None if portfolio.positions else {"AAA": 1.0}


def frame(values):
    return pd.DataFrame({"AAA": values}, index=pd.date_range("2026-01-05", periods=len(values), freq="B"))


def test_backtest_eliminates_a_bot_that_crashes():
    prices = frame([100.0, 100.0, 60.0, 60.0, 200.0, 200.0])  # -40%, then a rally it misses
    result = run_backtest(AllIn(), prices, prices, 1000, slippage_bps=0, limits=RiskLimits(max_weight=1.0))
    assert result.status == "eliminated"
    assert result.equity.iloc[-1] == pytest.approx(600)  # sold at 60, missed the rally
    assert [f.side for f in result.fills] == ["buy", "sell"]


def test_backtest_with_kill_switch_never_trades():
    switch = Switch()
    switch.reason = "halt"
    prices = frame([100.0, 110.0, 120.0])
    result = run_backtest(AllIn(), prices, prices, 1000, kill_switch=switch)
    assert result.fills == []
    assert result.equity.tolist() == [1000, 1000, 1000]


def test_any_kill_switch_reports_the_first_engaged_reason():
    from bot_arena.risk import AnyKillSwitch, NoKillSwitch

    a, b = Switch(), Switch()
    combined = AnyKillSwitch(NoKillSwitch(), a, b)
    assert combined.check() is None
    b.reason = "db says stop"
    assert combined.check() == "db says stop"


def test_database_kill_switch_fails_closed():
    import psycopg

    from bot_arena.db.repository import DbKillSwitch

    class BrokenConnection:
        def execute(self, *args):
            raise psycopg.OperationalError("server closed the connection")

        def rollback(self):
            raise psycopg.OperationalError("still closed")

    reason = DbKillSwitch(BrokenConnection()).check()
    assert reason is not None and "halting to be safe" in reason
