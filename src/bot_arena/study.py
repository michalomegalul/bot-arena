"""Long-history study: every rule bot over ~10 years, on two universes.

- stocks:  the 6-symbol watchlist (SPY, QQQ, AAPL, MSFT, NVDA, TSLA). Picked in 2026 knowing these
           did well, so it flatters anything that holds them (survivorship / hindsight bias).
- sectors: the 11 SPDR sector ETFs plus SPY and QQQ. Nobody picked winners here, so it's the
           fairer test.

`arena study --universe both` prints the tables and writes them to docs/long_history.md.
"""

import argparse
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bot_arena import data, metrics
from bot_arena.broker import Portfolio
from bot_arena.config import STARTING_CASH, WATCHLIST
from bot_arena.engine import BacktestResult, run_backtest
from bot_arena.risk import RiskLimits
from bot_arena.strategies import RandomMonkey, SpyHodler, Strategy, full_roster

SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC", "SPY", "QQQ"]
TRADE_FROM = "2017-01-03"  # a full year of warmup from 2016, so the 200/252-day bots can act from day one
MONKEY_SEEDS = 20
BEAR_MARKETS = {
    "2018 Q4 sell-off": ("2018-10-01", "2018-12-24"),
    "2020 COVID crash": ("2020-02-19", "2020-03-23"),
    "2022 bear market": ("2022-01-03", "2022-10-12"),
}


@dataclass(frozen=True)
class Universe:
    key: str
    title: str
    bars_file: Path
    symbols: list[str]

    def limits(self, breaker: bool = False) -> RiskLimits:
        # Sector ETFs are diversified inside a sector, but a sector is still one concentrated bet
        # (tech, energy...), so they get the same 25% cap as single stocks. SPY and QQQ hold the
        # whole market / Nasdaq-100 and may take everything.
        # The 30% drawdown breaker is the arena's rule, not part of any strategy, so the main tables
        # run without it (it sold everyone at the bottom of the 2020 crash) and its effect is shown
        # separately.
        # max_positions: the arena default (6) fits the 6-stock list but would silently drop picks in a
        # 13-ETF universe (and make bots re-propose them every day), so allow the whole universe.
        return RiskLimits(
            allowed_symbols=frozenset(self.symbols),
            max_positions=len(self.symbols),
            max_drawdown=0.30 if breaker else None,
        )


UNIVERSES = {
    "stocks": Universe("stocks", "6 stocks (hindsight watchlist)", data.BARS_FILE, WATCHLIST),
    "sectors": Universe(
        "sectors", "13 ETFs (11 sectors + SPY + QQQ)", data.DATA_DIR / "bars_sectors.parquet", SECTORS
    ),
}


class Listed(Strategy):
    """Shows a bot only the symbols that exist yet (XLC only lists in 2018-06).

    Some bots assume every column has prices; this keeps not-yet-listed symbols out of sight.
    """

    def __init__(self, inner: Strategy):
        self.inner = inner
        self.name, self.emoji, self.deterministic = inner.name, inner.emoji, inner.deterministic

    def decide(self, history: pd.DataFrame, portfolio: Portfolio) -> dict[str, float] | None:
        return self.inner.decide(history.dropna(axis=1, how="all"), portfolio)


def qqq_hodler() -> Strategy:
    bot = SpyHodler(symbol="QQQ")
    bot.name, bot.emoji = "QQQ Hodler", "🦔"
    return bot


def contestants(seed: int = 42) -> list[Strategy]:
    return [*full_roster(seed), qqq_hodler()]


# --- measuring ---


def yearly_returns(equity: pd.Series) -> pd.Series:
    """Calendar-year returns; the first year counts from the first value."""
    year_end = equity.groupby(equity.index.year).last()
    previous = year_end.shift(1)
    previous.iloc[0] = equity.iloc[0]
    return year_end / previous - 1


def versus(equity: pd.Series, market: pd.Series) -> tuple[float, float, float]:
    """(beta, R², annual alpha) of daily returns against the market's daily returns."""
    both = pd.concat([equity.pct_change(), market.pct_change()], axis=1).dropna()
    bot, mkt = both.iloc[:, 0].to_numpy(), both.iloc[:, 1].to_numpy()
    if bot.std() == 0 or mkt.std() == 0:
        return 0.0, 0.0, 0.0
    beta, intercept = np.polyfit(mkt, bot, 1)
    r2 = float(np.corrcoef(mkt, bot)[0, 1] ** 2)
    return float(beta), r2, float(intercept * 252)


