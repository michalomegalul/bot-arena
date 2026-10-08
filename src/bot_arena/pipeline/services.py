"""The broker and the bots, as pipeline services.

Both reuse exactly the backtest's pieces (SimBroker, RiskManager, the strategies), so a
replay through the pipeline gives the same results as `arena backtest`.
"""

from collections.abc import Mapping

import pandas as pd

from bot_arena.broker import SimBroker
from bot_arena.pipeline import events as ev
from bot_arena.pipeline.events import Event
from bot_arena.risk import KillSwitch, RiskLimits, RiskManager
from bot_arena.strategies.base import Strategy


class BrokerService:
    """Owns every bot's ledger. Fills decisions at the next day's open, then reports portfolios."""

    name = "broker"

    def __init__(self):
        self.recorded: Mapping[str, Event] = {}
        self.ledgers: dict[str, SimBroker] = {}
        self.pending: dict[str, dict[str, float]] = {}
        self.opens: dict[str, dict[str, float]] = {}  # day -> symbol -> open
        self.closes: dict[str, dict[str, float]] = {}  # day -> symbol -> close
        self.last_close: dict[str, float] = {}  # symbol -> latest close (for valuation)

    def handle(self, event: Event) -> list[Event]:
        if event.type == ev.RUN:
            d = event.data
            self.ledgers = {b: SimBroker(d["cash"], d["slippage_bps"], d["fee"]) for b in d["bots"]}
        elif event.type == ev.BAR and not event.data.get("warmup"):
            self.opens.setdefault(event.date, {})[event.key] = event.data["open"]
            self.closes.setdefault(event.date, {})[event.key] = event.data["close"]
        elif event.type == ev.DECISION and event.key in self.ledgers:
            targets = event.data["targets"]
            if targets is not None:
                self.pending[event.key] = targets
        elif event.type == ev.CLOSE:
            return self._end_of_day(event.date)
        return []

    def _end_of_day(self, date: str) -> list[Event]:
        ts = pd.Timestamp(date, tz="UTC")
        opens = pd.Series(self.opens.pop(date, {}), dtype=float)
        previous = pd.Series(self.last_close, dtype=float)
        self.last_close.update(self.closes.pop(date, {}))
        valuation = pd.Series(self.last_close, dtype=float)

        out = []
        for bot, ledger in self.ledgers.items():
            already = len(ledger.fills)
            if (targets := self.pending.pop(bot, None)) is not None:
                ledger.rebalance(targets, opens, ts, last_known=previous)
            out += [ev.fill(bot, already + i, f) for i, f in enumerate(ledger.fills[already:])]
            out.append(ev.portfolio(bot, date, ledger.snapshot(valuation)))
        return out


class BotService:
    """One bot: keeps the price history, and decides after seeing its end-of-day portfolio."""

    def __init__(self, strategy: Strategy, limits: RiskLimits, kill_switch: KillSwitch | None = None):
        self.strategy = strategy
        self.name = strategy.name
        self.risk = RiskManager(strategy.name, limits, kill_switch)
        self.recorded: Mapping[str, Event] = {}
        self.history: dict[str, dict[str, float]] = {}  # day -> symbol -> close
        self.in_run = False

    def handle(self, event: Event) -> list[Event]:
        if event.type == ev.RUN:
            self.in_run = self.name in event.data["bots"]
        elif event.type == ev.BAR:
            self.history.setdefault(event.date, {})[event.key] = event.data["close"]
        elif event.type == ev.PORTFOLIO and event.key == self.name and self.in_run:
            return self._decide(event)
        return []

    def _decide(self, event: Event) -> list[Event]:
        portfolio = ev.to_portfolio(event)
        recorded = self.recorded.get(ev.decision(self.name, event.date, None, "").id)

        if recorded is not None and not self.strategy.deterministic:
            # Restarting: reuse the decision from the log instead of asking again.
            self.risk.peak = max(self.risk.peak, portfolio.equity)
            self.risk.eliminated = recorded.data["status"] == "eliminated"
            return [recorded]

        proposal = None
        if not self.risk.eliminated:
            proposal = self.strategy.decide(self._closes_until(event.date), portfolio)
        before = len(self.risk.events)
        approved = self.risk.review(proposal, portfolio, event.timestamp)
        status = "eliminated" if self.risk.eliminated else "active"

        out = [
            ev.risk(self.name, before + i, e.kind, e.detail, event.date)
            for i, e in enumerate(self.risk.events[before:])
        ]
        out.append(ev.decision(self.name, event.date, approved, status))
        return out

    def _closes_until(self, date: str) -> pd.DataFrame:
        days = sorted(d for d in self.history if d <= date)
        frame = pd.DataFrame([self.history[d] for d in days], index=pd.to_datetime(days, utc=True))
        return frame.reindex(columns=sorted(frame.columns)).astype(float)
