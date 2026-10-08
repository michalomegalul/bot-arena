import pandas as pd
import pytest

from bot_arena import metrics
from bot_arena.backtest import buy_and_hold


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
    assert metrics.total_return(series(1000.0, 1250.0)) == pytest.approx(0.25)


def test_max_drawdown_measures_from_the_peak_not_the_start():
    # Up to 200, down to 150 (-25% from peak), recovers. The start (100) is irrelevant.
    assert metrics.max_drawdown(series(100.0, 200.0, 150.0, 210.0)) == pytest.approx(-0.25)


def test_cagr_of_exactly_one_year():
    equity = pd.Series([1000.0] * 252 + [1100.0])  # 252 daily steps = one trading year
    assert metrics.cagr(equity) == pytest.approx(0.10)


def test_flat_equity_has_zero_risk_metrics():
    flat = series(1000.0, 1000.0, 1000.0)
    assert metrics.sharpe(flat) == 0.0
    assert metrics.sortino(flat) == 0.0
    assert metrics.volatility(flat) == 0.0


def test_sharpe_is_positive_for_steady_gains_and_negative_for_losses():
    assert metrics.sharpe(series(100.0, 101.0, 103.0, 104.0)) > 0
    assert metrics.sharpe(series(100.0, 99.0, 97.0, 96.0)) < 0


def test_sortino_ignores_upside_volatility():
    # Same small dips, much bigger up moves. Sharpe counts the big up moves as risk,
    # Sortino doesn't, so Sortino rewards the wild curve more than Sharpe does.
    calm = series(100.0, 102.0, 101.0, 103.0)
    wild = series(100.0, 110.0, 108.9, 120.0)
    assert metrics.sortino(wild) / metrics.sortino(calm) > metrics.sharpe(wild) / metrics.sharpe(calm)


def test_sortino_matches_a_hand_calculation():
    equity = series(100.0, 110.0, 99.0)  # +10%, then -10%
    # mean = 0, so Sortino is 0 regardless of the downside.
    assert metrics.sortino(equity) == pytest.approx(0.0)
    equity = series(100.0, 120.0, 108.0)  # +20%, -10%: mean 5%, downside dev sqrt((0 + 0.01) / 2)
    assert metrics.sortino(equity) == pytest.approx(0.05 / (0.01 / 2) ** 0.5 * 252**0.5)


def test_env_example_contains_no_secrets():
    """.env.example is committed; real keys belong only in .env (which git ignores)."""
    from pathlib import Path

    for line in Path(__file__).parent.parent.joinpath(".env.example").read_text().splitlines():
        if line.startswith(("ALPACA_API_KEY=", "ALPACA_SECRET_KEY=", "ANTHROPIC_API_KEY=")):
            assert line.endswith("="), f"looks like a real key in .env.example: {line.split('=')[0]}"
