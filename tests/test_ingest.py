from datetime import UTC, date, datetime

import pandas as pd
import pytest

from bot_arena.config import Settings
from bot_arena.pipeline import events, ingest
from bot_arena.pipeline.log import MemoryLog

SETTINGS = Settings(api_key="test", secret_key="test", paper=True)
SYMBOLS = ["SPY", "AAPL"]


def alpaca_bars(days: dict[str, dict[str, float]]) -> pd.DataFrame:
    """{"2026-10-05": {"SPY": 500.0, ...}} -> a DataFrame shaped like Alpaca's (midnight New York)."""
    rows = []
    for d, closes in days.items():
        ts = pd.Timestamp(d, tz=ingest.NEW_YORK).tz_convert("UTC")
        for symbol, close in closes.items():
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": ts,
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "volume": 1000.0,
                }
            )
    return pd.DataFrame(rows).set_index(["symbol", "timestamp"]).sort_index()


def ny(d: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{d}T{hhmm}").replace(tzinfo=ingest.NEW_YORK).astimezone(UTC)


# Mon 5 .. Fri 9 Oct 2026, with Friday a half day (closes 13:00).
CALENDAR = [(d, ny(d, "16:00")) for d in ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]]
CALENDAR.append(("2026-10-09", ny("2026-10-09", "13:00")))
PRICES = {d: {"SPY": 500.0 + i, "AAPL": 200.0 + i} for i, (d, _) in enumerate(CALENDAR)}


@pytest.fixture
def fake_alpaca(monkeypatch):
    calls = {"calendar": [], "bars": []}

    def trading_days(settings, start, end):
        calls["calendar"].append((start, end))
        return [(d, c) for d, c in CALENDAR if start <= date.fromisoformat(d) <= end]

    def fetch_bars(settings, symbols, start, end):
        calls["bars"].append((start, end))
        # Only bars for sessions that had started before `end` exist.
        known = {d: p for d, p in PRICES.items() if ny(d, "09:30") < end}
        return alpaca_bars(known)

    monkeypatch.setattr(ingest, "trading_days", trading_days)
    monkeypatch.setattr(ingest, "fetch_bars", fetch_bars)
    return calls


def seeded_log() -> MemoryLog:
    return MemoryLog([events.run("2026-10-06", ["Bot"], 1000, 5, 0)])


def closes(log: MemoryLog) -> list[str]:
    return [e.date for e in log.events if e.type == events.CLOSE]


# --- seed_run ---


def test_seed_run_writes_run_then_warmup_bars_once(monkeypatch):
    history = {f"2026-09-{d:02d}": {"SPY": 400.0 + d, "AAPL": 150.0 + d} for d in (28, 29, 30)}
    history["2026-10-01"] = {"SPY": 431.0, "AAPL": 181.0}  # "today": must not become warmup
    monkeypatch.setattr(ingest.data, "fetch_daily_bars", lambda s, syms, start: alpaca_bars(history))

    log = MemoryLog()
    assert ingest.seed_run(log, ["Bot"], 1000, 5, 0, 2, SETTINGS, SYMBOLS, date(2026, 10, 1))
    first, *rest = log.events
    assert first.type == events.RUN and first.date == "2026-10-01" and first.data["bots"] == ["Bot"]
    assert [(e.date, e.key) for e in rest] == [
        ("2026-09-29", "AAPL"),
        ("2026-09-29", "SPY"),
        ("2026-09-30", "AAPL"),
        ("2026-09-30", "SPY"),
    ]
    assert all(e.type == events.BAR and e.data["warmup"] for e in rest)
    assert not any(e.type == events.CLOSE for e in log.events)  # no trading on warmup days
    aapl = {"open": 178.0, "close": 179.0, "high": 180.0, "low": 177.0, "volume": 1000.0, "warmup": True}
    assert rest[0].data == aapl

    assert not ingest.seed_run(log, ["Other"], 5, 0, 0, 2, SETTINGS, SYMBOLS, date(2026, 10, 2))
    assert len(log.events) == 5


def test_seed_run_without_warmup():
    log = MemoryLog()
    ingest.seed_run(log, ["Bot"], 1000, 5, 0, 0, SETTINGS, SYMBOLS, date(2026, 10, 1))
    assert [e.type for e in log.events] == [events.RUN]


