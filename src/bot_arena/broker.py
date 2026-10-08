"""A simulated broker: one bot's private ledger of cash and shares."""

import math
from dataclasses import dataclass

import pandas as pd

# Trades smaller than this are skipped, so tiny price drifts don't cause endless rebalancing.
MIN_TRADE_DOLLARS = 1.0
# With a fee, a trade must also be at least this many times the fee (fee <= 5% of the trade).
MIN_TRADE_FEE_MULTIPLE = 20
# An existing position is only resized if it is off target by more than this share of equity.
DRIFT_TOLERANCE = 0.02


@dataclass(frozen=True)
class Fill:
    date: pd.Timestamp
    symbol: str
    side: str  # "buy" or "sell"
    shares: float
    price: float  # after slippage
    fee: float


@dataclass(frozen=True)
class Portfolio:
    """Read-only snapshot a strategy gets to see. Strategies cannot touch the broker."""

    cash: float
    positions: dict[str, float]  # symbol -> shares
    equity: float
    weights: dict[str, float]  # symbol -> fraction of equity


class SimBroker:
    """Fills orders at a given price, with slippage and a per-trade fee.

    Fractional shares, long only, no margin: cash never goes below zero.
    """

    def __init__(self, cash: float, slippage_bps: float = 5.0, fee_per_trade: float = 0.0):
        self.cash = cash
        self.positions: dict[str, float] = {}
        self.fills: list[Fill] = []
        self.slippage = slippage_bps / 10_000
        self.fee_per_trade = fee_per_trade
        self.min_trade = max(MIN_TRADE_DOLLARS, MIN_TRADE_FEE_MULTIPLE * fee_per_trade)

    def equity(self, prices: pd.Series) -> float:
        return self.cash + sum(shares * prices[sym] for sym, shares in self.positions.items())

    def snapshot(self, prices: pd.Series) -> Portfolio:
        equity = self.equity(prices)
        weights = {sym: shares * prices[sym] / equity for sym, shares in self.positions.items()}
        return Portfolio(self.cash, dict(self.positions), equity, weights)

    def rebalance(
        self,
        targets: dict[str, float],
        prices: pd.Series,
        date: pd.Timestamp,
        last_known: pd.Series | None = None,
    ) -> None:
        """Trade towards `targets` (symbol -> fraction of equity). Held symbols not listed are sold.

        Symbols without a price in `prices` are not traded; for sizing, they are valued at
        `last_known` (e.g. the previous close) so the other targets stay correct.
        Small resizes of existing positions (within DRIFT_TOLERANCE) are skipped.
        """
        validate_targets(targets)
        tradable = sorted(sym for sym in set(targets) | set(self.positions) if _has_price(prices, sym))
        equity = self.cash + sum(
            shares * (prices[sym] if sym in tradable else _price_or_zero(last_known, sym))
            for sym, shares in self.positions.items()
        )
        deltas = {}
        for sym in tradable:
            target = targets.get(sym, 0.0)
            delta = target * equity - self.positions.get(sym, 0.0) * prices[sym]
            resize = sym in self.positions and target > 0
            if resize and abs(delta) < DRIFT_TOLERANCE * equity:
                continue
            deltas[sym] = delta
        # Sell first so the cash is there for the buys. Sorted, so results never depend on set order.
        for sym, delta in deltas.items():
            if delta <= -self.min_trade:
                self._sell(sym, -delta, prices[sym], date)
        for sym, delta in deltas.items():
            if delta >= self.min_trade:
                self._buy(sym, delta, prices[sym], date)

    def _sell(self, sym: str, dollars: float, price: float, date: pd.Timestamp) -> None:
        shares = min(dollars / price, self.positions[sym])
        fill_price = price * (1 - self.slippage)
        self.cash += shares * fill_price - self.fee_per_trade
        remaining = self.positions[sym] - shares
        if remaining * price < self.min_trade:  # don't leave dust behind
            shares += remaining
            self.cash += remaining * fill_price
            remaining = 0.0
        if remaining:
            self.positions[sym] = remaining
        else:
            del self.positions[sym]
        self.fills.append(Fill(date, sym, "sell", shares, fill_price, self.fee_per_trade))

    def _buy(self, sym: str, dollars: float, price: float, date: pd.Timestamp) -> None:
        fill_price = price * (1 + self.slippage)
        dollars = min(dollars, self.cash - self.fee_per_trade)  # slippage can make us a bit short
        if dollars < self.min_trade:
            return
        shares = dollars / fill_price
        self.cash -= dollars + self.fee_per_trade
        self.positions[sym] = self.positions.get(sym, 0.0) + shares
        self.fills.append(Fill(date, sym, "buy", shares, fill_price, self.fee_per_trade))


def validate_targets(targets: dict[str, float]) -> None:
    if any(w < 0 or math.isnan(w) for w in targets.values()):
        raise ValueError(f"weights must be >= 0 (no shorting): {targets}")
    if sum(targets.values()) > 1 + 1e-9:
        raise ValueError(f"weights add up to more than 100% (no margin): {targets}")


def _has_price(prices: pd.Series | None, sym: str) -> bool:
    return prices is not None and sym in prices.index and not pd.isna(prices[sym])


def _price_or_zero(prices: pd.Series | None, sym: str) -> float:
    return float(prices[sym]) if _has_price(prices, sym) else 0.0
