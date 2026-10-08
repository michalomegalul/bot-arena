"""Risk manager: every bot's orders pass through here before reaching the broker.

Bots only *propose* target weights. The risk manager can shrink them, drop them, or
stop a bot entirely. It never makes a position bigger than the bot asked for.
"""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

from bot_arena.broker import Portfolio


@dataclass(frozen=True)
class RiskEvent:
    date: pd.Timestamp
    bot: str
    kind: str  # "clipped" | "dropped" | "rejected" | "eliminated" | "kill_switch"
    detail: str


@dataclass(frozen=True)
class RiskLimits:
    max_weight: float = 0.25  # per single stock
    # Broad index funds are already diversified, so they may take the whole portfolio.
    max_weight_overrides: Mapping[str, float] = field(default_factory=lambda: {"SPY": 1.0, "QQQ": 1.0})
    max_positions: int = 6
    max_drawdown: float | None = 0.30  # fall from peak that eliminates a bot; None = never
    allowed_symbols: frozenset[str] | None = None  # None = anything with a price

    @classmethod
    def unlimited(cls) -> "RiskLimits":
        """Only the hard rules (no shorting, no margin). For tests and experiments."""
        return cls(max_weight=1.0, max_weight_overrides={}, max_positions=10**6, max_drawdown=None)

    def cap(self, symbol: str) -> float:
        return self.max_weight_overrides.get(symbol, self.max_weight)


class KillSwitch(Protocol):
    def check(self) -> str | None:
        """Return the reason if engaged, otherwise None."""


class NoKillSwitch:
    def check(self) -> str | None:
        return None


class LocalKillSwitch:
    """Engaged by the ARENA_KILL_SWITCH env var, or by a file existing (`touch data/KILL`).

    The file can hold a reason. Both work without the database, so the switch still works
    when everything else is broken.
    """

    def __init__(self, path: Path = Path("data/KILL"), env_var: str = "ARENA_KILL_SWITCH"):
        self.path, self.env_var = path, env_var

    def check(self) -> str | None:
        if os.getenv(self.env_var, "").lower() in {"1", "true", "on", "yes"}:
            return f"{self.env_var} is set"
        if self.path.exists():
            return self.path.read_text().strip() or f"{self.path} exists"
        return None


class AnyKillSwitch:
    """Engaged if any of its switches is. Combine the local switch with the database one,
    so stopping still works when the database is down."""

    def __init__(self, *switches: KillSwitch):
        self.switches = switches

    def check(self) -> str | None:
        return next((reason for s in self.switches if (reason := s.check())), None)


class RiskManager:
    """One per bot. Called once per day, whether or not the bot wants to trade."""

    def __init__(self, bot: str, limits: RiskLimits, kill_switch: KillSwitch | None = None):
        self.bot, self.limits = bot, limits
        self.kill_switch = kill_switch or NoKillSwitch()
        self.events: list[RiskEvent] = []
        self.peak = 0.0
        self.eliminated = False
        self.halted = False

    def review(
        self, targets: dict[str, float] | None, portfolio: Portfolio, date: pd.Timestamp
    ) -> dict[str, float] | None:
        """Approve, shrink or block a bot's targets. Returns what may be sent to the broker."""
        reason = self.kill_switch.check()
        if reason and not self.halted:  # log changes only, not every halted day
            self._log(date, "kill_switch", f"all trading halted: {reason}")
        elif self.halted and not reason:
            self._log(date, "kill_switch", "released, trading resumes")
        self.halted = bool(reason)
        if self.halted:
            return None

        self.peak = max(self.peak, portfolio.equity)
        if self.eliminated:
            # Keep trying to sell out (a symbol may have had no price on the first try).
            return {} if portfolio.positions else None
        if self._drawdown_breached(portfolio.equity):
            self.eliminated = True
            drop = 1 - portfolio.equity / self.peak
            self._log(date, "eliminated", f"down {drop:.1%} from peak ${self.peak:,.2f}; selling everything")
            return {}

        if targets is None:
            return None
        if problem := _invalid(targets):
            self._log(date, "rejected", problem)
            return None
        return self._apply_limits(targets, date)

    def _drawdown_breached(self, equity: float) -> bool:
        limit = self.limits.max_drawdown
        return limit is not None and self.peak > 0 and equity <= self.peak * (1 - limit)

    def _apply_limits(self, targets: dict[str, float], date: pd.Timestamp) -> dict[str, float]:
        approved = {}
        for sym, weight in targets.items():
            if self.limits.allowed_symbols is not None and sym not in self.limits.allowed_symbols:
                self._log(date, "dropped", f"{sym} is not on the allowed list")
                continue
            if weight > self.limits.cap(sym):
                self._log(date, "clipped", f"{sym} {weight:.1%} -> {self.limits.cap(sym):.1%}")
                weight = self.limits.cap(sym)
            if weight > 0:
                approved[sym] = weight

        if len(approved) > self.limits.max_positions:
            ranked = sorted(approved, key=lambda s: (-approved[s], s))
            cut = ranked[self.limits.max_positions :]
            self._log(date, "dropped", f"over {self.limits.max_positions} positions: {', '.join(cut)}")
            approved = {s: approved[s] for s in ranked[: self.limits.max_positions]}
        return approved

    def _log(self, date: pd.Timestamp, kind: str, detail: str) -> None:
        self.events.append(RiskEvent(date, self.bot, kind, detail))


def _invalid(targets: dict[str, float]) -> str | None:
    if any(not isinstance(w, int | float) or math.isnan(w) or math.isinf(w) for w in targets.values()):
        return f"weights must be finite numbers: {targets}"
    if any(w < 0 for w in targets.values()):
        return f"shorting is not allowed: {targets}"
    if sum(targets.values()) > 1 + 1e-9:
        return f"weights add up to {sum(targets.values()):.1%}, margin is not allowed"
    return None
