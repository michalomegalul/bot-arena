"""An LLM as portfolio manager.

Every few trading days the model gets a compact briefing (prices, trends, its own portfolio,
its last notes) and answers with target weights plus its reasoning. Whatever it says still
goes through the same risk manager as every other bot.

The model is swappable: anything with `chat(system, user, schema) -> (text, stats)`. Local
models run through Ollama; Claude can plug into the same interface.
"""

import hashlib
import json
import math
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd
import requests

from bot_arena.broker import Portfolio
from bot_arena.indicators import rsi, sma
from bot_arena.strategies.base import Strategy

INDEX_FUNDS = {"SPY", "QQQ"}
FUND_ORDER = ["SPY", "QQQ"]  # as written in the prompt; changing it changes every cached answer
MAX_SINGLE_STOCK = 0.25

SYSTEM_PROMPT = """You are a portfolio manager in a trading competition.
You manage one portfolio that started with $1,000. Your goal is the best risk-adjusted return,
and the benchmark is simply holding SPY (the S&P 500). Other bots compete against you.

Rules:
- Long only, no margin: weights are fractions of your portfolio, each >= 0, adding up to at most 1.
  Whatever is not invested stays in cash.
- At most 0.25 in any single stock. {funds} (index funds) may go up to 1.0.
- Only these symbols exist: {symbols}.
- Your orders execute at the next trading day's open. Trading is not free (slippage).
- You decide again in {every} trading days, so think in terms of the next week or two.

Answer with JSON only: target weights for every symbol you want to hold (omit symbols you want
to sell entirely), 2-4 sentences of reasoning, and your confidence from 0 to 1."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "targets": {"type": "object", "additionalProperties": {"type": "number"}},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["targets", "reasoning", "confidence"],
}


class LLMClient(Protocol):
    model: str

    def chat(self, system: str, user: str, schema: dict) -> tuple[str, dict]:
        """Return the model's raw text and stats (tokens, seconds)."""


