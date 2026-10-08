import pandas as pd
import pytest

from bot_arena.broker import Portfolio
from bot_arena.engine import run_backtest
from bot_arena.strategies.base import Strategy

DATES = pd.date_range("2026-01-05", periods=5, freq="B")


def frame(values):
    return pd.DataFrame({"AAA": values}, index=DATES, dtype=float)


class Spy(Strategy):
    """Records what it was shown, and buys on the first day."""

    name, emoji = "spy", "🕵"

    def __init__(self):
        self.seen = []

    def decide(self, history, portfolio: Portfolio):
        self.seen.append(history.copy())
        return {"AAA": 1.0} if not portfolio.positions else None


def test_strategy_never_sees_the_future():
    closes = frame([10, 11, 12, 13, 14])
    spy = Spy()
    run_backtest(spy, closes, closes, cash=1000)
    for day, history in zip(DATES, spy.seen, strict=False):
        assert history.index[-1] == day
        assert history.index.max() <= day


def test_orders_fill_at_the_next_open_not_todays_close():
    opens = frame([100, 200, 200, 200, 200])
    closes = frame([10, 10, 10, 10, 10])  # if it filled at a close, the price would be 10
    result = run_backtest(Spy(), opens, closes, cash=1000, slippage_bps=0)
    (fill,) = result.fills
    assert fill.date == DATES[1]
    assert fill.price == 200


def test_no_decision_after_the_last_day():
    closes = frame([10, 11, 12, 13, 14])
    spy = Spy()
    run_backtest(spy, closes, closes, cash=1000)
    assert len(spy.seen) == len(DATES) - 1


def test_equity_and_exposure_tracking():
    opens = frame([10, 10, 10, 10, 10])
    closes = frame([10, 10, 20, 20, 5])
    result = run_backtest(Spy(), opens, closes, cash=1000, slippage_bps=0)
    assert result.equity.tolist() == pytest.approx([1000, 1000, 2000, 2000, 500])
    assert result.exposure.tolist() == pytest.approx([0, 1, 1, 1, 1])
