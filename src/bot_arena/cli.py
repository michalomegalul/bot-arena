"""Command line entry point: `arena fetch | chart | backtest | account`."""

import argparse
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from bot_arena import data, metrics
from bot_arena.backtest import buy_and_hold
from bot_arena.chart import plot_equity
from bot_arena.config import BENCHMARK, STARTING_CASH, WATCHLIST, load_settings
from bot_arena.db.cli import register as register_db
from bot_arena.engine import run_backtest
from bot_arena.risk import AnyKillSwitch, LocalKillSwitch, RiskLimits
from bot_arena.strategies import SpyHodler, full_roster, roster


def cmd_fetch(args: argparse.Namespace) -> None:
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    bars = data.fetch_daily_bars(load_settings(), WATCHLIST, start)
    data.save_bars(bars)
    days = bars.index.get_level_values("timestamp").nunique()
    print(f"Saved {len(bars)} bars ({days} trading days, {len(WATCHLIST)} symbols) to {data.BARS_FILE}")


def cmd_chart(args: argparse.Namespace) -> None:
    prices = data.closes(data.load_bars())
    curves = {sym: buy_and_hold(prices[sym], STARTING_CASH) for sym in prices.columns}

    print(f"{'symbol':<8}{'final $':>10}{'return':>10}{'max drawdown':>15}")
    for sym, equity in sorted(curves.items(), key=lambda kv: -kv[1].iloc[-1]):
        mark = "  <- benchmark" if sym == BENCHMARK else ""
        print(
            f"{sym:<8}{equity.iloc[-1]:>10,.2f}{metrics.total_return(equity):>10.1%}"
            f"{metrics.max_drawdown(equity):>15.1%}{mark}"
        )

    out = Path(args.out)
    plot_equity(curves, BENCHMARK, STARTING_CASH, out)
    print(f"Chart written to {out}")


def cmd_backtest(args: argparse.Namespace) -> None:
    with ExitStack() as stack:
        conn = None
        if args.save:
            from bot_arena.db import repository as repo

            conn = stack.enter_context(repo.connect())
            repo.migrate(conn)
        _backtest(args, conn)


def _backtest(args: argparse.Namespace, conn) -> None:
    kill_switch = LocalKillSwitch()
    if conn is not None:
        from bot_arena.db.repository import DbKillSwitch

        kill_switch = AnyKillSwitch(kill_switch, DbKillSwitch(conn))

    bars = data.load_bars()
    opens, closes = data.prices(bars, "open"), data.prices(bars, "close")
    if args.no_risk:
        limits = RiskLimits.unlimited()
    else:
        max_dd = args.max_drawdown / 100 if args.max_drawdown else None
        limits = RiskLimits(max_drawdown=max_dd, allowed_symbols=frozenset(WATCHLIST))
    results = [
        run_backtest(bot, opens, closes, STARTING_CASH, args.slippage_bps, args.fee, limits, kill_switch)
        for bot in roster(args.seed)
    ]
    start, end = closes.index[0].date(), closes.index[-1].date()
    print(
        f"Backtest {start} -> {end} ({len(closes)} trading days), ${STARTING_CASH:,.0f} each, "
        f"slippage {args.slippage_bps:g} bps, fee ${args.fee:g}/trade\n"
    )

    header = f"{'bot':<20}{'final $':>10}{'return':>9}{'CAGR':>8}{'Sharpe':>8}{'Sortino':>9}"
    print(header + f"{'max DD':>9}{'trades':>8}{'invested':>10}{'risk events':>13}  status")
    print("-" * (len(header) + 48))
    for r in sorted(results, key=lambda r: -r.equity.iloc[-1]):
        eq = r.equity
        print(
            f"{r.strategy.label:<19}{eq.iloc[-1]:>10,.2f}{metrics.total_return(eq):>9.1%}"
            f"{metrics.cagr(eq):>8.1%}{metrics.sharpe(eq):>8.2f}{metrics.sortino(eq):>9.2f}"
            f"{metrics.max_drawdown(eq):>9.1%}{len(r.fills):>8}{r.exposure.mean():>10.0%}"
            f"{len(r.events):>13}  {'💀 ' if r.status == 'eliminated' else ''}{r.status}"
        )
    for r in results:
        for e in r.events:
            if e.kind in {"eliminated", "kill_switch", "rejected"}:
                print(f"  {e.date.date()}  {r.strategy.label}: {e.kind}, {e.detail}")

    benchmark = next(r for r in results if isinstance(r.strategy, SpyHodler)).strategy.name
    out = Path(args.out)
    plot_equity(
        {r.strategy.name: r.equity for r in results},
        benchmark,
        STARTING_CASH,
        out,
        title=f"Bot Arena backtest: ${STARTING_CASH:,.0f} each, {start} to {end}",
    )
    print(f"\nChart written to {out}")

    if conn is not None:
        from bot_arena.db.repository import save_backtest, save_bars

        params = {k: v for k, v in vars(args).items() if k != "func"}
        run_id = save_backtest(conn, results, params, STARTING_CASH)
        save_bars(conn, bars)  # so the UI can draw price charts for this run
        print(f"Saved as run #{run_id} (see `arena db runs`)")


