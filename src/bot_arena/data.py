"""Download daily price bars from Alpaca and cache them locally."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from bot_arena.config import Settings

DATA_DIR = Path("data")
BARS_FILE = DATA_DIR / "bars_daily.parquet"


def fetch_daily_bars(settings: Settings, symbols: list[str], start: datetime) -> pd.DataFrame:
    """Daily OHLCV bars, indexed by (symbol, timestamp).

    Uses the full-market SIP feed. The free plan only allows SIP data older than
    15 minutes, so the request ends 20 minutes ago. Prices are adjusted for splits
    and dividends, so buy-and-hold returns are total returns.
    """
    client = StockHistoricalDataClient(settings.api_key, settings.secret_key)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=datetime.now(UTC) - timedelta(minutes=20),
        adjustment=Adjustment.ALL,
        feed=DataFeed.SIP,
    )
    return client.get_stock_bars(request).df


def save_bars(bars: pd.DataFrame, path: Path = BARS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(path)


def load_bars(path: Path = BARS_FILE) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"No cached data at {path}. Run `arena fetch` first.")
    return pd.read_parquet(path)


def closes(bars: pd.DataFrame) -> pd.DataFrame:
    """Close prices as a wide table: one row per day, one column per symbol."""
    wide = bars["close"].unstack(level="symbol")
    wide.index = pd.to_datetime(wide.index).normalize()
    return wide.sort_index()
