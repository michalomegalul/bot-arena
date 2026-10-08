import pandas as pd
import pytest

from bot_arena.indicators import rsi, sma


def test_sma_needs_a_full_window():
    out = sma(pd.Series([1.0, 2.0, 3.0, 4.0]), 3)
    assert out.isna().tolist() == [True, True, False, False]
    assert out.iloc[-1] == pytest.approx(3.0)


def test_rsi_extremes():
    up = pd.Series(range(1, 31), dtype=float)
    assert rsi(up).iloc[-1] == pytest.approx(100.0)
    assert rsi(up[::-1].reset_index(drop=True)).iloc[-1] == pytest.approx(0.0)


def test_rsi_of_a_flat_line_is_neutral():
    assert rsi(pd.Series([5.0] * 30)).iloc[-1] == 50.0


def test_rsi_does_not_look_ahead():
    prices = pd.Series([10, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18, 17], dtype=float)
    full = rsi(prices, 5)
    for t in range(len(prices)):
        partial = rsi(prices.iloc[: t + 1], 5)
        assert partial.iloc[-1] == pytest.approx(full.iloc[t], nan_ok=True)
