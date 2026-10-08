import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.strategies.base import Strategy
from bot_arena.strategies.schedule import due


class Winners12m1(Strategy):
    """Cross-sectional momentum: each month, hold the best performers of the past year.

    Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers": stocks that
    rose most over the last 3-12 months kept outperforming for months. The classic "12-1"
    signal measures the return from 12 months ago to 1 month ago, skipping the last month
    because very recent winners tend to dip back. Long only here: top 3 of 6, equal weight
    (the risk manager trims single stocks to 25%).
    """

    name = "Winners 12-1"
    emoji = "🏆"

    def __init__(self, lookback: int = 252, skip: int = 21, top: int = 3):
        self.lookback, self.skip, self.top = lookback, skip, top
        self.started = False

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        if len(history) <= self.lookback or not due(history, portfolio, self.started):
            return None
        self.started = True
        past = history.iloc[-1 - self.lookback]
        recent = history.iloc[-1 - self.skip]
        score = (recent / past - 1).dropna()
        winners = sorted(score.index, key=lambda s: (-score[s], s))[: self.top]
        targets = {s: 1 / len(winners) for s in winners}
        return None if set(targets) == set(portfolio.positions) else targets
