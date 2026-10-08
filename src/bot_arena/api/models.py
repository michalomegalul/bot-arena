"""The API contract: every response the UI can get. The frontend's types mirror these.

Conventions:
- Dates are "YYYY-MM-DD" strings (trading days). Money is in dollars.
- Fractions stay fractions (0.25 = 25%); the UI formats them.
- `None` means "not known yet" (e.g. a live run before its first close).
"""

from typing import Literal

from pydantic import BaseModel


class Run(BaseModel):
    id: int
    kind: Literal["backtest", "paper", "live"]
    topic: str | None  # event log topic, for paper/live runs
    start_date: str | None
    end_date: str | None  # last trading day with data
    started_at: str  # when the run was created (ISO timestamp)
    bots: int


class BotSummary(BaseModel):
    id: int
    name: str
    emoji: str
    status: Literal["active", "eliminated"]
    is_benchmark: bool  # the SPY Hodler: the line everyone has to beat
    rank: int  # 1 = most money
    starting_cash: float
    equity: float | None  # latest end-of-day value
    total_return: float | None
    max_drawdown: float | None  # negative fraction
    sharpe: float | None
    sortino: float | None
    exposure: float | None  # fraction invested at the latest close
    trades: int
    sparkline: list[float]  # last 30 equity values, oldest first


class Leaderboard(BaseModel):
    run: Run
    as_of: str | None  # latest trading day with equity data
    bots: list[BotSummary]  # sorted by rank


class EquityPoint(BaseModel):
    t: str
    v: float


class EquitySeries(BaseModel):
    bot_id: int
    name: str
    emoji: str
    is_benchmark: bool
    points: list[EquityPoint]


class Trade(BaseModel):
    id: int
    bot_id: int
    bot: str
    emoji: str
    t: str
    symbol: str
    side: Literal["buy", "sell"]
    shares: float
    price: float
    value: float  # shares * price
    fee: float


class RiskEvent(BaseModel):
    id: int
    bot_id: int
    bot: str
    emoji: str
    t: str
    kind: str  # clipped | dropped | rejected | eliminated | kill_switch
    detail: str


class Position(BaseModel):
    symbol: str
    shares: float
    price: float | None  # latest close
    value: float | None
    weight: float | None  # fraction of the bot's equity


class BotDetail(BaseModel):
    summary: BotSummary
    positions: list[Position]  # paper runs only; backtests don't store holdings
    trades: list[Trade]  # newest first
    risk_events: list[RiskEvent]  # newest first


class PricePoint(BaseModel):
    t: str
    open: float
    close: float


class FeedMessage(BaseModel):
    """Pushed over the WebSocket /api/runs/{id}/feed when new rows are recorded."""

    type: Literal["trade", "risk", "equity"]
    trade: Trade | None = None
    risk: RiskEvent | None = None
    equity: EquitySeries | None = None  # only the new points
