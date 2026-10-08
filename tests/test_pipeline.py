"""The streaming pipeline must reproduce the backtest engine exactly."""

import numpy as np
import pandas as pd
import pytest

from bot_arena.engine import run_backtest
from bot_arena.pipeline import events as ev
from bot_arena.pipeline.events import Event
from bot_arena.pipeline.log import MemoryLog
from bot_arena.pipeline.pipeline import Pipeline, equity_curves, history_days, replay, statuses
from bot_arena.pipeline.runner import catch_up
from bot_arena.pipeline.services import BotService, BrokerService
from bot_arena.risk import RiskLimits
from bot_arena.strategies import MeanReversion, Momentum, RandomMonkey, SpyHodler


def market(n=260, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-02", periods=n, freq="B", tz="UTC")
    drifts = {"SPY": 0.0004, "QQQ": 0.0006, "AAA": 0.001, "BBB": -0.0008, "CCC": 0.0}
    closes = pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(d + rng.normal(0, 0.015, n))) for s, d in drifts.items()}, index=idx
    )
    closes = closes[sorted(closes.columns)]  # real data comes sorted; the monkey's picks depend on it
    opens = closes.shift(1).fillna(closes.iloc[0]) * (1 + rng.normal(0, 0.003, closes.shape))
    return opens, closes


def roster():
    return [SpyHodler(), Momentum(), MeanReversion(), RandomMonkey(seed=3)]


def run_both(limits, slippage=5.0, fee=0.0):
    opens, closes = market()
    expected = {bot.name: run_backtest(bot, opens, closes, 1000, slippage, fee, limits) for bot in roster()}
    bots = roster()
    run_event = ev.run("2025-01-02", [b.name for b in bots], 1000, slippage, fee)
    log = replay([BrokerService(), *(BotService(b, limits) for b in bots)], opens, closes, run_event)
    return expected, log


@pytest.mark.parametrize("limits", [RiskLimits.unlimited(), RiskLimits(), RiskLimits(max_drawdown=0.1)])
def test_replay_matches_the_backtest_exactly(limits):
    expected, log = run_both(limits, fee=1.0)
    curves = equity_curves(log)
    for name, result in expected.items():
        assert curves[name].tolist() == result.equity.tolist(), name  # exact, not approx
        assert statuses(log)[name] == result.status


def test_fills_and_risk_events_match_the_backtest():
    expected, log = run_both(RiskLimits(max_drawdown=0.1))
    events = [e for _, e in log.read()]
    for name, result in expected.items():
        fills = [e for e in events if e.type == ev.FILL and e.key == name]
        assert [(f.data["symbol"], f.data["side"], f.data["shares"]) for f in fills] == [
            (f.symbol, f.side, f.shares) for f in result.fills
        ]
        risk = [e for e in events if e.type == ev.RISK and e.key == name]
        assert [r.data["kind"] for r in risk] == [r.kind for r in result.events]


def test_events_survive_a_json_round_trip():
    _, log = run_both(RiskLimits())
    for _, event in log.read():
        assert Event.from_json(event.to_json()) == event


def test_restarted_services_rebuild_state_without_duplicating_anything():
    opens, closes = market(n=120)
    days = list(history_days(opens, closes))
    bots = roster()
    run_event = ev.run("2025-01-02", [b.name for b in bots], 1000, 5.0, 0.0)

    # Run the first half, then "crash" every service.
    log = MemoryLog()
    first = Pipeline(log, [BrokerService(), *(BotService(b, RiskLimits()) for b in bots)])
    first.append([run_event])
    first.drain()
    for _, day_events in days[:60]:
        first.append(day_events)
        first.drain()
    size_before_restart = log.end_offset()

    # Fresh services catch up from the log, then continue with the second half.
    restarted = Pipeline(log, [BrokerService(), *(BotService(b, RiskLimits()) for b in roster())])
    assert log.end_offset() == size_before_restart  # nothing was appended twice
    for _, day_events in days[60:]:
        restarted.append(day_events)
        restarted.drain()

    ids = [e.id for _, e in log.read()]
    assert len(ids) == len(set(ids))

    # Same result as never crashing (the monkey's RNG is rebuilt by recomputing its decisions).
    fresh = replay(
        [BrokerService(), *(BotService(b, RiskLimits()) for b in roster())], opens, closes, run_event
    )
    after_restart, never_crashed = equity_curves(log), equity_curves(fresh)
    for bot, curve in never_crashed.items():
        assert after_restart[bot].tolist() == curve.tolist(), bot


def test_a_lost_output_is_published_on_restart():
    opens, closes = market(n=30)
    bots = [SpyHodler()]
    log = replay(
        [BrokerService(), BotService(bots[0], RiskLimits())],
        opens,
        closes,
        ev.run("2025-01-02", ["SPY Hodler"], 1000, 5.0, 0.0),
    )
    # Simulate a crash right before the bot's last decision was written.
    last_decision = max(off for off, e in log.read() if e.type == ev.DECISION)
    truncated = MemoryLog([e for off, e in log.read() if off != last_decision])

    catch_up(BotService(SpyHodler(), RiskLimits()), truncated)
    decisions = [e for _, e in truncated.read() if e.type == ev.DECISION]
    assert len(decisions) == len([e for _, e in log.read() if e.type == ev.DECISION])


class Oracle(SpyHodler):
    """Pretends to be an LLM bot: not deterministic, and counts how often it is asked."""

    deterministic = False

    def __init__(self):
        super().__init__()
        self.calls = 0

    def decide(self, history, portfolio):
        self.calls += 1
        return super().decide(history, portfolio)


def test_non_deterministic_bots_are_not_asked_again_after_a_restart():
    opens, closes = market(n=30)
    log = replay(
        [BrokerService(), BotService(Oracle(), RiskLimits())],
        opens,
        closes,
        ev.run("2025-01-02", ["SPY Hodler"], 1000, 5.0, 0.0),
    )
    oracle = Oracle()
    catch_up(BotService(oracle, RiskLimits()), log)
    assert oracle.calls == 0


def test_warmup_bars_feed_history_but_never_trade():
    opens, closes = market(n=80)
    warm, live = closes.index[:60], closes.index[60:]
    log = MemoryLog([ev.run(ev.day(live[0]), ["Momentum"], 1000, 0.0, 0.0)])
    for ts in warm:
        for s in closes.columns:
            log.append(ev.bar(s, ev.day(ts), opens.at[ts, s], closes.at[ts, s], warmup=True))
    pipeline = Pipeline(log, [BrokerService(), BotService(Momentum(), RiskLimits.unlimited())])
    for _, day_events in history_days(opens.loc[live], closes.loc[live]):
        pipeline.append(day_events)
        pipeline.drain()

    first_portfolio = next(e for _, e in log.read() if e.type == ev.PORTFOLIO)
    assert first_portfolio.date == ev.day(live[0])  # no trading on warmup days
    # Momentum needs 50 days of history; thanks to warmup it can trade from the first live days.
    first_fill = next(e for _, e in log.read() if e.type == ev.FILL)
    assert first_fill.date <= ev.day(live[2])