def cmd_replay(args: argparse.Namespace) -> None:
    """Push history through the streaming services (in memory) and compare with the backtest."""
    import time

    from bot_arena.pipeline import events as ev
    from bot_arena.pipeline.pipeline import equity_curves, replay, statuses
    from bot_arena.pipeline.services import BotService, BrokerService

    bars = data.load_bars()
    opens, closes = data.prices(bars, "open"), data.prices(bars, "close")
    limits = RiskLimits(allowed_symbols=frozenset(WATCHLIST))
    bots = roster(args.seed)
    run_event = ev.run(ev.day(closes.index[0]), [b.name for b in bots], STARTING_CASH, 5.0, 0.0)

    started = time.perf_counter()
    if args.kafka:
        # The services must already be running: arena broker / arena bot <name> --topic <topic>
        from bot_arena.pipeline.kafka_log import KafkaLog
        from bot_arena.pipeline.pipeline import feed_and_wait, history_days

        log = KafkaLog(args.kafka)
        if log.end_offset():
            raise SystemExit(f"Topic {args.kafka} is not empty; replays need a fresh topic.")
        feed_and_wait(log, run_event, history_days(opens, closes))
        time.sleep(2)  # let the last portfolios land
    else:
        services = [BrokerService(), *(BotService(b, limits) for b in bots)]
        log = replay(services, opens, closes, run_event)
    took = time.perf_counter() - started
    print(f"Replayed {len(closes)} days as {log.end_offset():,} events in {took:.1f}s\n")

    curves, status = equity_curves(log), statuses(log)
    print(f"{'bot':<20}{'pipeline $':>12}{'backtest $':>12}  match")
    for bot in roster(args.seed):
        expected = run_backtest(bot, opens, closes, STARTING_CASH, 5.0, 0.0, limits).equity
        got = curves[bot.name]
        same = got.tolist() == expected.tolist()
        print(
            f"{bot.label:<19}{got.iloc[-1]:>12,.2f}{expected.iloc[-1]:>12,.2f}  "
            f"{'✓ exact' if same else '✗ DIFFERENT'}  ({status[bot.name]})"
        )


def _kill_switch():
    """Local file/env switch, plus the database switch when a database is configured."""
    import os

    from dotenv import load_dotenv

    load_dotenv()
    if not os.getenv("DATABASE_URL"):
        return LocalKillSwitch()
    from bot_arena.db import repository as repo

    return AnyKillSwitch(LocalKillSwitch(), repo.DbKillSwitch(repo.connect()))


def cmd_broker(args: argparse.Namespace) -> None:
    from bot_arena.pipeline.kafka_log import KafkaLog
    from bot_arena.pipeline.runner import run_forever
    from bot_arena.pipeline.services import BrokerService

    run_forever(BrokerService(), KafkaLog(args.topic))


def cmd_bot(args: argparse.Namespace) -> None:
    from bot_arena.pipeline.kafka_log import KafkaLog
    from bot_arena.pipeline.runner import run_forever
    from bot_arena.pipeline.services import BotService

    bots = {b.name.lower().replace(" ", "-"): b for b in roster(args.seed)}
    if args.name not in bots:
        raise SystemExit(f"Unknown bot {args.name!r}. Choose from: {', '.join(bots)}")
    limits = RiskLimits(allowed_symbols=frozenset(WATCHLIST))
    run_forever(BotService(bots[args.name], limits, _kill_switch()), KafkaLog(args.topic))


