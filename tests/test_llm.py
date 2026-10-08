import json

import numpy as np
import pandas as pd
import pytest

from bot_arena.broker import Portfolio
from bot_arena.engine import run_backtest
from bot_arena.risk import RiskLimits
from bot_arena.strategies.llm import LLMManager, briefing, clean_targets

SYMBOLS = ["AAPL", "NVDA", "QQQ", "SPY", "TSLA"]


def market(n=120):
    rng = np.random.default_rng(2)
    idx = pd.date_range("2026-01-02", periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n))) for s in SYMBOLS}, index=idx
    )


class FakeModel:
    """Answers with scripted replies and records every prompt."""

    model = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def chat(self, system, user, schema):
        self.prompts.append(user)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return (reply if isinstance(reply, str) else json.dumps(reply)), {"seconds": 0.1}


def answer(targets, reasoning="because", confidence=0.6):
    return {"targets": targets, "reasoning": reasoning, "confidence": confidence}


EMPTY = Portfolio(1000, {}, 1000, {})


def test_cleanup_fixes_what_models_get_wrong():
    targets, notes = clean_targets({"spy": 0.5, "Cash": 0.2, "NVDA": 40, "TSLA": -0.1, "AAPL": "x"}, SYMBOLS)
    assert targets == pytest.approx({"SPY": 0.5, "NVDA": 0.4})  # "40" read as 40%
    assert any("Cash" in n for n in notes) and any("percentage" in n for n in notes)
    assert any("non-numeric" in n for n in notes) and any("NVDA" in n and "limit" in n for n in notes)


def test_cleanup_scales_down_over_100_percent():
    targets, notes = clean_targets({"SPY": 0.8, "QQQ": 0.7}, SYMBOLS)
    assert sum(targets.values()) == pytest.approx(1.0) and targets["SPY"] == pytest.approx(0.8 / 1.5)
    assert any("scaled down" in n for n in notes)


def test_decides_only_every_n_days_and_journals_reasoning():
    model = FakeModel(answer({"SPY": 1.0}, "index is safest"))
    bot = LLMManager(model, every=5, cache_dir=None)
    history = market()
    decisions = [bot.decide(history.iloc[: 60 + i], EMPTY) for i in range(11)]
    assert [d is not None for d in decisions] == [True, *[False] * 4, True, *[False] * 4, True]
    assert len(model.prompts) == 3
    assert bot.journal[0].reasoning == "index is safest" and bot.journal[0].confidence == 0.6


def test_broken_answers_mean_hold_not_crash():
    bot = LLMManager(FakeModel("not json at all"), cache_dir=None)
    assert bot.decide(market(), EMPTY) is None
    assert bot.journal[0].targets is None and "holding" in bot.journal[0].notes


def test_the_briefing_only_contains_the_past():
    history = market()
    text = briefing(history.iloc[:80], EMPTY, [])
    assert history.index[79].strftime("%Y-%m-%d") in text
    assert history.index[80].strftime("%Y-%m-%d") not in text
    assert f"{history['NVDA'].iloc[79]:.2f}" in text and f"{history['NVDA'].iloc[80]:.2f}" not in text


def test_cache_answers_the_same_prompt_without_asking_again(tmp_path):
    first = FakeModel(answer({"QQQ": 0.8}))
    LLMManager(first, cache_dir=tmp_path).decide(market(), EMPTY)
    second = FakeModel(answer({"SPY": 0.1}))
    bot = LLMManager(second, cache_dir=tmp_path)
    assert bot.decide(market(), EMPTY) == {"QQQ": 0.8}
    assert second.prompts == [] and bot.journal[0].cached


def test_full_backtest_goes_through_the_risk_manager():
    history = market()
    bot = LLMManager(FakeModel(answer({"NVDA": 0.9, "SPY": 0.1})), every=10, cache_dir=None)
    result = run_backtest(bot, history, history, 1000, limits=RiskLimits(), trade_from=history.index[60])
    assert any(e.kind == "clipped" and "NVDA" in e.detail for e in result.events)  # 90% -> 25%
    assert result.exposure.max() <= 1 + 1e-9
    assert len(bot.journal) == 6  # 60 trading days / every 10 (the last day never decides)


