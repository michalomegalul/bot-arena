import pandas as pd
import pytest

from bot_arena.backtest import buy_and_hold, max_drawdown, total_return


def series(*values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values)))


def test_buy_and_hold_scales_with_price():
    equity = buy_and_hold(series(100.0, 110.0, 50.0), cash=1000)
    assert list(equity) == [1000.0, 1100.0, 500.0]


def test_buy_and_hold_skips_days_without_a_price():
    equity = buy_and_hold(series(None, 20.0, 40.0), cash=1000)
    assert list(equity) == [1000.0, 2000.0]


def test_buy_and_hold_needs_prices():
    with pytest.raises(ValueError):
        buy_and_hold(series(None, None), cash=1000)


def test_total_return():
    assert total_return(series(1000.0, 1250.0)) == pytest.approx(0.25)


def test_max_drawdown_measures_from_the_peak_not_the_start():
    # Up to 200, down to 150 (-25% from peak), recovers. The start (100) is irrelevant.
    assert max_drawdown(series(100.0, 200.0, 150.0, 210.0)) == pytest.approx(-0.25)
