import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.strategies.base import Strategy
from bot_arena.strategies.schedule import due


class DualMomentum(Strategy):
    """Dual momentum: own the stronger index fund, but only if it actually went up; else cash.

    Antonacci (2012/2014), "Risk Premia Harvesting Through Dual Momentum": relative momentum
    picks the better of two equity funds over the last 12 months; absolute momentum moves
    to cash when even the winner is down (the paper compares with T-bills; here cash = 0%).
    Checked monthly, holds one fund at a time.
    """

    name = "Dual Momentum"
    emoji = "🥇"

    def __init__(self, funds: tuple[str, ...] = ("SPY", "QQQ"), lookback: int = 252):
        self.funds, self.lookback = funds, lookback
        self.started = False

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        funds = [f for f in self.funds if f in history.columns]
        if len(history) <= self.lookback or not funds or not due(history, portfolio, self.started):
            return None
        self.started = True
        past = {f: history[f].iloc[-1] / history[f].iloc[-1 - self.lookback] - 1 for f in funds}
        best = max(funds, key=lambda f: (past[f], f))
        targets = {best: 1.0} if past[best] > 0 else {}
        return None if set(targets) == set(portfolio.positions) else targets