def test_answers_in_the_wrong_format_are_rescued_and_noted():
    from bot_arena.strategies.llm import parse_answer

    raw = '```json\n{"weights": {"SPY": 0.5}, "reasoning": "x", "confidence": 0.7}\n```'
    data, notes = parse_answer(raw)
    assert data["targets"] == {"SPY": 0.5}
    assert "Markdown code block" in notes[0] and "'weights'" in notes[1]

    data, notes = parse_answer('Sure! Here it is: {"targets": {"QQQ": 1}, "reasoning": "y", "confidence": 1}')
    assert data["targets"] == {"QQQ": 1} and "extra text" in notes[0]

    data, notes = parse_answer('{"AAPL": 0.15, "SPY": 0.5, "reasoning": "flat", "confidence": 0.6}')
    assert data["targets"] == {"AAPL": 0.15, "SPY": 0.5} and "top level" in notes[0]

    data, notes = parse_answer('{"FUND_1": 0.6, "STOCK_B": 0.25, "reasoning": "anon", "confidence": 0.8}')
    assert data["targets"] == {"FUND_1": 0.6, "STOCK_B": 0.25}  # anonymized names at the top level

    # Weights twice (top level and under target_weights), reasoning after the code block:
    raw = '```json\n{"FUND_1": 0.3, "target_weights": {"FUND_1": 0.3, "STOCK_A": 0.2}}\n```\nI like funds.'
    data, notes = parse_answer(raw)
    assert data["targets"] == {"FUND_1": 0.3, "STOCK_A": 0.2} and data["reasoning"] == "I like funds."
    assert "wrote the reasoning outside the JSON" in notes

    with pytest.raises(KeyError):
        parse_answer('{"reasoning": "no weights at all", "confidence": 0.2}')


def test_a_rescued_answer_is_still_traded():
    raw = '```json\n{"weights": {"SPY": 1.0}, "reasoning": "index", "confidence": 0.7}\n```'
    bot = LLMManager(FakeModel(raw), cache_dir=None)
    assert bot.decide(market(), EMPTY) == {"SPY": 1.0}
    assert bot.journal[0].notes[:2] == [
        "answer was wrapped in a Markdown code block",
        "used 'weights' instead of 'targets'",
    ]


def test_anonymous_mode_hides_names_dates_and_prices():
    model = FakeModel(answer({"FUND_1": 0.5, "STOCK_A": 0.2}))
    bot = LLMManager(model, label="anon", anonymize=True, cache_dir=None)
    history = market()
    targets = bot.decide(history, EMPTY)
    prompt = model.prompts[0]
    for symbol in SYMBOLS:
        assert symbol not in prompt
    assert "2026" not in prompt and "trading day 1" in prompt
    assert f"{history['NVDA'].iloc[-1]:.2f}" not in prompt
    # The answer is translated back to real tickers.
    real = {a: s for s, a in bot.aliases.items()}
    assert targets == {real["FUND_1"]: 0.5, real["STOCK_A"]: 0.2}
    assert real["FUND_1"] in {"SPY", "QQQ"}


def test_aliases_are_stable_and_shuffled():
    bot = LLMManager(FakeModel(answer({})), label="x", anonymize=True, cache_dir=None)
    first = dict(bot._alias_map(SYMBOLS))
    assert bot._alias_map(SYMBOLS) == first
    assert set(first.values()) == {"FUND_1", "FUND_2", "STOCK_A", "STOCK_B", "STOCK_C"}


def test_seeded_sampling_gets_its_own_cache(tmp_path):
    from bot_arena.strategies.llm import OllamaClient

    assert OllamaClient("m").cache_id == "m"  # default settings keep the old cache valid
    assert (
        OllamaClient("m", temperature=0.7, seed=1).cache_id
        != OllamaClient("m", temperature=0.7, seed=2).cache_id
    )
