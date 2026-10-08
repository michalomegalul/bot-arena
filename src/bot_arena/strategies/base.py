"""What every bot has to implement."""

from abc import ABC, abstractmethod

import pandas as pd

from bot_arena.broker import Portfolio


class Strategy(ABC):
    name: str
    emoji: str
    # Same history + portfolio -> same decision. False for bots that ask an LLM: after a restart
    # their past decisions are read back from the log instead of being recomputed.
    deterministic: bool = True

    @abstractmethod
    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        """Called after each day's close.

        `history` holds close prices up to and including today (one column per symbol);
        nothing from the future is in it. Return target weights (symbol -> fraction of
        equity, adding up to at most 1; unlisted holdings get sold), or None to change nothing.
        """

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"
