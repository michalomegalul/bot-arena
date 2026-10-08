"""Experiments on the AI bots: how much is luck, and how much is memory?

- repeats: each model several times with sampling on (temperature > 0, different seeds).
  The spread of results is the luck in a single run.
- memorization: each model with real names and dates vs anonymized (STOCK_A, "trading day 12",
  prices rescaled), in a window the models were trained on (2023-24) and one after their
  training (2026). A model that only does well with real names in 2023-24 is remembering
  history, not reading the data.

Results are saved after every run (data/experiments/*.json), and every model answer is cached,
so an interrupted experiment resumes where it stopped.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import pandas as pd

from bot_arena import data, metrics
from bot_arena.config import STARTING_CASH, WATCHLIST
from bot_arena.engine import run_backtest
from bot_arena.risk import RiskLimits
from bot_arena.strategies import SpyHodler
from bot_arena.strategies.llm import LLMManager, OllamaClient

OUT_DIR = Path("data/experiments")
MODELS = {
    "gemma3:12b": "Gemma 3 12B",
    "gemma4:e4b": "Gemma 4 e4b",
    "qwen2.5-coder:14b": "Qwen 2.5 Coder 14B",
    "qwen3:8b": "Qwen 3 8B",
}
# (name, first trading day, last day, decide every N days)
WINDOWS = [
    ("2023-24 (in training data)", "2023-01-03", "2024-12-31", 10),
    ("2026 (after training)", "2026-01-02", None, 5),
]


def _prices(end: str | None):
    bars = data.load_bars()
    opens, closes = data.prices(bars, "open"), data.prices(bars, "close")
    if end:
        opens, closes = opens.loc[:end], closes.loc[:end]
    return opens, closes


def _run(bot, start: str, end: str | None) -> dict:
    opens, closes = _prices(end)
    limits = RiskLimits(allowed_symbols=frozenset(WATCHLIST))
    started = time.perf_counter()
    result = run_backtest(
        bot, opens, closes, STARTING_CASH, 5.0, 0.0, limits, trade_from=pd.Timestamp(start, tz="UTC")
    )
    eq = result.equity
    row = {
        "return": metrics.total_return(eq),
        "sharpe": metrics.sharpe(eq),
        "max_drawdown": metrics.max_drawdown(eq),
        "trades": len(result.fills),
        "seconds": round(time.perf_counter() - started, 1),
    }
    if isinstance(bot, LLMManager):
        row["decisions"] = len(bot.journal)
        row["failed"] = sum(e.targets is None for e in bot.journal)
        row["new_calls"] = sum(not e.cached for e in bot.journal)
        row["format_fixes"] = sum(
            any(k in n for k in ("Markdown", "instead", "top level", "extra text"))
            for e in bot.journal
            for n in e.notes
        )
    return row


def _benchmarks(start: str, end: str | None) -> dict:
    qqq = SpyHodler("QQQ")
    qqq.name = "QQQ Hodler"
    return {"SPY": _run(SpyHodler(), start, end), "QQQ": _run(qqq, start, end)}


def _save(name: str, results: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps(results, indent=1))


def _load(name: str) -> dict:
    path = OUT_DIR / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def memorization(models: dict[str, str], ollama: str) -> dict:
    results = _load("memorization")
    for window, start, end, every in WINDOWS:
        results.setdefault("benchmarks", {})[window] = _benchmarks(start, end)
    for model, label in models.items():
        for window, start, end, every in WINDOWS:
            for mode in ("named", "anonymous"):
                bot = LLMManager(OllamaClient(model, ollama), label, every, anonymize=mode == "anonymous")
                row = _run(bot, start, end)
                results.setdefault("runs", {}).setdefault(label, {}).setdefault(window, {})[mode] = row
                _save("memorization", results)
                print(
                    f"{label:<20} {window:<28} {mode:<9} {row['return']:+.1%}  "
                    f"({row['new_calls']} new calls, {row['seconds']:.0f}s)",
                    flush=True,
                )
    return results


def repeats(models: dict[str, str], ollama: str, seeds: int, temperature: float) -> dict:
    window, start, end, every = WINDOWS[1]
    results = _load("repeats")
    results["benchmarks"] = _benchmarks(start, end)
    results["settings"] = {"window": window, "temperature": temperature, "seeds": seeds, "every": every}
    for model, label in models.items():
        runs = results.setdefault("runs", {}).setdefault(label, {})
        runs["temperature 0"] = _run(LLMManager(OllamaClient(model, ollama), label, every), start, end)
        for seed in range(1, seeds + 1):
            client = OllamaClient(model, ollama, temperature=temperature, seed=seed)
            runs[f"seed {seed}"] = _run(LLMManager(client, label, every), start, end)
            _save("repeats", results)
            print(
                f"{label:<20} seed {seed}: {runs[f'seed {seed}']['return']:+.1%}  "
                f"({runs[f'seed {seed}']['new_calls']} new calls)",
                flush=True,
            )
    return results


def report() -> str:
    """Markdown tables from whatever results exist so far."""
    lines = ["# AI experiments", ""]
    mem = _load("memorization")
    if mem:
        lines += ["## Memorization test: real names vs anonymized", ""]
        for window, *_ in WINDOWS:
            b = mem.get("benchmarks", {}).get(window)
            if not b:
                continue
            lines += [
                f"### {window}",
                "",
                f"Benchmarks: SPY {b['SPY']['return']:+.1%}, QQQ {b['QQQ']['return']:+.1%}",
                "",
                "| Model | Real names | Anonymized | Gap | Format fixes (named / anon) |",
                "|---|---|---|---|---|",
            ]
            for label, windows in mem.get("runs", {}).items():
                r = windows.get(window, {})
                if "named" in r and "anonymous" in r:
                    gap = r["named"]["return"] - r["anonymous"]["return"]
                    lines.append(
                        f"| {label} | {r['named']['return']:+.1%} | {r['anonymous']['return']:+.1%} | "
                        f"{gap:+.1%} | {r['named'].get('format_fixes', 0)} / {r['anonymous'].get('format_fixes', 0)} |"
                    )
            lines.append("")
    rep = _load("repeats")
    if rep:
        s = rep["settings"]
        b = rep["benchmarks"]
        lines += [
            f"## Repeat runs: {s['seeds']} seeds at temperature {s['temperature']}, {s['window']}",
            "",
            (
                f"Benchmarks: SPY {b['SPY']['return']:+.1%} (Sharpe {b['SPY']['sharpe']:.2f}), "
                f"QQQ {b['QQQ']['return']:+.1%} (Sharpe {b['QQQ']['sharpe']:.2f})"
            ),
            "",
            "| Model | Temp 0 | Sampled: worst | median | best | spread | Sharpe range | beat SPY | beat QQQ |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for label, runs in rep.get("runs", {}).items():
            sampled = [r for k, r in runs.items() if k.startswith("seed")]
            if not sampled:
                continue
            rets = sorted(r["return"] for r in sampled)
            sharpes = sorted(r["sharpe"] for r in sampled)
            beat_spy = sum(r["return"] > b["SPY"]["return"] for r in sampled)
            beat_qqq = sum(r["return"] > b["QQQ"]["return"] for r in sampled)
            zero = runs.get("temperature 0", {}).get("return")
            lines.append(
                f"| {label} | {zero:+.1%} | {rets[0]:+.1%} | {statistics.median(rets):+.1%} | {rets[-1]:+.1%} | "
                f"{rets[-1] - rets[0]:.1%} | {sharpes[0]:.2f}–{sharpes[-1]:.2f} | "
                f"{beat_spy}/{len(sampled)} | {beat_qqq}/{len(sampled)} |"
            )
        lines.append("")
    return "\n".join(lines)


def register(subparsers) -> None:
    p = subparsers.add_parser("experiment", help="AI experiments: repeat runs and the memorization test")
    p.add_argument("kind", choices=["memorization", "repeats", "report", "all"])
    p.add_argument("--models", default=",".join(MODELS), help="Ollama models (default: all four)")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--ollama", default="http://192.168.4.19:11434")
    p.add_argument("--out", default="docs/ai_experiments.md")
    p.set_defaults(func=_cli)


def _cli(args: argparse.Namespace) -> None:
    models = {m: MODELS.get(m, m) for m in args.models.split(",") if m}
    if args.kind in ("memorization", "all"):
        memorization(models, args.ollama)
    if args.kind in ("repeats", "all"):
        repeats(models, args.ollama, args.seeds, args.temperature)
    text = report()
    Path(args.out).write_text(text + "\n")
    print("\n" + text)
