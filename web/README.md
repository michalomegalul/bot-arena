# Bot Arena web UI

React + TypeScript + [Lightweight Charts](https://tradingview.github.io/lightweight-charts/), built with Vite.
In production FastAPI serves the built `dist/` together with `/api`, so the UI has no config.

Needs Node 22+.

```sh
npm ci
npm run dev                  # http://localhost:5173, proxies /api (and the WebSocket) to localhost:8000
VITE_MOCK=1 npm run dev      # no API needed: built-in sample data
npm run build                # type-check + production build into dist/
npm run lint                 # type-check only
node scripts/check-api.mjs http://localhost:8000   # check the real API against src/types.ts
```

Pages:

- `/` the arena: leaderboard, equity race chart (benchmark dashed), live trade feed. `?run=<id>` picks a run.
- `/bots/:runId/:botId` one bot: metrics, holdings, equity vs the benchmark, trades on the price chart, risk events.

The routes are client-side, so the server must answer any non-`/api` path with `index.html`.

`src/types.ts` mirrors `src/bot_arena/api/models.py`; change both together.
