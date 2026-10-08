import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.indicators import last_sma
from bot_arena.strategies.base import Strategy


class Momentum(Strategy):
    """Trend following: hold the stocks whose short moving average is above their long one.

    Splits the money equally between those "uptrend" stocks and only trades when the set changes.
    """

    name = "Momentum"
    emoji = "📈"

    def __init__(self, fast: int = 20, slow: int = 50):
        self.fast, self.slow = fast, slow

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        uptrend = {
            sym
            for sym in history.columns
            if last_sma(history[sym], self.fast) > last_sma(history[sym], self.slow)
        }
        if uptrend == set(portfolio.positions):
            return None
        return {sym: 1 / len(uptrend) for sym in uptrend}
