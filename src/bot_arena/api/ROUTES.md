# Bot Arena API (read-only)

All under `/api`. Interactive docs at `/api/docs` once running.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{"ok": true}` |
| GET | `/api/runs` | `Run[]`, newest first |
| GET | `/api/runs/default` | `Run`: the live paper run if it has data, else the newest backtest |
| GET | `/api/runs/{run_id}/leaderboard` | `Leaderboard` |
| GET | `/api/runs/{run_id}/equity` | `EquitySeries[]`, one per bot, oldest point first |
| GET | `/api/runs/{run_id}/trades?limit=100&bot_id=` | `Trade[]`, newest first |
| GET | `/api/runs/{run_id}/risk-events?limit=100&bot_id=` | `RiskEvent[]`, newest first |
| GET | `/api/runs/{run_id}/bots/{bot_id}` | `BotDetail` |
| GET | `/api/runs/{run_id}/journal?bot_id=` | `JournalEntry[]`, newest first: LLM decisions with their outcome |
| GET | `/api/prices/{symbol}?start=&end=` | `PricePoint[]`, oldest first |
| WS | `/api/runs/{run_id}/feed` | stream of `FeedMessage` (checked every 5 s) |

Errors: 404 `{"detail": "..."}` for an unknown run, bot or symbol.
There are no write endpoints: the kill switch and admin tools are deliberately not on the web.