def sharpe_standard_error(sharpe: float, years: float) -> float:
    """Roughly how far a Sharpe ratio can be off by luck alone (Lo 2002, i.i.d. returns)."""
    return math.sqrt((1 + 0.5 * sharpe**2) / years) if years > 0 else float("nan")


def window(equity: pd.Series, start: str, end: str) -> tuple[float, float] | None:
    """(return, max drawdown) between two dates, or None if the bot wasn't running then."""
    part = equity.loc[pd.Timestamp(start, tz="UTC") : pd.Timestamp(end, tz="UTC")]
    if len(part) < 2:
        return None
    return float(part.iloc[-1] / part.iloc[0] - 1), float(metrics.max_drawdown(part))


@dataclass
class UniverseResult:
    universe: Universe
    results: dict[str, BacktestResult]  # $0 fee, no drawdown breaker
    with_fee: dict[str, float]  # final $ at $1 per trade
    with_breaker: dict[str, BacktestResult]  # $0 fee, eliminated at -30% from peak (the arena's rule)
    monkeys: list[pd.Series]  # equity curves over many seeds
    market: pd.Series  # SPY closes over the period
    seconds: float

    @property
    def years(self) -> float:
        eq = next(iter(self.results.values())).equity
        return (len(eq) - 1) / metrics.TRADING_DAYS


def run_universe(
    universe: Universe,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    trade_from: str = TRADE_FROM,
    fee: float = 1.0,
) -> UniverseResult:
    started = time.perf_counter()
    start = pd.Timestamp(trade_from, tz="UTC")

    def run(bot: Strategy, fee_per_trade: float, breaker: bool = False) -> BacktestResult:
        limits = universe.limits(breaker)
        return run_backtest(
            Listed(bot), opens, closes, STARTING_CASH, 5.0, fee_per_trade, limits, trade_from=start
        )

    results = {bot.name: run(bot, 0.0) for bot in contestants()}
    with_fee = {bot.name: float(run(bot, fee).equity.iloc[-1]) for bot in contestants()}
    with_breaker = {bot.name: run(bot, 0.0, breaker=True) for bot in contestants()}
    monkeys = [run(RandomMonkey(seed), 0.0).equity for seed in range(MONKEY_SEEDS)]
    market = closes["SPY"].loc[start:]
    return UniverseResult(
        universe, results, with_fee, with_breaker, monkeys, market, time.perf_counter() - started
    )


# --- tables (markdown) ---


def _md(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _pct(v: float | None, digits: int = 1) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.{digits}%}"


def summary_table(u: UniverseResult) -> str:
    years = u.years
    rows = []
    ranked = sorted(u.results.items(), key=lambda kv: -kv[1].equity.iloc[-1])
    for name, r in ranked:
        eq = r.equity
        sharpe = metrics.sharpe(eq)
        beta, r2, alpha = versus(eq, u.market)
        rows.append(
            [
                f"{r.strategy.emoji} {name}",
                f"${eq.iloc[-1]:,.0f}",
                f"${u.with_fee[name]:,.0f}",
                _pct(metrics.cagr(eq)),
                f"{sharpe:.2f} ± {sharpe_standard_error(sharpe, years):.2f}",
                f"{metrics.sortino(eq):.2f}",
                _pct(metrics.max_drawdown(eq)),
                str(len(r.fills)),
                f"{beta:.2f}",
                f"{r2:.0%}",
                _pct(alpha),
            ]
        )
    headers = ["Bot", "Final", "Final ($1 fee)", "CAGR", "Sharpe ± SE", "Sortino", "Max DD", "Trades"]
    return _md([*headers, "Beta", "R²", "Alpha/yr"], rows)


def yearly_table(u: UniverseResult) -> str:
    yearly = {name: yearly_returns(r.equity) for name, r in u.results.items()}
    spy, qqq = yearly["SPY Hodler"], yearly["QQQ Hodler"]
    years = list(spy.index)
    rows = []
    for name, r in sorted(u.results.items(), key=lambda kv: -kv[1].equity.iloc[-1]):
        y = yearly[name]
        beat_spy = sum(y[yr] > spy[yr] for yr in years) if name != "SPY Hodler" else None
        beat_qqq = sum(y[yr] > qqq[yr] for yr in years) if name != "QQQ Hodler" else None
        rows.append(
            [f"{r.strategy.emoji} {name}", *[_pct(y.get(yr), 0) for yr in years]]
            + [
                "—" if beat_spy is None else f"{beat_spy}/{len(years)}",
                "—" if beat_qqq is None else f"{beat_qqq}/{len(years)}",
            ]
        )
    labels = [str(yr) if yr != years[-1] else f"{yr} YTD" for yr in years]
    return _md(["Bot", *labels, "Beat SPY", "Beat QQQ"], rows)


