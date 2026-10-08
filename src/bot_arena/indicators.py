"""Technical indicators. Each one only looks backwards, so it is safe to use in a backtest."""

import pandas as pd


def sma(prices: pd.Series, window: int) -> pd.Series:
    """Simple moving average. NaN until `window` prices exist."""
    return prices.rolling(window, min_periods=window).mean()


def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing), from 0 to 100.

    Below ~30 is usually read as "oversold", above ~70 as "overbought".
    NaN until `period` price changes exist.
    """
    change = prices.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    out = 100 - 100 / (1 + gain / loss)
    # No losses at all means maximum strength. `gain / 0` gives inf, which already maps to 100,
    # except when there was no movement either (0 / 0).
    return out.where(~((gain == 0) & (loss == 0)), 50.0)


def last_sma(prices: pd.Series, window: int) -> float:
    """Today's simple moving average, without computing the whole history. NaN if too short."""
    p = prices.dropna()
    return float(p.iloc[-window:].mean()) if len(p) >= window else float("nan")


def last_rsi(prices: pd.Series, period: int = 14) -> float:
    """Today's RSI from a recent window. Wilder's smoothing forgets old data fast: after 500 days
    the rest of the history weighs less than 1e-16, so the result equals the full calculation."""
    p = prices.dropna()
    if len(p) <= period:
        return float("nan")
    return float(rsi(p.iloc[-max(500, period * 30) :], period).iloc[-1])
