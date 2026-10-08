import numpy as np
import pandas as pd
import pytest

from bot_arena.broker import Portfolio
from bot_arena.engine import run_backtest
from bot_arena.strategies import MeanReversion, Momentum, RandomMonkey, SpyHodler

EMPTY = Portfolio(cash=1000, positions={}, equity=1000, weights={})


def closes(n=120, seed=0, **trends):
    """Random-walk prices per symbol with a daily drift, e.g. closes(UP=0.01, DOWN=-0.01)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(d + rng.normal(0, 0.01, n))) for s, d in trends.items()}, index=idx
    )


def test_hodler_buys_once_then_holds():
    history = closes(SPY=0.0, QQQ=0.0)
    assert SpyHodler().decide(history, EMPTY) == {"SPY": 1.0}
    holding = Portfolio(0, {"SPY": 10}, 1000, {"SPY": 1.0})
    assert SpyHodler().decide(history, holding) is None


def test_momentum_holds_uptrends_only():
    history = closes(UP=0.01, DOWN=-0.01, UP2=0.008)
    assert Momentum().decide(history, EMPTY) == {"UP": 0.5, "UP2": 0.5}


def test_momentum_does_nothing_before_it_has_enough_history():
    assert Momentum(fast=20, slow=50).decide(closes(n=30, UP=0.01), EMPTY) is None


def test_mean_reversion_buys_the_crash_and_sells_the_bounce():
    history = closes(CRASH=0.0, CALM=0.005)  # CALM trends up, never oversold
    history.iloc[-6:, 0] *= np.linspace(0.97, 0.80, 6)  # CRASH falls ~20% in a week
    assert MeanReversion().decide(history, EMPTY) == {"CRASH": 0.25}

    bounced = closes(CRASH=0.02, CALM=0.005)  # now strongly up, RSI high
    holding = Portfolio(750, {"CRASH": 2.5}, 1000, {"CRASH": 0.25})
    assert MeanReversion().decide(bounced, holding) == {}


def test_mean_reversion_buys_even_when_winners_have_grown_past_their_slots():
    # Review repro: three holdings drifted to 26% each used to block the 4th slot.
    history = closes(A=0.005, B=0.005, C=0.005, CRASH=0.0)
    history.iloc[-6:, 3] *= np.linspace(0.97, 0.80, 6)
    held = {"A": 0.26, "B": 0.26, "C": 0.26}
    portfolio = Portfolio(220, {s: 1.0 for s in held}, 1000, held)
    targets = MeanReversion(sell_above=101).decide(history, portfolio)  # never sell, to isolate buying
    assert targets["CRASH"] == pytest.approx(0.22)
    assert sum(targets.values()) <= 1 + 1e-9


def test_monkey_is_reproducible_and_stays_within_limits():
    history = closes(A=0.0, B=0.0, C=0.0, D=0.0)
    first, second = RandomMonkey(seed=7), RandomMonkey(seed=7)
    for _ in range(20):
        a = first.decide(history, EMPTY)
        assert a == second.decide(history, EMPTY)
        assert 1 <= len(a) <= 3
        assert all(w >= 0 for w in a.values()) and sum(a.values()) <= 1 + 1e-9


@pytest.mark.parametrize("fee", [0.0, 1.0, 5.0])
def test_every_bot_survives_a_full_backtest_with_fees(fee):
    history = closes(n=300, SPY=0.0005, QQQ=0.001, AAA=-0.001, BBB=0.0)
    for bot in [SpyHodler(), Momentum(), MeanReversion(), RandomMonkey()]:
        result = run_backtest(bot, history, history, cash=1000, fee_per_trade=fee)
        assert (result.equity > 0).all()
        # exposure <= 100% means cash never went negative
        assert result.exposure.between(-1e-9, 1 + 1e-9).all(), bot.name