def bear_table(u: UniverseResult) -> str:
    rows = []
    for name, r in sorted(u.results.items(), key=lambda kv: -kv[1].equity.iloc[-1]):
        cells = [f"{r.strategy.emoji} {name}"]
        for start, end in BEAR_MARKETS.values():
            w = window(r.equity, start, end)
            cells.append("—" if w is None else f"{_pct(w[0])} (DD {_pct(w[1])})")
        rows.append(cells)
    return _md(["Bot", *BEAR_MARKETS], rows)


def breaker_table(u: UniverseResult) -> str:
    """What the arena's 30% elimination rule would have done to each bot."""
    rows = []
    for name, r in sorted(u.results.items(), key=lambda kv: -kv[1].equity.iloc[-1]):
        b = u.with_breaker[name]
        out = next((e for e in b.events if e.kind == "eliminated"), None)
        free, ruled = r.equity.iloc[-1], b.equity.iloc[-1]
        rows.append(
            [
                f"{r.strategy.emoji} {name}",
                f"${free:,.0f}",
                f"{out.date:%Y-%m-%d}" if out else "survived",
                f"${ruled:,.0f}",
                _pct(ruled / free - 1) if out else "—",
            ]
        )
    return _md(
        ["Bot", "Final (no breaker)", "Eliminated on", "Final (with breaker)", "Cost of the rule"], rows
    )


def monkey_table(u: UniverseResult) -> str:
    finals = np.array([eq.iloc[-1] for eq in u.monkeys])
    sharpes = np.array([metrics.sharpe(eq) for eq in u.monkeys])
    spy = u.results["SPY Hodler"].equity
    beat_money = int((finals > spy.iloc[-1]).sum())
    beat_sharpe = int((sharpes > metrics.sharpe(spy)).sum())
    rows = [
        [
            "Final $",
            *[f"${np.percentile(finals, p):,.0f}" for p in (10, 50, 90)],
            f"{beat_money}/{len(finals)}",
        ],
        [
            "Sharpe",
            *[f"{np.percentile(sharpes, p):.2f}" for p in (10, 50, 90)],
            f"{beat_sharpe}/{len(sharpes)}",
        ],
    ]
    return _md(
        ["Random Monkey × " + str(len(finals)) + " seeds", "10th pct", "median", "90th pct", "beats SPY"],
        rows,
    )


def report(results: list[UniverseResult]) -> str:
    first = results[0]
    eq = next(iter(first.results.values())).equity
    span = f"{eq.index[0]:%Y-%m-%d} → {eq.index[-1]:%Y-%m-%d} (~{first.years:.1f} years)"
    parts = [
        "# Long-history study",
        "",
        f"Every rule bot from {span}, after a year of warmup from 2016-01-04, so even the bots that need",
        "200–252 days of history can act from day one. $1,000 each, risk manager on (position caps), 5 bps",
        "slippage, $0 fee unless noted, and **without** the arena's 30% elimination rule (its effect has its",
        "own table). Bot parameters are the published defaults, never tuned to this data. Generated by",
        "`arena study --universe both`.",
        "",
        FINDINGS,
        WHAT_THIS_SHOWS,
    ]
    for u in results:
        parts += [
            "",
            f"## {u.universe.title}",
            "",
            "### Whole period",
            "",
            "Sharpe ± SE: the standard error says how far a Sharpe ratio can be off by luck alone. Two bots",
            "whose ranges overlap are not reliably different. Beta, R² and alpha are measured against SPY's",
            "daily returns: R² is how much of the bot's moves the market explains, and alpha is the return",
            "left over per year.",
            "",
            summary_table(u),
            "",
            "### Year by year",
            "",
            yearly_table(u),
            "",
            "### In bear markets (return, and max drawdown inside the window)",
            "",
            bear_table(u),
            "",
            "### The arena's 30% elimination rule",
            "",
            "In the live arena a bot that falls 30% from its peak sells everything and is frozen. Over ten",
            "years that rule fires in the 2020 crash and in 2022, usually close to the bottom.",
            "",
            breaker_table(u),
            "",
            "### Luck baseline",
            "",
            monkey_table(u),
            "",
            f"<sub>{u.universe.title}: computed in {u.seconds:.0f} s.</sub>",
        ]
    return "\n".join(parts) + "\n"


