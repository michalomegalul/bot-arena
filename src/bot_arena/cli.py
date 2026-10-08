"""Command line entry point: `arena fetch`, `arena chart`, `arena account`."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from bot_arena import backtest, data
from bot_arena.chart import plot_equity
from bot_arena.config import BENCHMARK, STARTING_CASH, WATCHLIST, load_settings


def cmd_fetch(args: argparse.Namespace) -> None:
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    bars = data.fetch_daily_bars(load_settings(), WATCHLIST, start)
    data.save_bars(bars)
    days = bars.index.get_level_values("timestamp").nunique()
    print(f"Saved {len(bars)} bars ({days} trading days, {len(WATCHLIST)} symbols) to {data.BARS_FILE}")


def cmd_chart(args: argparse.Namespace) -> None:
    prices = data.closes(data.load_bars())
    curves = {sym: backtest.buy_and_hold(prices[sym], STARTING_CASH) for sym in prices.columns}

    print(f"{'symbol':<8}{'final $':>10}{'return':>10}{'max drawdown':>15}")
    for sym, equity in sorted(curves.items(), key=lambda kv: -kv[1].iloc[-1]):
        mark = "  <- benchmark" if sym == BENCHMARK else ""
        print(
            f"{sym:<8}{equity.iloc[-1]:>10,.2f}{backtest.total_return(equity):>10.1%}"
            f"{backtest.max_drawdown(equity):>15.1%}{mark}"
        )

    out = Path(args.out)
    plot_equity(curves, BENCHMARK, STARTING_CASH, out)
    print(f"Chart written to {out}")


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

    p = sub.add_parser("account", help="check the Alpaca connection")
    p.set_defaults(func=cmd_account)

    args = parser.parse_args()
    args.func(args)
