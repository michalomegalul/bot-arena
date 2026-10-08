"""The live market feed: appends each finished trading day to the event log.

A paper run starts with `seed_run`: one `run` event, then warmup bars (price history for
indicators like the 50-day average; no trading happens on warmup days). After that,
`run_ingest` checks every few minutes for sessions that closed at least 20 minutes ago and
appends their bars plus a `close` event, one day at a time, in order.

Days already in the log are never rewritten. Alpaca's prices are adjusted for splits and
dividends after the fact, so fetching an old day again later can return slightly different
numbers. The log keeps what was known at the time, which is why a live paper run can differ
a little from a fresh backtest over the same dates.
"""

import logging
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest

from bot_arena import data
from bot_arena.config import Settings
from bot_arena.pipeline import events
from bot_arena.pipeline.events import Event
from bot_arena.pipeline.log import EventLog

log_ = logging.getLogger(__name__)

NEW_YORK = ZoneInfo("America/New_York")
# Wait this long after the closing bell, so the day's bar is final (and SIP data is allowed).
SETTLE = timedelta(minutes=20)
# The free data plan only serves full-market (SIP) data older than 15 minutes.
SIP_DELAY = timedelta(minutes=16)

DayBars = dict[str, dict[str, float]]  # symbol -> {"open", "high", "low", "close", "volume"}


# --- Alpaca access (module-level so tests can replace them) ---


def trading_days(settings: Settings, start: date, end: date) -> list[tuple[str, datetime]]:
    """(YYYY-MM-DD, closing time in UTC) for every trading session from start to end, inclusive."""
    client = TradingClient(settings.api_key, settings.secret_key, paper=settings.paper)
    calendar = client.get_calendar(GetCalendarRequest(start=start, end=end))
    # The API gives naive New York times; half days close early (e.g. 13:00).
    return [(c.date.isoformat(), c.close.replace(tzinfo=NEW_YORK).astimezone(UTC)) for c in calendar]


def fetch_bars(settings: Settings, symbols: list[str], start: datetime, end: datetime) -> pd.DataFrame:
    """Adjusted daily SIP bars between start and end, indexed by (symbol, timestamp)."""
    client = StockHistoricalDataClient(settings.api_key, settings.secret_key)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        adjustment=Adjustment.ALL,
        feed=DataFeed.SIP,
    )
    return client.get_stock_bars(request).df


# --- building the log ---


def seed_run(
    log: EventLog,
    bots: list[str],
    cash: float,
    slippage_bps: float,
    fee: float,
    warmup_days: int,
    settings: Settings,
    symbols: list[str],
    today: date,
    **extra,
) -> bool:
    """Start a paper run: a `run` event dated `today` plus `warmup_days` days of warmup bars.

    `today` is the New York date the run starts; its own session is the first live day.
    Does nothing (returns False) if the log already has a run.
    """
    if any(e.type == events.RUN for _, e in log.read()):
        return False
    log.append(events.run(today.isoformat(), bots, cash, slippage_bps, fee, symbols=sorted(symbols), **extra))

    if warmup_days > 0:
        # ~1.5 calendar days per trading day, plus slack for holidays.
        start = datetime.combine(
            today - timedelta(days=int(warmup_days * 1.5) + 10), datetime.min.time(), UTC
        )
        days = _by_day(data.fetch_daily_bars(settings, symbols, start))
        warmup = [d for d in sorted(days) if d < today.isoformat()][-warmup_days:]
        for d in warmup:
            for symbol in sorted(days[d]):
                log.append(_bar_event(symbol, d, days[d][symbol], warmup=True))
        span = f" ({warmup[0]} to {warmup[-1]})" if warmup else ""
        log_.info("seeded run %s with %d warmup days%s", today, len(warmup), span)
    return True


def ingest_day(log: EventLog, day: str, bars_for_day: DayBars) -> bool:
    """Append a finished day: its bars (sorted by symbol), then `close`.

    Idempotent: bars and the close already in the log are skipped, so a crash halfway
    through a day is safe to retry. Returns False if the day was already complete.
    """
    seen = {e.id for _, e in log.read()}
    close = events.close(day, list(bars_for_day))
    if close.id in seen:
        return False
    for symbol in sorted(bars_for_day):
        bar = _bar_event(symbol, day, bars_for_day[symbol])
        if bar.id not in seen:
            log.append(bar)
    log.append(close)
    return True


def catch_up_days(log: EventLog, settings: Settings, symbols: list[str], now: datetime) -> list[str]:
    """Ingest every session that closed at least SETTLE ago and isn't in the log yet, in order.

    Returns the days ingested. Stops at the first day whose bars aren't available yet, so a
    later poll fills it in before anything after it.
    """
    run, last_close = None, None
    for _, e in log.read():
        if e.type == events.RUN and run is None:
            run = e
        elif e.type == events.CLOSE:
            last_close = e.date
    if run is None:
        raise RuntimeError("the log has no run yet; seed it first (seed_run)")

    first = date.fromisoformat(last_close) + timedelta(days=1) if last_close else date.fromisoformat(run.date)
    today_ny = now.astimezone(NEW_YORK).date()
    if first > today_ny:
        return []
    due = [d for d, closed_at in trading_days(settings, first, today_ny) if closed_at + SETTLE <= now]
    if not due:
        return []

    start = datetime.combine(date.fromisoformat(due[0]), datetime.min.time(), NEW_YORK)
    days = _by_day(fetch_bars(settings, symbols, start, now - SIP_DELAY))
    ingested = []
    for d in due:
        if not days.get(d):
            log_.warning("no bars for %s yet; will retry", d)
            break
        if ingest_day(log, d, days[d]):
            ingested.append(d)
            log_.info("ingested %s (%d symbols)", d, len(days[d]))
    return ingested


def run_ingest(
    log: EventLog, settings: Settings, symbols: list[str], poll_seconds: float = 300, clock=None
) -> None:
    """Poll forever: append each newly finished trading day to the log."""
    clock = clock or (lambda: datetime.now(UTC))
    log_.info("ingest running for %s, checking every %ss", ", ".join(sorted(symbols)), poll_seconds)
    while True:
        try:
            catch_up_days(log, settings, symbols, clock())
        except Exception:  # keep the feed alive through network hiccups
            log_.exception("ingest failed; retrying in %ss", poll_seconds)
        time.sleep(poll_seconds)


# --- helpers ---


def _by_day(bars: pd.DataFrame) -> dict[str, DayBars]:
    """Alpaca bars -> {YYYY-MM-DD (New York date): {symbol: ohlcv}}."""
    days: dict[str, DayBars] = {}
    if bars is None or bars.empty:
        return days
    for (symbol, ts), row in bars.iterrows():
        d = pd.Timestamp(ts).tz_convert(NEW_YORK).strftime("%Y-%m-%d")
        days.setdefault(d, {})[str(symbol)] = {
            k: float(row[k]) for k in ("open", "high", "low", "close", "volume") if k in row
        }
    return days


def _bar_event(symbol: str, day: str, ohlcv: dict[str, float], warmup: bool = False) -> Event:
    extra = {k: ohlcv[k] for k in ("high", "low", "volume") if k in ohlcv}
    return events.bar(symbol, day, ohlcv["open"], ohlcv["close"], warmup=warmup, **extra)
