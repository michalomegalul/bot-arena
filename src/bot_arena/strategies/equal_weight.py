import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.strategies.base import Strategy
from bot_arena.strategies.schedule import due, same_targets


class EqualWeight(Strategy):
    """1/N: split the money equally across everything and rebalance once a month.

    DeMiguel, Garlappi & Uppal (2009), "Optimal Versus Naive Diversification": none of 14
    clever optimisation methods reliably beat this naive split out of sample. Rebalancing
    sells a little of what went up and buys what went down.
    """

    name = "Equal Weight"
    emoji = "🍰"

    def __init__(self):
        self.started = False

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        if not due(history, portfolio, self.started):
            return None
        self.started = True
        symbols = [s for s in history.columns if not pd.isna(history[s].iloc[-1])]
        if not symbols:
            return None
        targets = {s: 1 / len(symbols) for s in symbols}
        return None if same_targets(targets, portfolio) else targets
