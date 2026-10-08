"""Shared helpers for bots that rebalance on a calendar."""

import pandas as pd

from bot_arena.broker import Portfolio


def new_month(history: pd.DataFrame) -> bool:
    """True on the first trading day of a month (today's month differs from yesterday's)."""
    if len(history) < 2:
        return False
    today, yesterday = history.index[-1], history.index[-2]
    return (today.year, today.month) != (yesterday.year, yesterday.month)


def due(history: pd.DataFrame, portfolio: Portfolio, started: bool) -> bool:
    """Monthly bots act on their first chance, then on the first trading day of each month."""
    return not started or new_month(history)


def same_targets(targets: dict[str, float], portfolio: Portfolio, tolerance: float = 0.02) -> bool:
    """Would these targets leave the portfolio (almost) as it is? Avoids pointless trades."""
    held = portfolio.weights
    if set(targets) != set(held):
        return False
    return all(abs(targets[s] - held[s]) <= tolerance for s in targets)
