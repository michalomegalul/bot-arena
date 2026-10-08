# Bot Arena: project plan

> Working name. Alternatives in [Open questions](#open-questions).

## Pitch

Give the system **$1000 of paper money** and let several trading bots race to grow it: a few classic rule-based strategies, a buy-and-hold S&P 500 baseline, and **Claude as a "portfolio manager"** that reads summarized market data a few times a day, decides what to do, and writes down *why*. A live web UI shows the race: a leaderboard, equity curves, a trade feed, and Claude's trading journal. Under the hood is a real streaming data pipeline (Redpanda), a time-series database, a risk manager with a kill switch, and a deployment on the homelab.

**Honest note:** this runs on **paper money by default**. Most strategies, LLMs included, do not reliably beat buy-and-hold after costs, so the SPY baseline is part of the leaderboard on purpose. If a bot loses to it, that's a valid result to show, not a failure. Real money stays optional, small, and behind a hard kill switch, and only after months of paper results.

---

## Verified facts (checked 2026-10-08)

| Topic | Fact | Source |
|---|---|---|
| Alpaca paper trading | Free; "anyone globally can create an Alpaca Paper Only Account" with just an email. Endpoint `https://paper-api.alpaca.markets` | docs.alpaca.markets/docs/paper-trading |
| Paper balance | Starts at **$100,000**; it "cannot change the account balance after it is created, unless you reset it" | same |
| Paper realism | No dividends or fees simulated, no market impact or slippage; ~10% random partial fills; can fill beyond real liquidity | same |
| Market data (free "Basic") | Real-time **IEX only** (one exchange, a small share of volume); SIP history only older than the **latest 15 min**; **200 API calls/min**; WebSocket **30 symbols** | docs.alpaca.markets/docs/about-market-data-api |
| Market data (paid) | Algo Trader Plus, **$99/month**: all US exchanges, 10,000 calls/min, unlimited symbols. *Not needed for this project.* | same |
| Crypto | Trades **24/7**, fractional (BTC min 0.0001), supported in paper. Eligibility: "select international jurisdictions and some U.S. jurisdictions" | docs.alpaca.markets/docs/crypto-trading |
| Redpanda | Official single-broker + Redpanda Console docker-compose; dev flags `--mode dev-container --smp 1` | docs.redpanda.com/redpanda-labs/docker-compose/single-broker/ |
| Claude pricing (per 1M tokens, in/out) | Haiku 4.5 **$1 / $5** · Sonnet 5 **$2 / $10** · Opus 5 **$5 / $25**. Cache reads ~0.1x input, 5-min cache writes 1.25x. Batch API **50% off**, stacks with caching. | Anthropic API skill reference (cached 2026-06-24) |

**Not verified, so check before relying on it:**
- Whether **Czech residents** can trade crypto on Alpaca. (Paper-only accounts are global, but crypto eligibility is region-dependent.)
- Whether a paper account can be **reset to exactly $1000**. This doesn't matter much: the design below keeps its own $1000 ledger per bot anyway.
- Whether crypto real-time data is free on the Basic plan. The docs don't say clearly.
- Redpanda dev-container RAM needs. Plan for ~1–2 GB and measure.
- Current Claude prices. Re-check the pricing page before Phase 6.

---

## Key design decision: one ledger per bot

Alpaca gives you **one** paper account with $100k, but the arena needs **N bots × $1000**. So:

- Each bot gets its own **internal virtual ledger** of cash, positions and trades, stored in Postgres.
- Fills are simulated from real market prices, with a configurable slippage and fee model so results aren't flattering.
- *Optionally* one "champion" bot also mirrors its orders to the real Alpaca paper account, which proves the broker integration works end to end.

Testing becomes easier too: the same `Broker` interface has a `SimBroker` (backtests and the arena) and an `AlpacaPaperBroker`.

---

## Architecture

```
                          ┌──────────────────────── homelab (Proxmox LXC, docker compose) ─────────────────────────┐
                          │                                                                                         │
 Alpaca market data ──►  [ingest]  ──► topic: bars.1m ──┬──► [strategy: momentum]      ─┐                           │
 (WebSocket IEX / crypto)   │                           ├──► [strategy: mean-revert]   ─┤                           │
 Alpaca historical REST ────┘                           ├──► [strategy: buy&hold SPY]  ─┼─► topic: signals          │
 News / headlines (later) ──► [news ingest] ──► topic: news                             │                           │
                                                        └──► [summarizer] ──► [Claude PM] ─┘   (few times / day)      │
                                                                                         │                           │
                                                                                         ▼                           │
                                                                   [risk manager] ── rejects: limits, drawdown,      │
                                                                         │            kill switch                    │
                                                                         ▼                                           │
                                                          topic: orders ─► [broker] ─► SimBroker (per-bot ledger)    │
                                                                                   └─► AlpacaPaperBroker (optional)  │
                                                                         │                                           │
                                                          topic: fills ──┴──► [recorder] ──► Postgres + TimescaleDB  │
                                                                                                 │                   │
                                                                                   [API: FastAPI] ◄┘                 │
                                                                                     │  REST + WebSocket             │
                                                                                     ▼                               │
                                                                               [UI: React] ──► cloudflared ──► web   │
                          └─────────────────────────────────────────────────────────────────────────────────────────┘
```

**Redpanda topics:** `bars.1m`, `news`, `signals`, `orders`, `fills`, `equity` (snapshots per bot), `events` (kill switch, errors).

Why a stream at all, when one Python script could do this? Because it's the learning goal. Each bot is an independent consumer, you can replay history through the same code path, and adding a bot means adding a consumer, not editing a monolith. It's also exactly the architecture you'd talk through in an interview.

---

## The bots (v1 roster)

| Bot | Logic | Why it's in the arena |
|---|---|---|
| **SPY Hodler** | Buy SPY on day 1 and never sell | The benchmark everyone has to beat |
| **Momentum** | e.g. 20/50-day moving-average crossover on a small watchlist | Classic trend-following |
| **Mean Reversion** | e.g. buy when RSI < 30 or price is far below its Bollinger band, sell on reversion | The opposite bet to momentum |
| **Random Monkey** | Random buys and sells under the same risk limits | Funny, and a serious sanity check: anything that can't beat the monkey isn't skill |
| **Claude PM** | 2–3 times per trading day, gets a compact summary (prices, indicators, its portfolio, recent news) and returns structured decisions plus reasoning | The headline feature |

**How Claude PM works:**
- **Input:** a summary, never raw tick data. Watchlist with % changes, a few indicators, current positions and P&L, its own last few journal entries, and top headlines.
- **Output:** **structured JSON** (Claude API structured outputs): `[{symbol, action: buy|sell|hold, size_pct, confidence, reasoning}]` plus a short `journal_entry`.
- Its decisions go through the **same risk manager** as every other bot. Claude never touches the broker directly.
- Every prompt and response is stored, so the UI can show "what Claude saw and why it acted".

---

## Risk manager (non-negotiable, built before any bot trades)

- Max position size per symbol (e.g. 25% of bot equity), max number of positions, no shorting or margin in v1.
- **Max drawdown breaker:** if a bot drops X% (e.g. 30%) from its peak, it's frozen and shown as "eliminated" in the UI.
- **Global kill switch:** a single flag (env var, DB row and a UI button) that stops all order flow immediately. Test it.
- Sanity checks: reject orders for unknown symbols, outside market hours (stocks), or above an order-size cap.
- Before real money ever happens: an order-count cap per day, plus a dollar cap enforced *outside* the bot logic.

---

## Backtesting (before any live paper trading)

- **Replay historical bars through Redpanda** into the same strategy code. One code path for backtest and live is the main payoff of the stream design.
- **Avoid lookahead bias:**
  - A strategy at time *t* only sees data up to *t*.
  - Fills happen at the *next* bar's open, not the bar the signal came from.
  - Indicators are computed incrementally.
  - Don't pick the watchlist using future knowledge, like "the stocks that went up in 2025". This is called survivorship bias.
- Model costs: slippage (e.g. 5–10 bps) and a fee per trade, even though paper is free.
- **Metrics:** total return vs SPY, CAGR, **Sharpe ratio**, Sortino, **max drawdown**, win rate, number of trades, exposure %.
- **Claude in backtests:** costs real money per decision and can "remember" history (a form of lookahead). So backtest Claude only on a short, recent window that's labeled clearly, or judge it on forward paper trading only. Write that limitation in the README; it makes the project look more credible.

---

## The UI: "the arena"

**Main screen:** a race.
- **Leaderboard cards**, one per bot: avatar/emoji, current equity, % return, rank change, a sparkline, and a status badge (active / frozen / eliminated).
- **One big chart:** every bot's equity curve on shared axes starting from $1000, with the SPY baseline as a dashed line. Range buttons: 1D / 1W / 1M / ALL.
- **Live trade feed** (WebSocket): "🐒 Monkey bought 3 × NVDA @ 131.20", with the newest at the top.

**Bot detail page:** positions, trade history, a per-bot metrics table (Sharpe, drawdown), and a price chart with buy/sell markers.

**"Claude's Journal" page:** one card per day with the trades Claude made, its reasoning *as written*, its confidence, and later the outcome ("✅ +4.1% since" / "❌ −2.3% since"). This is the most shareable screen, so give it the most design attention.

**Extras for later:** an ntfy push when a bot is eliminated or makes a big move. A "season" reset each month with a hall of fame. A read-only public demo.

**Stack:**
- **Frontend: React + Vite.** You already use them in `homelab-dashboard`, so the learning effort goes into new things, not a new framework. Charts with **TradingView Lightweight Charts** (`lightweight-charts`): fast, built for finance, and supports candles, markers and multiple line series.
- **Backend API: FastAPI (Python).** It shares models and code with the strategy and recording services, has native WebSocket support for the live feed, and generates OpenAPI docs automatically.
- Not Rust for the API: one language for the whole trading side keeps this project finishable. Your Rust learning has its own home in the DNS project. **Stretch goal:** rewrite the `ingest` service in Rust later (`rdkafka` / `tokio-tungstenite`). It's a small, well-defined service, and a polyglot pipeline is a good resume line.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language (trading side) | **Python 3.12+** | Best libraries for data and finance, the official Alpaca SDK (`alpaca-py`), and the official Anthropic SDK |
| Streaming | **Redpanda** (single broker) + Redpanda Console | Kafka API without the JVM or ZooKeeper; Console lets you watch messages flow, which helps a lot for learning |
| Kafka client | `confluent-kafka` (Python) | Mature, fast, and the standard choice |
| Storage | **PostgreSQL + TimescaleDB** extension | You already run Postgres (LXC 112). Hypertables handle the price and equity time series, and normal tables hold ledgers and trades. Prefer it over ClickHouse: one database, and SQL you already know |
| Indicators / backtest math | `pandas`, `numpy` (maybe `pandas-ta`) | Standard tools |
| LLM | Anthropic API, structured outputs | See cost section |
| API | FastAPI + Uvicorn | See above |
| UI | React + Vite + Lightweight Charts | See above |
| Monitoring | **Grafana + Prometheus** (already on LXC 113) | Pipeline health: consumer lag, errors, Claude spend |
| Alerts | **ntfy** (already on LXC 116) | Kill switch triggered, bot eliminated, daily summary |
| Packaging | Docker Compose | One `docker compose up` for the whole stack, locally and on the homelab |
| CI | GitHub Actions (+ your self-hosted runner for deploys) | Lint, tests and build on every push |

---

## Claude cost control

Rules:
1. **Few calls.** Claude PM decides **2–3 times per trading day**, never per tick. The rule bots handle the high-frequency work.
2. **Summaries in, not raw data.** Keep each request around 5–10K input tokens.
3. **Structured output with a capped `max_tokens`.** No essays; the reasoning field is a few sentences.
4. **Batch API (50% off)** for anything nobody waits on: the end-of-day journal, the weekly review, and backtest runs.
5. **Prompt caching won't help much here.** The default cache lives ~5 minutes, and calls are hours apart. Only use it if you add multi-step tool loops within one decision.
6. **Hard limits:** set a monthly spend limit in the Anthropic Console, plus an app-side budget counter (stored in the DB and shown in the UI) that switches Claude PM to "hold" when it's exceeded.
7. Log `usage` from every response so actual cost is tracked, not guessed.

**Estimate** (3 decisions/day × ~21 trading days ≈ 63 calls/month, ~8K input + ~3K output each, with output padded for reasoning):

| Model | Input cost | Output cost | ≈ / month |
|---|---|---|---|
| Haiku 4.5 ($1/$5) | 504K × $1 = $0.50 | 189K × $5 = $0.95 | **~$1.50** |
| Sonnet 5 ($2/$10) | $1.01 | $1.89 | **~$3** |
| Opus 5 ($5/$25) | $2.52 | $4.73 | **~$7.50** |

Plus a daily journal via Batch (~21 calls × ~10K in / 1K out): **under $0.50/month** on any of these models.

Crypto (24/7) at 6 decisions/day ≈ 180 calls/month is roughly **3×** the numbers above.

**Recommendation:** it's cheap either way, so choosing the model is your call. A fun option is to make the **model itself a variable**: run "Claude PM (Haiku)" and "Claude PM (Opus)" as separate bots and let the leaderboard answer whether the bigger model trades better. That makes a great README chart.

---

## Milestones

Rough sizes are in weekends (WE). Every phase ends with something that runs and is committed.

**Phase 1: Hello market (1 WE).** *Learn: APIs, keys, time series.*
- Alpaca paper account, `.env`, and a script that pulls daily bars for SPY + 5 tickers into a CSV/Parquet file.
- A plain matplotlib chart of "$1000 in SPY since Jan 1" vs one other ticker.
- Repo scaffold with a README, `.gitignore` (including `.env`), and `pyproject.toml`.

**Phase 2: Backtester + first bots (1–2 WE).** *Learn: pandas, lookahead bias, metrics.*
- An in-memory backtester with the `Strategy` and `Broker` interfaces and `SimBroker` with slippage and fees.
- Bots: SPY Hodler, Momentum, Mean Reversion, Random Monkey.
- Metrics module (Sharpe, max drawdown, ...) with **unit tests**, plus a backtest report (table + chart).

**Phase 3: Postgres/Timescale + risk manager (1 WE).** *Learn: schema design, hypertables, defensive code.*
- Tables: `bots`, `ledgers`, `positions`, `trades`, `equity_snapshots` (hypertable), `bars` (hypertable).
- The risk manager and kill switch, with tests that prove bad orders get rejected.

**Phase 4: Streaming pipeline (2 WE).** *Learn: Kafka concepts (topics, partitions, consumer groups, offsets).*
- Redpanda + Console in docker compose.
- `ingest` (Alpaca WebSocket → `bars.1m`), each bot as a consumer, `orders`/`fills` topics, and the `recorder`.
- **Replay mode:** push historical bars through the same pipeline, so backtest and live share the code path.
- Live **paper** trading during market hours (or crypto 24/7).

**Phase 5: API + arena UI (2 WE).** *Learn: FastAPI, WebSockets, React data viz.*
- REST endpoints for bots, equity and trades, plus a WebSocket for the live feed.
- Leaderboard, multi-bot equity chart, trade feed and bot detail page.

**Phase 6: Claude PM (1–2 WE).** *Learn: LLM integration, structured output, prompt design, evaluating a non-deterministic component.*
- Summarizer, the Claude PM bot with JSON decisions, the budget guard, and the journal (Batch API).
- The "Claude's Journal" UI page, with every prompt and response stored for transparency.

**Phase 7: Deploy to homelab (1 WE).** *Learn: ops.*
- See the deployment section. Grafana dashboard, ntfy alerts, and a read-only public demo via Cloudflare Tunnel.

**Phase 8: Polish for resume (1 WE).**
- README with GIF, architecture diagram, results section, and CI badges. Write a blog post or long README section: "What I learned when Claude played the stock market for a month".

**Stretch ideas:** a Rust `ingest` rewrite · a news sentiment feed · options strategies · monthly "seasons" · let users submit their own strategy file as a new bot.

---

## Deployment (homelab)

- **New LXC** on the Proxmox node (e.g. `stock-bot`, Debian, Docker inside, 4 GB RAM / 2–4 cores to start). Or reuse the docker LXC 106, but a dedicated CT keeps backups and resources clean.
- `docker compose` stack: redpanda, redpanda-console, ingest, bots, risk, broker, recorder, api, ui (nginx).
- **Database:** either add the TimescaleDB extension to the existing Postgres (LXC 112) or run `timescale/timescaledb` in the stack. The second is simpler and isolated; the first is less to run.
- **Public read-only demo:** expose only the UI and read-only API through the existing **cloudflared** tunnel (e.g. `arena.dobsinsky.dev`). Redpanda Console, the kill switch and admin endpoints stay **LAN/Tailscale-only**.
- Already covered by your weekly vzdump backups. Add Uptime Kuma checks for the API and ingest freshness ("last bar < 5 min old").
- **CI/CD:** GitHub Actions runs tests on push, and the self-hosted runner deploys `main` (as you already do for `sites`).

**Secrets:**
- All keys in `.env`: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `APCA_API_BASE_URL`, `ANTHROPIC_API_KEY`, `DATABASE_URL`.
- `.env` is in `.gitignore` from the very first commit. Commit only a `.env.example` with dummy values.
- Add a **secret scanner** (e.g. gitleaks as a pre-commit hook and in CI). A leaked broker key in a public repo gets abused quickly.
- Use paper keys only. If real money ever happens, live keys live only on the server, never on the laptop or in CI.

---

## What makes it resume-worthy

- **README that sells it in 10 seconds:** a GIF of the arena racing, one sentence, the architecture diagram, and a "results so far" table vs SPY.
- **Real engineering, not a notebook:** event streaming, a clean `Strategy`/`Broker` design, a risk layer, and tests (metrics, risk rules, backtest determinism).
- **CI:** lint (ruff), type checks (mypy), tests (pytest), and a frontend build. Badges in the README.
- **Live read-only demo URL** on your domain.
- **Honest write-up:** what worked, what didn't, why lookahead bias matters, and how Claude PM did vs the monkey. Interviewers trust honest results more than "my bot made 400%".
- **Talking points:** "why Redpanda over a cron job", "how I prevent lookahead bias", "how I bound LLM cost and risk".

---

## Open questions

1. **Stocks, crypto, or both?** Stocks: more realistic, but only active ~6.5 h on weekdays (evening in CZ). Crypto: 24/7, so the arena is always moving, but your region's eligibility needs checking and the market is noisier. *Suggestion:* stocks for the main arena, crypto as a second arena once the pipeline works.
2. **Project name?** "Bot Arena", "Paper Hands", "Monkey vs Claude", "Thousand to ???"
3. **Which Claude model(s)** for the PM? Or run two and race them (see the cost section)?
4. **Watchlist:** a fixed set (e.g. SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMD, plus a couple of ETFs) vs letting Claude choose from a larger set. Note the free plan's 30-symbol WebSocket limit.
5. **Public repo from day 1?** Recommended: progress shows up on your profile as you go.
6. **News source** for Claude's context, and is it free? Decide in Phase 6.
7. **Live account status (2026-10-08):** paper account works from CZ. CZ is selectable in the live application (https://app.alpaca.markets/brokerage/new-account), but it is not submitted yet and KYC is pending. Finish it near Phase 7.
8. Real money, ever? If yes, set the rules now (amount, kill-switch criteria) while you're not attached to the outcome.
