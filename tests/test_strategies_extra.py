"""Tests for the research-backed bots (Faber, Antonacci, 1/N, vol targeting, RSI(2), 12-1)."""

import numpy as np
import pandas as pd
import pytest

from bot_arena.broker import Portfolio
from bot_arena.engine import run_backtest
from bot_arena.risk import RiskLimits
from bot_arena.strategies.connors_rsi2 import ConnorsRSI2
from bot_arena.strategies.dual_momentum import DualMomentum
from bot_arena.strategies.equal_weight import EqualWeight
from bot_arena.strategies.faber_trend import FaberTrend
from bot_arena.strategies.schedule import new_month
from bot_arena.strategies.vol_target import VolTarget
from bot_arena.strategies.winners import Winners12m1

EMPTY = Portfolio(cash=1000, positions={}, equity=1000, weights={})


def closes(n=300, seed=0, vol=0.01, start="2025-01-01", **drifts):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(d + rng.normal(0, vol, n))) for s, d in drifts.items()}, index=idx
    )


def holding(**weights):
    return Portfolio(cash=0, positions={s: 1.0 for s in weights}, equity=1000, weights=weights)


def first_day_of_month(history):
    """Cut history so its last row is the first trading day of a month."""
    for i in range(len(history) - 1, 0, -1):
        if new_month(history.iloc[: i + 1]):
            return history.iloc[: i + 1]
    raise AssertionError("no month change")


def test_new_month():
    idx = pd.to_datetime(["2026-01-30", "2026-02-02"], utc=True)
    assert new_month(pd.DataFrame({"A": [1, 2]}, index=idx))
    assert not new_month(pd.DataFrame({"A": [1, 2]}, index=idx[:1].append(idx[:1])))


# --- Faber trend ---


def test_faber_holds_uptrends_and_keeps_downtrend_slices_in_cash():
    history = closes(UP=0.002, DOWN=-0.002)
    assert FaberTrend().decide(history, EMPTY) == {"UP": 0.5}


def test_faber_waits_for_enough_history():
    assert FaberTrend().decide(closes(n=150, UP=0.002), EMPTY) is None


def test_faber_only_acts_monthly_after_its_first_decision():
    bot, history = FaberTrend(), closes(UP=0.002)
    assert bot.decide(history, EMPTY) is not None
    mid_month = next(history.iloc[:i] for i in range(len(history), 1, -1) if not new_month(history.iloc[:i]))
    assert bot.decide(mid_month, holding(UP=1.0)) is None
    assert bot.decide(first_day_of_month(history), holding(UP=1.0)) == {"UP": 1.0}


# --- Dual momentum ---


def test_dual_momentum_picks_the_stronger_fund():
    history = closes(SPY=0.0005, QQQ=0.0015, NVDA=0.01)
    assert DualMomentum().decide(history, EMPTY) == {"QQQ": 1.0}  # NVDA is not one of its funds


def test_dual_momentum_goes_to_cash_when_both_fall():
    history = closes(SPY=-0.002, QQQ=-0.001)
    assert DualMomentum().decide(history, holding(QQQ=1.0)) == {}


def test_dual_momentum_does_not_trade_when_the_winner_is_already_held():
    history = closes(SPY=0.0005, QQQ=0.0015)
    assert DualMomentum().decide(history, holding(QQQ=1.0)) is None


# --- Equal weight ---


def test_equal_weight_splits_and_then_waits_for_the_next_month():
    bot, history = EqualWeight(), closes(n=40, A=0, B=0, C=0, D=0)
    assert bot.decide(history, EMPTY) == {s: 0.25 for s in "ABCD"}
    assert bot.decide(history, holding(A=0.4, B=0.2, C=0.2, D=0.2)) is None  # not a new month


def test_equal_weight_rebalances_drift_at_the_month_start():
    bot, history = EqualWeight(), closes(n=60, A=0, B=0)
    bot.decide(history, EMPTY)
    assert bot.decide(first_day_of_month(history), holding(A=0.7, B=0.3)) == {"A": 0.5, "B": 0.5}
    assert bot.decide(first_day_of_month(history), holding(A=0.51, B=0.49)) is None  # close enough


# --- Vol target ---


def test_vol_target_holds_less_when_markets_are_jumpy():
    calm = VolTarget().decide(closes(n=60, vol=0.004, SPY=0.0005), EMPTY)
    wild = VolTarget().decide(closes(n=60, vol=0.03, SPY=0.0005), EMPTY)
    assert calm == {"SPY": 1.0}  # never above 100%
    assert 0 < wild["SPY"] < 0.5


# --- Connors RSI(2) ---


def test_connors_buys_a_sharp_dip_in_an_uptrend_only():
    up = closes(n=260, vol=0.004, UP=0.002, DOWN=-0.002)
    up.iloc[-2:, :] *= np.array([[0.97, 0.97], [0.94, 0.94]])  # two sharp down days for both
    assert ConnorsRSI2().decide(up, EMPTY) == {"UP": 0.25}  # DOWN is below its 200-day average


def test_connors_sells_once_price_closes_above_its_5_day_average():
    history = closes(n=260, vol=0.004, UP=0.002)
    history.iloc[-1, 0] *= 1.03  # strong close
    assert ConnorsRSI2().decide(history, holding(UP=0.25)) == {}


# --- Winners 12-1 ---


def test_winners_hold_the_top_three_and_skip_the_last_month():
    history = closes(n=300, vol=0.002, A=0.003, B=0.002, C=0.001, D=0.0, E=-0.001)
    assert set(Winners12m1().decide(history, EMPTY)) == {"A", "B", "C"}

    # A crashes only in the last month: 12-1 ignores that month, so A still ranks first.
    crashed = history.copy()
    crashed.iloc[-15:, 0] *= 0.5
    assert "A" in Winners12m1().decide(crashed, EMPTY)


# --- every bot through a full backtest ---

ALL = [FaberTrend, DualMomentum, EqualWeight, VolTarget, ConnorsRSI2, Winners12m1]


@pytest.mark.parametrize("bot_class", ALL)
@pytest.mark.parametrize("fee", [0.0, 1.0])
def test_full_backtest_with_risk_limits_and_fees(bot_class, fee):
    history = closes(
        n=520, vol=0.015, SPY=0.0004, QQQ=0.0006, AAPL=0.0008, MSFT=0.0003, NVDA=0.001, TSLA=-0.0002
    )
    result = run_backtest(bot_class(), history, history, 1000, 5.0, fee, RiskLimits())
    assert (result.equity > 0).all()
    assert result.exposure.between(-1e-9, 1 + 1e-9).all()  # cash never negative
    assert result.fills, f"{bot_class.name} never traded"


def test_names_and_emojis_are_unique_across_all_bots():
    from bot_arena.strategies import roster

    bots = [*roster(), *(c() for c in ALL)]
    assert len({b.name for b in bots}) == len(bots)
    assert len({b.emoji for b in bots}) == len(bots)
