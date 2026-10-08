import numpy as np
import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.strategies.base import Strategy


class RandomMonkey(Strategy):
    """Every so often, throws darts: a random 1-3 stocks with random weights.

    A sanity check. A strategy that can't beat the monkey has no skill.
    Seeded, so a backtest gives the same result every time.
    """

    name = "Random Monkey"
    emoji = "🐒"

    def __init__(self, seed: int = 42, trade_prob: float = 0.1):
        self.rng = np.random.default_rng(seed)
        self.trade_prob = trade_prob

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        if portfolio.positions and self.rng.random() >= self.trade_prob:
            return None
        available = [s for s in history.columns if not pd.isna(history[s].iloc[-1])]
        picks = self.rng.choice(available, size=min(len(available), self.rng.integers(1, 4)), replace=False)
        weights = self.rng.dirichlet(np.ones(len(picks)))
        return {str(s): float(w) for s, w in zip(picks, weights, strict=True)}
