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
