"""Command line entry point: `arena fetch | chart | backtest | account`."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from bot_arena import data, metrics
from bot_arena.backtest import buy_and_hold
from bot_arena.chart import plot_equity
from bot_arena.config import BENCHMARK, STARTING_CASH, WATCHLIST, load_settings
from bot_arena.engine import run_backtest
from bot_arena.strategies import SpyHodler, roster


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
    bars = data.load_bars()
    opens, closes = data.prices(bars, "open"), data.prices(bars, "close")
    results = [
        run_backtest(bot, opens, closes, STARTING_CASH, args.slippage_bps, args.fee)
        for bot in roster(args.seed)
    ]
    start, end = closes.index[0].date(), closes.index[-1].date()
    print(
        f"Backtest {start} -> {end} ({len(closes)} trading days), ${STARTING_CASH:,.0f} each, "
        f"slippage {args.slippage_bps:g} bps, fee ${args.fee:g}/trade\n"
    )

    header = f"{'bot':<20}{'final $':>10}{'return':>9}{'CAGR':>8}{'Sharpe':>8}{'Sortino':>9}"
    print(header + f"{'max DD':>9}{'trades':>8}{'invested':>10}")
    print("-" * (len(header) + 27))
    for r in sorted(results, key=lambda r: -r.equity.iloc[-1]):
        eq = r.equity
        print(
            f"{r.strategy.label:<19}{eq.iloc[-1]:>10,.2f}{metrics.total_return(eq):>9.1%}"
            f"{metrics.cagr(eq):>8.1%}{metrics.sharpe(eq):>8.2f}{metrics.sortino(eq):>9.2f}"
            f"{metrics.max_drawdown(eq):>9.1%}{len(r.fills):>8}{r.exposure.mean():>10.0%}"
        )

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
    p.add_argument("--out", default="charts/backtest.png")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("account", help="check the Alpaca connection")
    p.set_defaults(func=cmd_account)

    args = parser.parse_args()
    args.func(args)
