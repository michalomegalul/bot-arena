// Checks every endpoint the UI uses against the shapes in src/types.ts.
// Usage: node scripts/check-api.mjs [http://localhost:8000]
const BASE = process.argv[2] ?? "http://localhost:8000";

const str = (v) => typeof v === "string";
const num = (v) => typeof v === "number" && Number.isFinite(v);
const nul = (f) => (v) => v === null || f(v);
const oneOf = (...xs) => (v) => xs.includes(v);
const arr = (f) => (v) => Array.isArray(v) && v.every(f);
const isDate = (v) => str(v) && /^\d{4}-\d{2}-\d{2}$/.test(v);

const shapes = {
  Run: { id: num, kind: oneOf("backtest", "paper", "live"), topic: nul(str), start_date: nul(isDate), end_date: nul(isDate), started_at: str, bots: num },
  BotSummary: {
    id: num, name: str, emoji: str, status: oneOf("active", "eliminated"), is_benchmark: (v) => typeof v === "boolean",
    rank: num, starting_cash: num, equity: nul(num), total_return: nul(num), max_drawdown: nul(num), sharpe: nul(num),
    sortino: nul(num), exposure: nul(num), trades: num, sparkline: arr(num),
  },
  EquityPoint: { t: isDate, v: num },
  Trade: { id: num, bot_id: num, bot: str, emoji: str, t: isDate, symbol: str, side: oneOf("buy", "sell"), shares: num, price: num, value: num, fee: num },
  RiskEvent: { id: num, bot_id: num, bot: str, emoji: str, t: isDate, kind: str, detail: str },
  Position: { symbol: str, shares: num, price: nul(num), value: nul(num), weight: nul(num) },
  PricePoint: { t: isDate, open: num, close: num },
};
shapes.EquitySeries = { bot_id: num, name: str, emoji: str, is_benchmark: (v) => typeof v === "boolean", points: (v) => Array.isArray(v) && v.every((p) => ok(p, "EquityPoint", "points[]")) };
shapes.Leaderboard = { run: (v) => ok(v, "Run", "run"), as_of: nul(isDate), bots: (v) => Array.isArray(v) && v.every((b) => ok(b, "BotSummary", "bots[]")) };
shapes.BotDetail = {
  summary: (v) => ok(v, "BotSummary", "summary"),
  positions: (v) => Array.isArray(v) && v.every((x) => ok(x, "Position", "positions[]")),
  trades: (v) => Array.isArray(v) && v.every((x) => ok(x, "Trade", "trades[]")),
  risk_events: (v) => Array.isArray(v) && v.every((x) => ok(x, "RiskEvent", "risk_events[]")),
};

const problems = [];
function ok(value, shape, where) {
  if (value === null || typeof value !== "object") {
    problems.push(`${where}: expected ${shape} object, got ${JSON.stringify(value)?.slice(0, 80)}`);
    return false;
  }
  const spec = shapes[shape];
  let good = true;
  for (const [k, check] of Object.entries(spec)) {
    if (!(k in value)) {
      problems.push(`${where}.${k}: missing (${shape})`);
      good = false;
    } else if (!check(value[k])) {
      problems.push(`${where}.${k}: unexpected ${JSON.stringify(value[k])?.slice(0, 80)} (${shape})`);
      good = false;
    }
  }
  for (const k of Object.keys(value)) if (!(k in spec)) problems.push(`${where}.${k}: extra field not in types.ts (${shape})`);
  return good;
}

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`);
  return res.json();
}

const listOf = (shape) => (v, where) => Array.isArray(v) ? v.every((x, i) => ok(x, shape, `${where}[${i}]`)) : (problems.push(`${where}: not an array`), false);

const health = await get("/api/health");
if (health?.ok !== true) problems.push(`/api/health: ${JSON.stringify(health)}`);
const runs = await get("/api/runs");
listOf("Run")(runs, "/api/runs");
const def = await get("/api/runs/default");
ok(def, "Run", "/api/runs/default");

let checked = 0;
for (const run of runs) {
  const lb = await get(`/api/runs/${run.id}/leaderboard`);
  ok(lb, "Leaderboard", `leaderboard(${run.id})`);
  const eq = await get(`/api/runs/${run.id}/equity`);
  listOf("EquitySeries")(eq, `equity(${run.id})`);
  const trades = await get(`/api/runs/${run.id}/trades?limit=100`);
  listOf("Trade")(trades, `trades(${run.id})`);
  if (trades.length > 1 && trades[0].t < trades.at(-1).t) problems.push(`trades(${run.id}): not newest first`);
  const risk = await get(`/api/runs/${run.id}/risk-events?limit=100`);
  listOf("RiskEvent")(risk, `risk-events(${run.id})`);
  for (const bot of lb.bots ?? []) {
    const d = await get(`/api/runs/${run.id}/bots/${bot.id}`);
    ok(d, "BotDetail", `bot(${run.id},${bot.id})`);
    const filtered = await get(`/api/runs/${run.id}/trades?limit=5&bot_id=${bot.id}`);
    if (filtered.some((t) => t.bot_id !== bot.id)) problems.push(`trades bot_id filter ignored (run ${run.id})`);
    const sym = d.trades?.[0]?.symbol;
    if (sym) {
      const prices = await get(`/api/prices/${sym}?start=${lb.run.start_date}&end=${lb.as_of ?? ""}`).catch((e) => (problems.push(String(e)), []));
      listOf("PricePoint")(prices, `prices(${sym})`);
      if (prices.length > 1 && prices[0].t > prices.at(-1).t) problems.push(`prices(${sym}): not oldest first`);
    }
    checked++;
  }
  // Ranks must be 1..n in order.
  const ranks = (lb.bots ?? []).map((b) => b.rank);
  if (ranks.some((r, i) => r !== i + 1)) problems.push(`leaderboard(${run.id}): ranks ${ranks} not 1..n in order`);
  const nb = (lb.bots ?? []).filter((b) => b.is_benchmark).length;
  if (nb !== 1) problems.push(`leaderboard(${run.id}): ${nb} benchmark bots`);
}
const missing = await fetch(`${BASE}/api/runs/999999/leaderboard`);
if (missing.status !== 404) problems.push(`unknown run: expected 404, got ${missing.status}`);

// The live feed must accept a WebSocket connection (messages only arrive when new rows are recorded).
const wsUrl = BASE.replace(/^http/, "ws") + `/api/runs/${def.id}/feed`;
const opened = await new Promise((resolve) => {
  const ws = new WebSocket(wsUrl);
  const t = setTimeout(() => (ws.close(), resolve(false)), 3000);
  ws.onopen = () => (clearTimeout(t), ws.close(), resolve(true));
  ws.onerror = () => (clearTimeout(t), resolve(false));
});
if (!opened) problems.push(`WebSocket ${wsUrl} did not open`);

console.log(`${runs.length} runs, ${checked} bot pages checked against ${BASE}`);
if (problems.length) {
  console.log(`${problems.length} problem(s):`);
  for (const p of [...new Set(problems)].slice(0, 50)) console.log("  - " + p);
  process.exit(1);
}
console.log("All responses match src/types.ts");
