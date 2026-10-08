import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.indicators import last_sma
from bot_arena.strategies.base import Strategy
from bot_arena.strategies.schedule import due


class FaberTrend(Strategy):
    """Trend filter: hold an asset only while it is above its 200-day average, else cash.

    Faber (2007), "A Quantitative Approach to Tactical Asset Allocation": checked once a month,
    each asset gets an equal slice (1/N). Below its long average, its slice sits in cash.
    The idea is not to beat the market in good times but to sidestep the worst crashes.
    """

    name = "Faber Trend"
    emoji = "🧭"

    def __init__(self, window: int = 200):
        self.window = window
        self.started = False

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        if len(history) < self.window or not due(history, portfolio, self.started):
            return None
        self.started = True
        symbols = [s for s in history.columns if not pd.isna(history[s].iloc[-1])]
        slice_ = 1 / len(symbols)
        targets = {s: slice_ for s in symbols if history[s].iloc[-1] > last_sma(history[s], self.window)}
        return targets
