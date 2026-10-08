import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.indicators import last_rsi
from bot_arena.strategies.base import Strategy


class MeanReversion(Strategy):
    """Buy the dip: buys stocks that fell hard (low RSI) and sells once they bounce back.

    Each position gets a fixed slot of the portfolio, so it holds at most 1/slot stocks.
    """

    name = "Mean Reversion"
    emoji = "🔄"

    def __init__(self, period: int = 14, buy_below: float = 30, sell_above: float = 55, slot: float = 0.25):
        self.period, self.buy_below, self.sell_above, self.slot = period, buy_below, sell_above, slot

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        strength = {sym: last_rsi(history[sym], self.period) for sym in history.columns}  # NaN = too new

        keep = {s: w for s, w in portfolio.weights.items() if not strength.get(s, 0) > self.sell_above}
        free_slots = round(1 / self.slot) - len(keep)
        # Most oversold first.
        candidates = sorted(
            (s for s, v in strength.items() if v < self.buy_below and s not in keep),
            key=lambda s: strength[s],
        )
        new = candidates[:free_slots]

        if not new and len(keep) == len(portfolio.weights):
            return None
        # Winners can grow past their slot; new positions only get the cash that is really left.
        size = min(self.slot, (1 - sum(keep.values())) / len(new)) if new else 0.0
        return keep | {s: size for s in new}