def cmd_paper_init(args: argparse.Namespace) -> None:
    from bot_arena.pipeline import ingest
    from bot_arena.pipeline.kafka_log import KafkaLog

    bots = roster()
    started = ingest.seed_run(
        KafkaLog(args.topic),
        [b.name for b in bots],
        STARTING_CASH,
        args.slippage_bps,
        args.fee,
        args.warmup_days,
        load_settings(),
        WATCHLIST,
        datetime.now(ingest.NEW_YORK).date(),
        emojis={b.name: b.emoji for b in bots},
    )
    print("Paper run started." if started else "This topic already has a run; nothing to do.")


def cmd_ingest(args: argparse.Namespace) -> None:
    from bot_arena.pipeline import ingest
    from bot_arena.pipeline.kafka_log import KafkaLog

    log, settings = KafkaLog(args.topic), load_settings()
    if args.once:
        days = ingest.catch_up_days(log, settings, WATCHLIST, datetime.now(UTC))
        print(f"Ingested {len(days)} day(s): {', '.join(days) or 'nothing new'}")
    else:
        ingest.run_ingest(log, settings, WATCHLIST, args.poll_seconds)


def cmd_recorder(args: argparse.Namespace) -> None:
    from bot_arena.db import repository as repo
    from bot_arena.pipeline.kafka_log import KafkaLog
    from bot_arena.pipeline.recorder import run_recorder

    log = KafkaLog(args.topic)
    conn = repo.connect()
    repo.migrate(conn)
    run_recorder(conn, log, log.topic)


def cmd_api(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "bot_arena.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=["src"] if args.reload else None,  # not web/node_modules
    )


def cmd_tournament(args: argparse.Namespace) -> None:
    """Rule bots vs LLM bots over one window, with warmup history before it."""
    import json
    import time

    import pandas as pd

    from bot_arena.strategies.llm import LLMManager, OllamaClient

    bars = data.load_bars()
    opens, closes = data.prices(bars, "open"), data.prices(bars, "close")
    start = pd.Timestamp(args.start, tz="UTC")
    limits = RiskLimits(allowed_symbols=frozenset(WATCHLIST))

    bots = list(full_roster(args.seed))
    emojis = iter("🤖🦾🧠👾🛸🔮")
    for spec in filter(None, args.models.split(",")):
        model, _, label = spec.partition("=")
        bots.append(LLMManager(OllamaClient(model, args.ollama), label or model, args.every, next(emojis)))

    results = []
    for bot in bots:
        started = time.perf_counter()
        results.append(
            run_backtest(bot, opens, closes, STARTING_CASH, 5.0, args.fee, limits, trade_from=start)
        )
        if isinstance(bot, LLMManager):
            asked = sum(not e.cached for e in bot.journal)
            failed = sum(e.targets is None for e in bot.journal)
            print(
                f"{bot.label}: {len(bot.journal)} decisions ({asked} new, {failed} failed) "
                f"in {time.perf_counter() - started:.0f}s",
                flush=True,
            )

    end = closes.index[-1].date()
    print(
        f"\nTournament {start.date()} -> {end}, ${STARTING_CASH:,.0f} each, LLMs decide every {args.every} days\n"
    )
    print(f"{'bot':<26}{'final $':>10}{'return':>9}{'Sharpe':>8}{'max DD':>9}{'trades':>8}{'invested':>10}")
    for r in sorted(results, key=lambda r: -r.equity.iloc[-1]):
        eq = r.equity
        print(
            f"{r.strategy.label:<25}{eq.iloc[-1]:>10,.2f}{metrics.total_return(eq):>9.1%}"
            f"{metrics.sharpe(eq):>8.2f}{metrics.max_drawdown(eq):>9.1%}{len(r.fills):>8}"
            f"{r.exposure.mean():>10.0%}"
        )

    journals = {b.name: b.journal_dicts() for b in bots if isinstance(b, LLMManager)}
    out = Path(args.journal_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(journals, indent=1, ensure_ascii=False))
    print(f"\nJournals written to {out}")

    if args.save:
        from bot_arena.db import repository as repo

        with repo.connect() as conn:
            repo.migrate(conn)
            params = {k: v for k, v in vars(args).items() if k != "func"} | {"tournament": True}
            run_id = repo.save_backtest(conn, results, params, STARTING_CASH)
            repo.save_journals(conn, run_id, journals)
            repo.save_bars(conn, bars)
        print(f"Saved as run #{run_id}")