# --- ingest_day ---


def test_ingest_day_appends_sorted_bars_then_close():
    log = seeded_log()
    day = {"SPY": {"open": 1.0, "close": 2.0}, "AAPL": {"open": 3.0, "close": 4.0}}
    assert ingest.ingest_day(log, "2026-10-06", day)
    assert [(e.type, e.key) for e in log.events[1:]] == [("bar", "AAPL"), ("bar", "SPY"), ("close", "")]
    assert log.events[-1].data == {"symbols": ["AAPL", "SPY"]}
    assert "warmup" not in log.events[1].data


def test_ingest_day_is_idempotent_and_finishes_a_half_written_day():
    log = seeded_log()
    day = {"SPY": {"open": 1.0, "close": 2.0}, "AAPL": {"open": 3.0, "close": 4.0}}
    log.append(events.bar("AAPL", "2026-10-06", 3.0, 4.0))  # crashed after the first bar
    assert ingest.ingest_day(log, "2026-10-06", day)
    assert [(e.type, e.key) for e in log.events[1:]] == [("bar", "AAPL"), ("bar", "SPY"), ("close", "")]
    assert not ingest.ingest_day(log, "2026-10-06", day)
    assert len(log.events) == 4


# --- catch_up_days ---


def test_catch_up_needs_a_seeded_run(fake_alpaca):
    with pytest.raises(RuntimeError):
        ingest.catch_up_days(MemoryLog(), SETTINGS, SYMBOLS, ny("2026-10-06", "17:00"))


def test_run_start_day_is_the_first_live_day(fake_alpaca):
    log = seeded_log()  # run starts Tue 6 Oct
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-06", "16:30")) == ["2026-10-06"]
    assert fake_alpaca["calendar"][0][0] == date(2026, 10, 6)


def test_waits_twenty_minutes_after_the_close(fake_alpaca):
    log = seeded_log()
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-06", "16:19")) == []
    assert closes(log) == []
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-06", "16:20")) == ["2026-10-06"]


def test_catches_up_several_missed_days_in_order(fake_alpaca):
    log = seeded_log()
    done = ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-08", "20:00"))
    assert done == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert closes(log) == done
    spy = [e.data["close"] for e in log.events if e.type == events.BAR and e.key == "SPY"]
    assert spy == [501.0, 502.0, 503.0]
    # Nothing new: no duplicate days.
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-08", "21:00")) == []
    assert closes(log) == done


def test_resumes_after_the_last_close(fake_alpaca):
    log = seeded_log()
    ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-06", "17:00"))
    fake_alpaca["calendar"].clear()
    ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-07", "17:00"))
    assert fake_alpaca["calendar"] == [(date(2026, 10, 7), date(2026, 10, 7))]
    assert closes(log) == ["2026-10-06", "2026-10-07"]


def test_half_day_is_due_twenty_minutes_after_its_early_close(fake_alpaca):
    log = seeded_log()
    ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-08", "17:00"))
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-09", "13:19")) == []
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-09", "13:20")) == ["2026-10-09"]


def test_stops_at_a_day_without_bars_so_order_is_kept(fake_alpaca, monkeypatch):
    log = seeded_log()
    missing_tuesday = {d: p for d, p in PRICES.items() if d != "2026-10-06"}
    monkeypatch.setattr(ingest, "fetch_bars", lambda s, syms, start, end: alpaca_bars(missing_tuesday))
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-08", "20:00")) == []
    assert closes(log) == []  # Wednesday is not ingested before Tuesday


def test_weekend_start_waits_for_monday(fake_alpaca):
    log = MemoryLog([events.run("2026-10-03", ["Bot"], 1000, 5, 0)])  # Saturday
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-04", "12:00")) == []
    assert ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-05", "16:30")) == ["2026-10-05"]


def test_bar_events_carry_ohlcv(fake_alpaca):
    log = seeded_log()
    ingest.catch_up_days(log, SETTINGS, SYMBOLS, ny("2026-10-06", "17:00"))
    spy = next(e for e in log.events if e.type == events.BAR and e.key == "SPY")
    assert spy.data == {"open": 500.0, "close": 501.0, "high": 502.0, "low": 499.0, "volume": 1000.0}
