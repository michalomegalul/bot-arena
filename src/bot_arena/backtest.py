"""The simplest possible strategy: buy on day one, never sell."""

import pandas as pd


def buy_and_hold(prices: pd.Series, cash: float) -> pd.Series:
    """Equity curve of putting all `cash` into one asset at the first price.

    Uses fractional shares (Alpaca supports them), so every dollar is invested.
    Days before the asset has a price are dropped.
    """
    prices = prices.dropna()
    if prices.empty:
        raise ValueError("no prices to trade on")
    shares = cash / prices.iloc[0]
    return prices * shares


def total_return(equity: pd.Series) -> float:
    return equity.iloc[-1] / equity.iloc[0] - 1


def max_drawdown(equity: pd.Series) -> float:
    """Largest fall from a previous peak, as a negative fraction (e.g. -0.25)."""
    running_peak = equity.cummax()
    return (equity / running_peak - 1).min()
