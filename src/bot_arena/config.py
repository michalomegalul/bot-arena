"""Settings loaded from the environment (and a local .env file)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Stocks the arena watches. SPY is the benchmark every bot has to beat.
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA"]
BENCHMARK = "SPY"
STARTING_CASH = 1000.0


@dataclass(frozen=True)
class Settings:
    api_key: str
    secret_key: str
    paper: bool


def load_settings() -> Settings:
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise SystemExit(
            "Missing ALPACA_API_KEY / ALPACA_SECRET_KEY. "
            "Copy .env.example to .env and fill in your paper keys."
        )
    # Paper unless explicitly turned off. Live trading must be a deliberate choice.
    paper = os.getenv("ALPACA_PAPER", "true").lower() != "false"
    return Settings(api_key=api_key, secret_key=secret_key, paper=paper)
