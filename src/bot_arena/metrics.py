"""Performance metrics for an equity curve of daily closes."""

import math

import pandas as pd

TRADING_DAYS = 252


def total_return(equity: pd.Series) -> float:
    return equity.iloc[-1] / equity.iloc[0] - 1


def cagr(equity: pd.Series) -> float:
    """Compound annual growth rate: the yearly return that would give the same result."""
    years = (len(equity) - 1) / TRADING_DAYS
    return (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0


def volatility(equity: pd.Series) -> float:
    """Annualized standard deviation of daily returns."""
    return equity.pct_change().std() * math.sqrt(TRADING_DAYS)


def sharpe(equity: pd.Series) -> float:
    """Return per unit of risk (risk-free rate taken as 0). Above 1 is good, above 2 is rare."""
    daily = equity.pct_change().dropna()
    std = daily.std()
    return daily.mean() / std * math.sqrt(TRADING_DAYS) if std > 0 else 0.0


def sortino(equity: pd.Series) -> float:
    """Like Sharpe, but only counts downside moves as risk."""
    daily = equity.pct_change().dropna()
    downside = math.sqrt((daily.clip(upper=0) ** 2).mean())
    return daily.mean() / downside * math.sqrt(TRADING_DAYS) if downside > 0 else 0.0


def max_drawdown(equity: pd.Series) -> float:
    """Largest fall from a previous peak, as a negative fraction (e.g. -0.25)."""
    return (equity / equity.cummax() - 1).min()