class OllamaClient:
    """A local model served by Ollama, forced into JSON by the response schema.

    temperature 0 = always the same answer; > 0 with a `seed` = varied but reproducible answers.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://192.168.4.19:11434",
        num_ctx: int = 4096,
        temperature: float = 0.0,
        seed: int | None = None,
    ):
        self.model, self.base_url, self.num_ctx = model, base_url.rstrip("/"), num_ctx
        self.temperature, self.seed = temperature, seed

    @property
    def cache_id(self) -> str:
        """What makes two answers interchangeable. Plain model name for the default settings."""
        if self.temperature == 0 and self.seed is None:
            return self.model
        return f"{self.model}|t={self.temperature}|seed={self.seed}"

    def chat(self, system: str, user: str, schema: dict) -> tuple[str, dict]:
        started = time.perf_counter()
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "format": schema,
                "stream": False,
                "think": False,  # reasoning models: answer directly, the JSON has a reasoning field
                "options": {"temperature": self.temperature, "num_ctx": self.num_ctx}
                | ({"seed": self.seed} if self.seed is not None else {}),
            },
            timeout=600,
        )
        response.raise_for_status()
        body = response.json()
        stats = {
            "prompt_tokens": body.get("prompt_eval_count", 0),
            "output_tokens": body.get("eval_count", 0),
            "seconds": round(time.perf_counter() - started, 2),
        }
        return body["message"]["content"], stats


@dataclass
class JournalEntry:
    date: str
    model: str
    targets: dict[str, float] | None  # after cleanup; None = hold (e.g. the model failed)
    reasoning: str
    confidence: float | None
    raw: str
    notes: list[str] = field(default_factory=list)  # what the cleanup had to fix
    stats: dict = field(default_factory=dict)
    cached: bool = False


class LLMManager(Strategy):
    deterministic = False  # restarts reuse logged decisions instead of asking again

    def __init__(
        self,
        client: LLMClient,
        label: str | None = None,
        every: int = 5,
        emoji: str = "🤖",
        cache_dir: Path | None = Path("data/llm_cache"),
        anonymize: bool = False,
    ):
        self.client = client
        self.name = f"AI {label or client.model}"
        self.emoji = emoji
        self.every = every
        self.cache_dir = cache_dir
        self.anonymize = anonymize  # hide names, dates and price levels (memorization test)
        self.aliases: dict[str, str] = {}
        self.journal: list[JournalEntry] = []
        self.days_seen = 0

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        self.days_seen += 1
        if (self.days_seen - 1) % self.every:
            return None
        symbols = [s for s in history.columns if not pd.isna(history[s].iloc[-1])]
        if not self.anonymize:
            funds = " and ".join(s for s in FUND_ORDER if s in symbols)
            system = SYSTEM_PROMPT.format(symbols=", ".join(symbols), funds=funds, every=self.every)
            user = briefing(history[symbols], portfolio, self.journal[-3:])
            entry = self._ask(system, user, history.index[-1], symbols)
        else:
            entry = self._ask_anonymously(history[symbols], portfolio, symbols)
        self.journal.append(entry)
        return entry.targets

    def _ask_anonymously(
        self, history: pd.DataFrame, portfolio: Portfolio, symbols: list[str]
    ) -> JournalEntry:
        """Same question, but the model can't tell which stocks or which years these are."""
        alias = self._alias_map(symbols)
        real = {a: s for s, a in alias.items()}
        # Prices as a level vs one year ago (= 100), so price levels give nothing away.
        base = history.iloc[max(0, len(history) - 253)]
        levels = (history / base * 100).rename(columns=alias)  # dates stay internal; never printed
        hidden = Portfolio(
            portfolio.cash,
            {alias[s]: q for s, q in portfolio.positions.items() if s in alias},
            portfolio.equity,
            {alias[s]: w for s, w in portfolio.weights.items() if s in alias},
        )
        recent = [
            JournalEntry(
                f"trading day {i * self.every + 1}",
                e.model,
                {alias.get(s, s): w for s, w in (e.targets or {}).items()},
                e.reasoning,
                e.confidence,
                "",
            )
            for i, e in list(enumerate(self.journal))[-3:]
        ]
        funds = " and ".join(alias[s] for s in symbols if s in INDEX_FUNDS)
        system = SYSTEM_PROMPT.format(symbols=", ".join(sorted(real)), funds=funds, every=self.every)
        user = briefing(levels[sorted(real)], hidden, recent, day_label=f"trading day {self.days_seen}")
        entry = self._ask(system, user, history.index[-1], sorted(real), funds=set(funds.split(" and ")))
        if entry.targets is not None:
            entry.targets = {real[a]: w for a, w in entry.targets.items()}
        return entry

    def _alias_map(self, symbols: list[str]) -> dict[str, str]:
        """Stable per bot: index funds -> FUND_1.., stocks -> STOCK_A.., in shuffled order."""
        missing = [s for s in symbols if s not in self.aliases]
        if missing:
            rng = random.Random(self.name)
            funds = [s for s in symbols if s in INDEX_FUNDS]
            stocks = [s for s in symbols if s not in INDEX_FUNDS]
            rng.shuffle(funds)
            rng.shuffle(stocks)
            self.aliases = {s: f"FUND_{i + 1}" for i, s in enumerate(funds)}
            self.aliases |= {s: f"STOCK_{chr(65 + i)}" for i, s in enumerate(stocks)}
        return self.aliases

    def _ask(
        self, system: str, user: str, ts: pd.Timestamp, symbols: list[str], funds: set[str] = INDEX_FUNDS
    ) -> JournalEntry:
        date = ts.strftime("%Y-%m-%d")
        raw, stats, cached = "", {}, False
        for attempt in range(2):
            try:
                raw, stats, cached = self._chat_cached(system, user)
                data, format_notes = parse_answer(raw)
                targets, notes = clean_targets(data.get("targets"), symbols, funds)
                notes = format_notes + notes
                confidence = data.get("confidence")
                confidence = float(confidence) if isinstance(confidence, int | float) else None
                return JournalEntry(
                    date,
                    self.client.model,
                    targets,
                    str(data.get("reasoning", "")).strip(),
                    confidence,
                    raw,
                    notes,
                    stats,
                    cached,
                )
            except (requests.RequestException, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                error = f"attempt {attempt + 1}: {type(exc).__name__}: {exc}"
        return JournalEntry(date, self.client.model, None, "", None, raw, [error, "holding"], stats, cached)

    def _chat_cached(self, system: str, user: str) -> tuple[str, dict, bool]:
        """Same model + same prompt -> same answer from disk. Reruns cost nothing."""
        model_id = getattr(self.client, "cache_id", self.client.model)
        key = hashlib.sha256(json.dumps([model_id, system, user]).encode()).hexdigest()[:24]
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path and path.exists():
            hit = json.loads(path.read_text())
            return hit["raw"], hit["stats"], True
        raw, stats = self.client.chat(system, user, RESPONSE_SCHEMA)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.client.model, "raw": raw, "stats": stats}))
        return raw, stats, False

    def journal_dicts(self) -> list[dict]:
        return [asdict(e) for e in self.journal]


TICKER = re.compile(r"[A-Z][A-Z0-9_.]{0,9}")  # NVDA, BRK.B, and anonymized names like STOCK_A / FUND_1
TARGET_SYNONYMS = (
    "targets",
    "weights",
    "target_weights",
    "target_allocation",
    "allocation",
    "allocations",
    "portfolio",
    "portfolio_weights",
)