def cmd_account(args: argparse.Namespace) -> None:
    from alpaca.trading.client import TradingClient

    settings = load_settings()
    account = TradingClient(settings.api_key, settings.secret_key, paper=settings.paper).get_account()
    kind = "PAPER" if settings.paper else "LIVE"
    print(
        f"{kind} account {account.account_number}: status {account.status}, "
        f"equity ${float(account.equity):,.2f}, cash ${float(account.cash):,.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="arena", description="Bot Arena")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("fetch", help="download daily bars for the watchlist")
    p.add_argument("--start", default=f"{datetime.now(UTC).year}-01-01", help="YYYY-MM-DD")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("chart", help="buy-and-hold $1000 in each symbol and plot it")
    p.add_argument("--out", default="charts/buy_and_hold.png")
    p.set_defaults(func=cmd_chart)

    p = sub.add_parser("backtest", help="race the bots over the downloaded history")
    p.add_argument("--slippage-bps", type=float, default=5.0, help="price penalty per trade (default 5)")
    p.add_argument("--fee", type=float, default=0.0, help="dollar fee per trade (default 0)")
    p.add_argument("--seed", type=int, default=42, help="random seed for the monkey")
    p.add_argument(
        "--max-drawdown", type=float, default=30, help="eliminate a bot at this %% drop (0 = never)"
    )
    p.add_argument("--no-risk", action="store_true", help="turn off the risk manager (hard rules stay)")
    p.add_argument("--save", action="store_true", help="store the run in the database (DATABASE_URL)")
    p.add_argument("--out", default="charts/backtest.png")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("replay", help="push history through the streaming services and compare")
    p.add_argument("--seed", type=int, default=42, help="random seed for the monkey")
    p.add_argument(
        "--kafka",
        metavar="TOPIC",
        help="replay through Redpanda into a fresh TOPIC (services run separately)",
    )
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("broker", help="service: fill every bot's orders and report portfolios")
    p.add_argument("--topic", default=None, help="event log topic (default: $ARENA_TOPIC or arena.paper)")
    p.set_defaults(func=cmd_broker)

    p = sub.add_parser(
        "bot", help="service: run one bot (spy-hodler, momentum, mean-reversion, random-monkey)"
    )
    p.add_argument("name")
    p.add_argument("--topic", default=None, help="event log topic (default: $ARENA_TOPIC or arena.paper)")
    p.add_argument("--seed", type=int, default=42, help="random seed for the monkey")
    p.set_defaults(func=cmd_bot)

    paper = sub.add_parser("paper", help="the live paper-trading run").add_subparsers(required=True)
    p = paper.add_parser("init", help="start a run: write its config and warmup history to the log")
    p.add_argument("--topic", default=None)
    p.add_argument("--warmup-days", type=int, default=120, help="price history before day one (>= 50)")
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--fee", type=float, default=0.0)
    p.set_defaults(func=cmd_paper_init)

    p = sub.add_parser("ingest", help="service: add each finished trading day's prices to the log")
    p.add_argument("--topic", default=None)
    p.add_argument("--poll-seconds", type=int, default=300)
    p.add_argument("--once", action="store_true", help="catch up once and exit")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("recorder", help="service: mirror the log into the database")
    p.add_argument("--topic", default=None)
    p.set_defaults(func=cmd_recorder)

    p = sub.add_parser("api", help="service: the web UI and its read-only API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    p.set_defaults(func=cmd_api)

    p = sub.add_parser("tournament", help="rule bots vs LLM bots over one window")
    p.add_argument("--start", default="2026-01-02", help="first trading day (earlier days are warmup)")
    p.add_argument("--models", default="gemma3:12b=Gemma 3 12B", help="model=Label,model=Label (Ollama)")
    p.add_argument("--every", type=int, default=5, help="LLMs decide every N trading days")
    p.add_argument("--fee", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ollama", default="http://192.168.4.19:11434")
    p.add_argument("--journal-out", default="data/journals/tournament.json")
    p.add_argument("--save", action="store_true", help="store results and journals in the database")
    p.set_defaults(func=cmd_tournament)

    p = sub.add_parser("account", help="check the Alpaca connection")
    p.set_defaults(func=cmd_account)

    register_db(sub)

    args = parser.parse_args()
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    args.func(args)