WHAT_THIS_SHOWS = """## What this shows (for beginners)

- **The 6-stock list flatters everyone.** It was chosen in 2026 knowing NVDA, AAPL, MSFT and QQQ had
  huge runs. Any bot that simply holds them looks brilliant. That's survivorship / hindsight bias,
  and why the **sector ETFs are the fairer test**: nobody hand-picked the winners there.
- **Read Sharpe ± SE before reading the ranking.** Over ~10 years the uncertainty is about ±0.35. A bot
  with Sharpe 0.9 and one with 0.7 can't be told apart.
- **Beta vs alpha.** A bot with high R² and beta near 1 is mostly the market in disguise. You can buy that
  cheaply in one fund. Alpha (what's left over) is the only thing a strategy really adds, and it is
  rare.
- **Bear markets are where the defensive bots should earn their keep.** Trend filters and volatility
  targeting promise to step aside in crashes; the bear-market table checks whether they did, and what
  it cost them the rest of the time.
- **Fees matter at $1,000.** The "$1 fee" column shows how much a dollar per trade costs a high-turnover bot
  over ten years.
- **The Random Monkey is the luck baseline.** Anything inside the monkey's 10th–90th percentile range
  could be luck."""


FINDINGS = """## Findings (run of 2026-10-08, data to 2026-10-07)

- **On the hand-picked 6 stocks, almost everything "beats the market".** Equal Weight turns $1,000 into
  ~$19,800 (+36%/yr) against SPY's ~$4,000, and the monkey beats SPY in 12 of 20 seeds. But Equal Weight
  has a beta of 1.33: it's a leveraged-looking tech bet on stocks we already knew would win (NVDA went
  from $0.79 to $237 split-adjusted). This is what hindsight bias looks like.
- **On the fair universe (sector ETFs), no rotation strategy beats buying and holding SPY.** Only the
  QQQ Hodler and Dual Momentum (which just switches between SPY and QQQ) finish ahead. Equal Weight beat
  SPY in 1 of 10 years, Momentum in 0, and the monkey in 0 of 20 seeds.
- **Defensive bots do defend, and pay for it the rest of the time.** In 2022, Faber Trend lost 9.8%
  and Winners 12-1 lost 0.1% while SPY lost 24.5%. Over ten years they still compound at about half of
  SPY's rate. Vol Target is the exception: a similar Sharpe to SPY (0.97 vs 0.89) with a much smaller
  worst drop (−21.5% vs −33.8%).
- **The differences at the top are within the noise.** Sharpe standard errors are about ±0.35–0.40, so
  0.97 vs 0.89 is not a real difference after ten years of data.
- **Turnover is fatal at $1,000.** At $1 per trade, Momentum on the sectors goes from $2,074 to $129 and
  Connors RSI2 from $1,456 to $79.
- **The arena's 30% elimination rule would have been the worst decision of all.** It sells SPY on
  2020-03-18, within days of the COVID bottom, and the SPY Hodler ends at $1,116 instead of $3,991
  (−72%). A breaker that liquidates and never re-enters locks in the loss.
"""


# --- command ---


def cmd_study(args: argparse.Namespace) -> None:
    keys = ["stocks", "sectors"] if args.universe == "both" else [args.universe]
    results = []
    for key in keys:
        universe = UNIVERSES[key]
        bars = data.load_bars(universe.bars_file)
        opens, closes = data.prices(bars, "open"), data.prices(bars, "close")
        print(f"Running {universe.title}...", flush=True)
        u = run_universe(universe, opens, closes, args.trade_from, args.fee)
        results.append(u)
        print(
            f"\n## {universe.title} ({u.seconds:.0f} s)\n\n{summary_table(u)}\n\n{bear_table(u)}\n\n"
            f"{breaker_table(u)}\n\n{monkey_table(u)}\n"
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report(results))
    print(f"Written to {out}")


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("study", help="every rule bot over ~10 years, on stocks and on sector ETFs")
    p.add_argument("--universe", choices=["stocks", "sectors", "both"], default="both")
    p.add_argument(
        "--fee", type=float, default=1.0, help="fee per trade for the 'with fee' column (default $1)"
    )
    p.add_argument("--trade-from", default=TRADE_FROM, help="first trading day; earlier days are warmup")
    p.add_argument("--out", default="docs/long_history.md")
    p.set_defaults(func=cmd_study)
