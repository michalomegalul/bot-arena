"""Runs one strategy over historical daily bars.

Timing rule that keeps the backtest honest (no lookahead):
a strategy decides after the close of day t, seeing only closes up to t,
and its orders fill at the OPEN of day t+1.
"""

from dataclasses import dataclass, field

import pandas as pd

from bot_arena.broker import Fill, SimBroker
from bot_arena.risk import RiskEvent
from bot_arena.strategies.base import Strategy


@dataclass
class BacktestResult:
    strategy: Strategy
    equity: pd.Series  # portfolio value at each close
    exposure: pd.Series  # fraction of equity invested at each close
    fills: list[Fill]
    events: list[RiskEvent] = field(default_factory=list)  # everything the risk manager did
    status: str = "active"  # "active" | "eliminated"


def run_backtest(
    strategy: Strategy,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    cash: float,
    slippage_bps: float = 5.0,
    fee_per_trade: float = 0.0,
) -> BacktestResult:
    """`opens` and `closes`: one row per trading day, one column per symbol."""
    broker = SimBroker(cash, slippage_bps, fee_per_trade)
    # Value holdings at the last known close if a symbol has a gap.
    valuation = closes.ffill()
    equity, exposure = {}, {}
    pending: dict[str, float] | None = None

    for i, today in enumerate(closes.index):
        if pending is not None:
            yesterday = valuation.iloc[i - 1]
            broker.rebalance(pending, opens.loc[today], today, last_known=yesterday)
            pending = None

        portfolio = broker.snapshot(valuation.loc[today])
        equity[today] = portfolio.equity
        exposure[today] = 1 - portfolio.cash / portfolio.equity

        if i < len(closes) - 1:  # no point deciding after the last day
            pending = strategy.decide(closes.iloc[: i + 1], portfolio)

    return BacktestResult(strategy, pd.Series(equity), pd.Series(exposure), broker.fills)