def parse_answer(raw: str) -> tuple[dict, list[str]]:
    """The model's JSON, even if it ignored the requested format. Every fix is noted."""
    notes, text, after = [], raw.strip(), ""
    if text.startswith("```"):
        notes.append("answer was wrapped in a Markdown code block")
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text, _, after = text.partition("```")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
        notes.append("answer had extra text around the JSON")
    if not isinstance(data, dict):
        raise TypeError(f"answer is not a JSON object: {data!r}")
    if "targets" not in data:
        key = next((k for k in TARGET_SYNONYMS if isinstance(data.get(k), dict)), None)
        tickers = {k: v for k, v in data.items() if isinstance(v, int | float) and TICKER.fullmatch(k)}
        if key is not None:
            notes.append(f"used {key!r} instead of 'targets'")
            data["targets"] = data.pop(key)
        elif tickers:
            notes.append("put the weights at the top level instead of under 'targets'")
            data["targets"] = tickers
        else:
            raise KeyError("answer has no targets")
    if not data.get("reasoning") and after.strip():
        notes.append("wrote the reasoning outside the JSON")
        data["reasoning"] = after.strip()
    return data, notes


def clean_targets(
    targets, symbols: list[str], funds: set[str] = INDEX_FUNDS
) -> tuple[dict[str, float], list[str]]:
    """Turn whatever the model said into valid weights, writing down every fix."""
    if not isinstance(targets, dict):
        raise TypeError(f"targets is not an object: {targets!r}")
    notes, out = [], {}
    for raw_symbol, raw_weight in targets.items():
        symbol = str(raw_symbol).strip().upper()
        if symbol not in symbols:
            notes.append(f"ignored unknown symbol {raw_symbol!r}")
            continue
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            notes.append(f"ignored non-numeric weight for {symbol}: {raw_weight!r}")
            continue
        if math.isnan(weight) or weight <= 0:
            continue
        if weight > 1.5:  # "40" meaning 40%
            notes.append(f"{symbol}: read {weight} as a percentage")
            weight /= 100
        cap = 1.0 if symbol in funds else MAX_SINGLE_STOCK
        if weight > cap:
            notes.append(f"{symbol}: {weight:.0%} is over the {cap:.0%} limit")  # the risk manager clips it
        out[symbol] = weight
    total = sum(out.values())
    if total > 1:
        notes.append(f"weights added up to {total:.0%}, scaled down to 100%")
        out = {s: w / total for s, w in out.items()}
    return out, notes


def briefing(
    history: pd.DataFrame, portfolio: Portfolio, recent: list[JournalEntry], day_label: str | None = None
) -> str:
    """Everything the model gets to see, as a compact table. Only data up to today.

    With `day_label`, the real date is never shown (anonymized runs).
    """
    today = history.index[-1]
    when = day_label or f"{today:%A, %Y-%m-%d}"
    lines = [f"Today is {when} (after the close).", "", "Market (daily closes):"]
    lines.append("symbol  close    5d     20d    60d   vs 50d-avg  RSI14  vol20  from 52w high")
    for symbol in history.columns:
        p = history[symbol].dropna()
        if len(p) < 2:
            continue
        last = p.iloc[-1]

        def change(days, p=p, last=last):
            return f"{last / p.iloc[-days - 1] - 1:+.1%}" if len(p) > days else "n/a"

        avg50 = sma(p, 50).iloc[-1]
        trend = f"{last / avg50 - 1:+.1%}" if not pd.isna(avg50) else "n/a"
        strength = rsi(p, 14).iloc[-1]
        vol = p.pct_change().iloc[-20:].std() * math.sqrt(252)
        off_high = last / p.iloc[-252:].max() - 1
        lines.append(
            f"{symbol:<6} {last:>8.2f} {change(5):>6} {change(20):>6} {change(60):>6} {trend:>10} "
            f"{strength:>6.0f} {vol:>5.0%} {off_high:>13.1%}"
        )

    lines += [
        "",
        f"Your portfolio: ${portfolio.equity:,.2f} total, cash {portfolio.cash / portfolio.equity:.0%}",
    ]
    for symbol, weight in sorted(portfolio.weights.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {symbol}: {weight:.1%}")
    if recent:
        lines += ["", "Your recent decisions:"]
        for e in recent:
            held = ", ".join(f"{s} {w:.0%}" for s, w in (e.targets or {}).items()) or "cash/hold"
            lines.append(f"  {e.date}: {held}. {e.reasoning[:300]}")
    return "\n".join(lines)
