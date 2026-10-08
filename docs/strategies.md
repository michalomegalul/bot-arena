# Strategy research and benchmark

Six extra rule-based bots, each taken from a published, well-known source and run with the **published default parameters**. Nothing was tuned to our data. They give the LLM bots a stronger field to race against than the original four.

## The strategies

| Bot | Idea | Rule as implemented | Source | What the evidence says |
|---|---|---|---|---|
| 🧭 **Faber Trend** (`faber_trend.FaberTrend`) | Trend filter: sidestep crashes | Monthly: each symbol gets 1/N; hold it only if its price is above its 200-day average (Siegel's daily version of Faber's 10-month rule), otherwise that slice is cash | Faber (2007), *A Quantitative Approach to Tactical Asset Allocation*, Journal of Wealth Management ([SSRN PDF](https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf)) | Over ~100 years of the S&P 500, similar returns to buy-and-hold with much lower volatility and drawdowns. Its edge is avoiding long bear markets. It loses to buy-and-hold in V-shaped crashes and choppy markets (whipsaw). |
| 🥇 **Dual Momentum** (`dual_momentum.DualMomentum`) | Own the stronger fund, but only if it's rising | Monthly: compare SPY and QQQ 12-month returns, hold 100% of the winner; if the winner's 12-month return is ≤ 0, hold cash | Antonacci, *Risk Premia Harvesting Through Dual Momentum* ([SSRN 2042750](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750)); *Dual Momentum Investing* (2014) | Strong long-run record in the original (US vs international stocks vs bonds). A 2026 replication found GEM **underperformed a passive index by ~4.8 points a year since 2010**, with its deepest drawdown in 2021–2023 ([SSRN 7427878](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7427878)). Our version uses SPY vs QQQ and cash at 0% instead of T-bills, a simplification. |
| 🍰 **Equal Weight** (`equal_weight.EqualWeight`) | 1/N: split equally, rebalance monthly | First day: 1/N in every symbol; then on the first trading day of each month, back to 1/N (skipped if within 2 percentage points) | DeMiguel, Garlappi & Uppal (2009), *Optimal Versus Naive Diversification*, Review of Financial Studies ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1376199)) | None of 14 optimisation models consistently beat 1/N out of sample after costs; estimation error eats the theoretical gains. A hard benchmark to beat. |
| 🎚️ **Vol Target** (`vol_target.VolTarget`) | Hold less when markets are jumpy | Monthly: SPY weight = 15% / realised volatility of the last 21 days (annualised), capped at 100% (no borrowing); rest in cash | Moreira & Muir (2017), *Volatility-Managed Portfolios*, Journal of Finance 72(4) ([NBER w22208](https://www.nber.org/papers/w22208)) | Higher Sharpe ratios across many factors and the market, because volatility doesn't bring proportionally higher returns. Later work debates how much survives realistic costs and constraints; without leverage, the upside in calm markets is capped. |
| 🎯 **Connors RSI2** (`connors_rsi2.ConnorsRSI2`) | Buy sharp 1–2 day dips in an uptrend | Daily, per symbol: if price > 200-day average and RSI(2) < 10, buy a 25% slot (most oversold first); sell when price closes above its 5-day average | Connors & Alvarez (2008), *Short Term Trading Strategies That Work*; rules summarised by [StockCharts](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2) | Popular, with a good published record on indices, but high turnover. The edge is small per trade, so **costs decide whether it works** (see the $1 fee table). The short side of the original is left out (we are long-only). |
| 🏆 **Winners 12-1** (`winners.Winners12m1`) | Cross-sectional momentum | Monthly: rank symbols by the return from 12 months ago to 1 month ago, hold the top 3 equally (risk manager trims single stocks to 25%) | Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*, Journal of Finance ([overview](https://alphaarchitect.com/momentum-factor-investing-30-years-of-out-of-sample-data/)) | One of the most robust anomalies: about 1%/month long-short in 1965–1989, and still present 30 years out of sample, but with rare, severe crashes. The research uses hundreds of stocks; with 6 symbols, "top 3" is a weak, noisy version. |

Considered but not added: **MACD crossover** and **Bollinger band reversion** (similar to Momentum and Mean Reversion already in the arena, with weaker published evidence), and the **SPY golden/death cross** (the trend-filter idea is already covered by Faber Trend).

## Benchmark

Setup: cached daily bars 2023-01-03 to 2026-10-07 (adjusted for splits and dividends), $1,000 per bot, 5 bps slippage, risk manager on (25% per single stock, SPY/QQQ up to 100%, eliminated at −30%), decisions after the close, fills at the next open. Script: `scratchpad/bench/bench.py` (not committed).

### Full period 2023-01-03 to 2026-10-07, fee $0/trade

| Bot | Final | Return | CAGR | Sharpe | Sortino | Max DD | Trades | Avg invested | Status |
|---|---|---|---|---|---|---|---|---|---|
| 🍰 Equal Weight | $4,089 | +308.9% | 45.7% | 1.67 | 2.58 | -29.9% | 51 | 98% | active |
| 📈 Momentum | $2,416 | +141.6% | 26.6% | 1.36 | 2.10 | -17.5% | 313 | 78% | active |
| 🐒 Random Monkey | $2,162 | +116.2% | 22.9% | 1.27 | 1.99 | -15.5% | 292 | 60% | active |
| 🐢 SPY Hodler | $2,126 | +112.6% | 22.3% | 1.43 | 2.15 | -18.8% | 1 | 100% | active |
| 🥇 Dual Momentum | $1,850 | +85.0% | 17.9% | 1.06 | 1.58 | -19.0% | 17 | 73% | active |
| 🎚️ Vol Target | $1,834 | +83.4% | 17.6% | 1.29 | 1.89 | -16.3% | 13 | 93% | active |
| 🏆 Winners 12-1 | $1,833 | +83.3% | 17.6% | 0.90 | 1.35 | -28.1% | 52 | 60% | active |
| 🧭 Faber Trend | $1,573 | +57.3% | 12.9% | 0.82 | 1.16 | -19.5% | 57 | 62% | active |
| 🎯 Connors RSI2 | $1,354 | +35.4% | 8.4% | 0.86 | 1.31 | -14.3% | 315 | 15% | active |
| 🔄 Mean Reversion | $1,343 | +34.3% | 8.2% | 0.68 | 1.10 | -18.1% | 46 | 15% | active |

### Full period 2023-01-03 to 2026-10-07, fee $1/trade

| Bot | Final | Return | CAGR | Sharpe | Sortino | Max DD | Trades | Avg invested | Status |
|---|---|---|---|---|---|---|---|---|---|
| 🍰 Equal Weight | $3,957 | +295.7% | 44.4% | 1.64 | 2.54 | -29.9% | 43 | 98% | active |
| 🐢 SPY Hodler | $2,123 | +112.3% | 22.3% | 1.43 | 2.15 | -18.8% | 1 | 100% | active |
| 📈 Momentum | $2,000 | +100.0% | 20.3% | 1.08 | 1.65 | -18.3% | 314 | 78% | active |
| 🥇 Dual Momentum | $1,825 | +82.5% | 17.4% | 1.04 | 1.54 | -19.1% | 17 | 73% | active |
| 🎚️ Vol Target | $1,817 | +81.7% | 17.3% | 1.27 | 1.86 | -16.4% | 13 | 93% | active |
| 🏆 Winners 12-1 | $1,768 | +76.8% | 16.4% | 0.85 | 1.27 | -28.2% | 52 | 60% | active |
| 🐒 Random Monkey | $1,755 | +75.5% | 16.2% | 0.95 | 1.46 | -16.5% | 290 | 61% | active |
| 🧭 Faber Trend | $1,509 | +50.9% | 11.6% | 0.75 | 1.06 | -19.5% | 56 | 62% | active |
| 🔄 Mean Reversion | $1,292 | +29.2% | 7.1% | 0.60 | 0.97 | -18.1% | 46 | 15% | active |
| 🎯 Connors RSI2 | $978 | -2.2% | -0.6% | -0.01 | -0.01 | -14.9% | 315 | 15% | active |

### Per calendar year (from the full run, fee $0): return / Sharpe

| Bot | 2023 | 2024 | 2025 | 2026 YTD | Years beating SPY Hodler |
|---|---|---|---|---|---|
| 🍰 Equal Weight | +90.4% / 2.92 | +56.7% / 2.04 | +22.6% / 0.86 | +15.8% / 1.06 | 4/4 |
| 📈 Momentum | +34.2% / 1.85 | +57.5% / 2.07 | +16.2% / 0.99 | +2.7% / 0.30 | 2/4 |
| 🐒 Random Monkey | +37.4% / 2.04 | +23.1% / 1.34 | +26.5% / 1.22 | +3.9% / 0.43 | 2/4 |
| 🐢 SPY Hodler | +25.9% / 1.85 | +25.6% / 1.88 | +18.0% / 0.95 | +14.7% / 1.44 | —/4 |
| 🥇 Dual Momentum | +0.0% / 0.00 | +24.8% / 1.39 | +20.1% / 0.97 | +24.0% / 1.49 | 2/4 |
| 🎚️ Vol Target | +17.0% / 1.43 | +24.7% / 1.84 | +12.9% / 0.85 | +12.1% / 1.25 | 0/4 |
| 🏆 Winners 12-1 | +0.0% / 0.00 | +39.0% / 1.65 | +10.0% / 0.48 | +19.8% / 1.37 | 2/4 |
| 🧭 Faber Trend | +10.1% / 1.39 | +48.0% / 1.93 | +0.1% / 0.09 | -0.2% / 0.07 | 1/4 |
| 🎯 Connors RSI2 | -1.7% / -0.43 | +20.6% / 1.77 | +4.3% / 0.40 | +13.9% / 1.83 | 0/4 |
| 🔄 Mean Reversion | +18.4% / 2.53 | +2.8% / 0.38 | +1.4% / 0.17 | +9.4% / 1.89 | 0/4 |

### Luck baseline: Random Monkey over 30 seeds (fee $0, risk manager on)

| | Worst | 25th pct | Median | 75th pct | Best |
|---|---|---|---|---|---|
| Final $ | $1,531 | $1,943 | $2,064 | $2,170 | $3,086 |
| Sharpe | 0.82 | 1.21 | 1.27 | 1.43 | 1.93 |

Monkeys beating SPY Hodler: 12/30 on money, 9/30 on Sharpe (SPY: $2,126, Sharpe 1.43). Median monkey Sharpe 1.29.

## How to read this (caveats)

- **Hindsight watchlist.** The six symbols were picked in 2026, *knowing* NVDA, AAPL and MSFT had a huge run. Any strategy that spreads money across them, like Equal Weight and the Monkey, gets a free boost. **Equal Weight "winning" mostly measures that bias,** not skill. Its −29.9% max drawdown, one point from elimination, shows the risk it took.
- **One sample, mostly a bull market.** 2023–2026 is less than four years. One good or bad year (e.g. the 2025 spring crash) moves the ranking a lot. A single backtest is not evidence.
- **Warm-up.** Faber Trend needs 200 days and Dual Momentum and Winners need 252 days of history. With data starting January 2023, they sit in cash for most or all of 2023 (the "+0.0%" cells). That penalises them versus bots that trade from day one.
- **No tuning.** All parameters are the published defaults. Tuning them on this data would make the table look better and mean less.
- **Costs matter at $1,000.** A $1 fee per trade is 0.1% of a $1,000 position. High-turnover bots (Connors RSI2, Momentum, the Monkey) lose the most, and Connors RSI2 goes from +35% to −2%.
- **The luck baseline.** The median random monkey makes $2,064 with a Sharpe of 1.29. A bot is only interesting if it clearly beats that *and* SPY on risk-adjusted terms. On this data, **no bot beats SPY Hodler's Sharpe of 1.43 except Equal Weight**, and Equal Weight is mostly hindsight.
