"""Risk manager: every bot's orders pass through here before reaching the broker."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RiskEvent:
    date: pd.Timestamp
    bot: str
    kind: str  # "clipped" | "dropped" | "eliminated" | "kill_switch"
    detail: str
