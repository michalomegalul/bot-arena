# Bot Arena

Trading bots race from **$1000 each**: classic rule-based strategies, a random monkey, and Claude as a "portfolio manager", all trying to beat simply holding the S&P 500.

Runs on **paper money** (Alpaca paper trading). See [PLAN.md](PLAN.md) for the full design: a Redpanda streaming pipeline, a risk manager with a kill switch, and a live "arena" UI.

## Status

- [x] **Phase 1: Hello market.** Download daily prices and chart $1000 bought and held in each stock.
- [ ] Phase 2: Backtester and the first bots
- [ ] Phase 3: Database and risk manager
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
```

`arena fetch --start 2024-01-01` fetches a longer history.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format .
```
