"""Everything that happens in the arena is an Event, appended to one ordered log.

Order of events for one trading day `t`:
    bar (one per symbol) -> close -> portfolio (one per bot, from the broker)
    -> risk events + decision (from each bot)
The broker fills day t's decisions at the OPEN of day t+1, when that day's `close` arrives,
which is the same timing as the backtest engine.

Every event has a deterministic `id`, so a restarted service can tell which of its outputs
are already in the log.
"""

import json
from dataclasses import asdict, dataclass, field

import pandas as pd

from bot_arena.broker import Fill, Portfolio

RUN = "run"  # first event: the run's configuration
BAR = "bar"  # one daily bar for one symbol
CLOSE = "close"  # all of the day's bars are in; the day is over
PORTFOLIO = "portfolio"  # a bot's holdings, valued at the close
DECISION = "decision"  # a bot's approved targets for the next open (None = change nothing)
FILL = "fill"  # a trade the broker executed
RISK = "risk"  # something the risk manager did


@dataclass(frozen=True)
class Event:
    type: str
    date: str  # trading day, YYYY-MM-DD
    key: str = ""  # symbol for market events, bot name for bot events
    data: dict = field(default_factory=dict)
    seq: int = 0  # tells apart several events of the same type, key and day (e.g. fills)

    @property
    def id(self) -> str:
        return f"{self.type}:{self.key}:{self.date}:{self.seq}"

    @property
    def timestamp(self) -> pd.Timestamp:
        return pd.Timestamp(self.date, tz="UTC")

    def to_json(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":")).encode()

    @classmethod
    def from_json(cls, raw: bytes | str) -> "Event":
        return cls(**json.loads(raw))


def day(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d")


# --- constructors, so every service builds events the same way ---


def run(date: str, bots: list[str], cash: float, slippage_bps: float, fee: float, **extra) -> Event:
    data = {"bots": bots, "cash": cash, "slippage_bps": slippage_bps, "fee": fee, **extra}
    return Event(RUN, date, data=data)


def bar(symbol: str, date: str, open_: float, close: float, *, warmup: bool = False, **extra) -> Event:
    """`warmup` bars only fill the bots' price history; no trading happens on warmup days."""
    data = {"open": float(open_), "close": float(close), **extra}
    if warmup:
        data["warmup"] = True
    return Event(BAR, date, symbol, data)


def close(date: str, symbols: list[str]) -> Event:
    return Event(CLOSE, date, data={"symbols": sorted(symbols)})


def portfolio(bot: str, date: str, p: Portfolio) -> Event:
    data = {"cash": p.cash, "positions": p.positions, "equity": p.equity, "weights": p.weights}
    return Event(PORTFOLIO, date, bot, {k: _plain(v) for k, v in data.items()})


def to_portfolio(event: Event) -> Portfolio:
    d = event.data
    return Portfolio(d["cash"], dict(d["positions"]), d["equity"], dict(d["weights"]))


def decision(bot: str, date: str, targets: dict[str, float] | None, status: str) -> Event:
    return Event(DECISION, date, bot, {"targets": _plain(targets), "status": status})


def fill(bot: str, seq: int, f: Fill) -> Event:
    data = {"symbol": f.symbol, "side": f.side, "shares": f.shares, "price": f.price, "fee": f.fee}
    return Event(FILL, day(f.date), bot, {k: _plain(v) for k, v in data.items()}, seq)


def risk(bot: str, seq: int, kind: str, detail: str, date: str) -> Event:
    return Event(RISK, date, bot, {"kind": kind, "detail": detail}, seq)


def _plain(value):
    """numpy floats -> float, so events serialize and compare exactly."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if hasattr(value, "item"):
        return value.item()
    return value
