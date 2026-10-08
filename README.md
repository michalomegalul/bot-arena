# Bot Arena

Trading bots race from **$1000 each**: classic rule-based strategies, a random monkey, and Claude as a "portfolio manager", all trying to beat simply holding the S&P 500.

Runs on **paper money** (Alpaca paper trading). See [PLAN.md](PLAN.md) for the full design: a Redpanda streaming pipeline, a risk manager with a kill switch, and a live "arena" UI.

## Status

- [x] **Phase 1: Hello market.** Download daily prices and chart $1000 bought and held in each stock.
- [x] **Phase 2: Backtester and the first bots.** Four bots race through history, with fees, slippage and a full metrics table.
- [x] **Phase 3: Database and risk manager.** Kill switch, drawdown breaker, position caps; results stored in Postgres + TimescaleDB.
- [ ] Phase 4: Streaming pipeline (Redpanda)
- [ ] Phase 5: API and arena UI
- [ ] Phase 6: Claude PM
- [ ] Phase 7: Deploy to the homelab
- [ ] Phase 8: Polish

## Quick start

Needs [uv](https://docs.astral.sh/uv/) and a free [Alpaca](https://alpaca.markets) paper account.

```sh
cp .env.example .env      # then paste your paper API keys into .env
uv sync
uv run arena account      # check the connection
uv run arena fetch        # daily bars since Jan 1 -> data/
uv run arena chart        # results table + charts/buy_and_hold.png
uv run arena backtest     # race the bots: metrics table + charts/backtest.png
```

`arena fetch --start 2023-01-01` fetches a longer history. `arena backtest --help` lists the options (slippage, fees, the monkey's seed).

## The bots

| | Bot | Strategy |
|---|---|---|
| 🐢 | **SPY Hodler** | Buys the S&P 500 on day one and never sells. The benchmark. |
| 📈 | **Momentum** | Holds every stock whose 20-day average is above its 50-day average, split equally. |
| 🔄 | **Mean Reversion** | Buys stocks that fell hard (RSI below 30) and sells when they bounce (RSI above 55). Up to 4 positions of 25% each. |
| 🐒 | **Random Monkey** | Now and then picks 1–3 random stocks with random weights. Any strategy that can't beat it has no skill. |
| 🤖 | **Claude PM** | *Coming in Phase 6.* |

## How the backtest stays honest

- **No lookahead:** a bot decides after a day's close, sees only prices up to that day, and its orders fill at the **next day's open**. A test proves the engine never hands a bot future data.
- **Costs:** every trade pays slippage (5 bps by default) and an optional fee.
- **No shorting, no margin:** weights must be positive and add up to at most 100%.

## Risk manager

Bots only *propose* trades. Every proposal passes the risk manager first, which can shrink, drop or block it, but never make it bigger.

| Check | Rule |
|---|---|
| 🛑 Kill switch | `touch data/KILL` (optionally with a reason inside) or `ARENA_KILL_SWITCH=1`: nothing trades, not even sells |
| 💀 Drawdown breaker | A bot that falls 30% from its peak is **eliminated**: it sells everything and stays frozen |
| ⚖️ Position cap | Max 25% in a single stock; broad index funds (SPY, QQQ) may go to 100% |
| 🔢 Max positions | 6 holdings at most |
| ❓ Unknown symbols | Dropped |
| 🚫 Invalid orders | Shorting, margin or NaN weights are rejected and logged, and the arena keeps running |

Every action is logged as a risk event. `arena backtest --no-risk` turns it off for comparison, and `--max-drawdown 20` changes the elimination line.

## First results (Jan 2023 to Oct 2026, $1000 each)

With the risk manager on (the default):

| Bot | Final | Return | Sharpe | Max drawdown | Trades |
|---|---|---|---|---|---|
| 📈 Momentum | $2,416 | +142% | 1.36 | −17.5% | 313 |
| 🐒 Random Monkey | $2,162 | +116% | 1.27 | −15.5% | 292 |
| 🐢 **SPY Hodler** | **$2,126** | **+113%** | **1.43** | **−19%** | 1 |
| 🔄 Mean Reversion | $1,343 | +34% | 0.68 | −18% | 46 |

Without it (`--no-risk`):

| Bot | Final | Return | Sharpe | Max drawdown | Trades |
|---|---|---|---|---|---|
| 🐒 Random Monkey | $3,181 | +218% | 1.00 | −35% | 312 |
| 🐢 **SPY Hodler** | **$2,126** | **+113%** | **1.43** | **−19%** | 1 |
| 📈 Momentum | $2,062 | +106% | 0.99 | −31% | 361 |
| 🔄 Mean Reversion | $1,343 | +34% | 0.68 | −18% | 46 |

**The 25% cap made the bots better, not just safer.** It stops Momentum from piling into one or two stocks, so it ends with more money than SPY and nearly SPY's Sharpe. It also cuts the monkey's worst drop from −35% to −15.5%.

**Without limits, the monkey "wins", and that's the most useful result here.** Across 50 random seeds the monkey beats SPY in dollars 44 times, but on risk-adjusted return (Sharpe) only 12 times. The watchlist (NVDA, AAPL, MSFT, QQQ, TSLA) was picked in 2026, *knowing* these stocks had a huge run, so throwing darts at it mostly hits winners. That's **survivorship bias**, and it means beating SPY on this list proves very little. No rule-based bot beats SPY on risk-adjusted terms.

With a $1 fee per trade, Momentum drops from $2,062 to $1,610: at $1000, costs matter a lot.

### Known limitations

- **Hindsight watchlist** (see above) and a single 3.75-year, mostly bull-market sample. Strategy parameters aren't validated out of sample yet.
- **Sharpe and Sortino use a risk-free rate of 0.** T-bills paid ~4–5% in this period, so both are overstated.
- **Prices are adjusted for dividends,** so returns assume dividends were reinvested. A live bot would receive cash instead.
- **Fills** are at the next open with flat slippage, with no volume or liquidity limits. An order is dropped if its symbol has no price the next morning.

## Database

Runs, trades, equity curves and risk events can be stored in **PostgreSQL + TimescaleDB** (equity curves and price bars are hypertables).

```sh
docker compose up -d db          # local TimescaleDB, dev-only credentials
uv run arena db migrate          # create / update the schema
uv run arena backtest --save     # race the bots and store the run
uv run arena db runs             # recent runs and each bot's final equity
uv run arena db kill on --reason "market is on fire"   # stop all trading
uv run arena db kill off
```

The risk manager checks both kill switches (the database row and the local `data/KILL` file). If the database can't be read, it **fails closed** and halts trading.

## Development

```sh
uv run pytest                    # database tests run when DATABASE_URL is set (they do in CI)
uv run ruff check . && uv run ruff format .
```
