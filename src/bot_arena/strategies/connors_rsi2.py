import pandas as pd

from bot_arena.broker import Portfolio
from bot_arena.indicators import rsi, sma
from bot_arena.strategies.base import Strategy


class ConnorsRSI2(Strategy):
    """Short-term pullbacks in an uptrend: buy after a sharp 1-2 day drop, sell on the bounce.

    Larry Connors' RSI(2) (Connors & Alvarez, "Short Term Trading Strategies That Work", 2008):
    only when a stock is above its 200-day average, buy if its 2-day RSI falls below 10;
    sell when it closes above its 5-day average. Trades often, holds for days.
    Each position gets a fixed slot (25%), so at most four at once.
    """

    name = "Connors RSI2"
    emoji = "🎯"

    def __init__(self, entry: float = 10, trend: int = 200, exit_window: int = 5, slot: float = 0.25):
        self.entry, self.trend, self.exit_window, self.slot = entry, trend, exit_window, slot

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        keep, buys = {}, []
        for sym in history.columns:
            prices = history[sym].dropna()
            if len(prices) < self.trend:
                continue
            price = prices.iloc[-1]
            if sym in portfolio.weights:
                if price <= sma(prices, self.exit_window).iloc[-1]:
                    keep[sym] = portfolio.weights[sym]  # no bounce yet: hold
            elif price > sma(prices, self.trend).iloc[-1] and rsi(prices, 2).iloc[-1] < self.entry:
                buys.append((rsi(prices, 2).iloc[-1], sym))

        free = round(1 / self.slot) - len(keep)
        new = [sym for _, sym in sorted(buys)[: max(free, 0)]]  # most oversold first
        if not new and len(keep) == len(portfolio.weights):
            return None
        size = min(self.slot, (1 - sum(keep.values())) / len(new)) if new else 0.0
        return keep | {s: size for s in new}
