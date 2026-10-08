import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.strategies.base import Strategy


class SpyHodler(Strategy):
    """Buys the S&P 500 on day one and never sells. The benchmark everyone has to beat."""

    name = "SPY Hodler"
    emoji = "🐢"

    def __init__(self, symbol: str = "SPY"):
        self.symbol = symbol

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        if self.symbol in portfolio.positions or pd.isna(history[self.symbol].iloc[-1]):
            return None
        return {self.symbol: 1.0}
