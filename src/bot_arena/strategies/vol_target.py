import math

import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.strategies.base import Strategy
from bot_arena.strategies.schedule import due, same_targets


class VolTarget(Strategy):
    """Volatility targeting: hold less of the S&P 500 when markets are jumpy, more when calm.

    Moreira & Muir (2017), "Volatility-Managed Portfolios" (Journal of Finance): scaling
    exposure by recent volatility raised Sharpe ratios, because calm periods tend to
    continue and turbulent ones bring crashes. Monthly: weight = target vol / last month's
    vol, never above 100% (no borrowing). The rest stays in cash.
    """

    name = "Vol Target"
    emoji = "🎚️"

    def __init__(self, symbol: str = "SPY", target: float = 0.15, window: int = 21):
        self.symbol, self.target, self.window = symbol, target, window
        self.started = False

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        prices = history[self.symbol].dropna() if self.symbol in history else pd.Series(dtype=float)
        if len(prices) <= self.window or not due(history, portfolio, self.started):
            return None
        self.started = True
        vol = prices.pct_change().iloc[-self.window :].std() * math.sqrt(252)
        weight = 1.0 if vol <= 0 else min(1.0, self.target / vol)
        targets = {self.symbol: round(weight, 4)}
        return None if same_targets(targets, portfolio, tolerance=0.05) else targets
