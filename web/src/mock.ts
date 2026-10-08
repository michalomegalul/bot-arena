// Offline sample data for `VITE_MOCK=1 npm run dev`, shaped exactly like the API.
import type {
  BotDetail,
  BotSummary,
  EquitySeries,
  Leaderboard,
  PricePoint,
  RiskEvent,
  Run,
  Trade,
} from "./types";

const RUNS: Run[] = [
  { id: 2, kind: "paper", topic: "arena.paper", start_date: "2026-10-08", end_date: null, started_at: "2026-10-08T09:11:05Z", bots: 4 },
  { id: 1, kind: "backtest", topic: null, start_date: "2023-01-03", end_date: "2026-10-07", started_at: "2026-10-08T08:50:00Z", bots: 4 },
];

const BOTS = [
  { id: 1, name: "SPY Hodler", emoji: "🐢", drift: 0.0008, vol: 0.009, bench: true },
  { id: 2, name: "Momentum", emoji: "📈", drift: 0.001, vol: 0.012, bench: false },
  { id: 3, name: "Mean Reversion", emoji: "🔄", drift: 0.0003, vol: 0.006, bench: false },
  { id: 4, name: "Random Monkey", emoji: "🐒", drift: 0.0009, vol: 0.016, bench: false },
];

function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

function tradingDays(start: string, end: string): string[] {
  const out: string[] = [];
  for (let d = new Date(`${start}T00:00:00Z`); d <= new Date(`${end}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 1)) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

const DAYS = tradingDays("2023-01-03", "2026-10-07");

const SERIES: EquitySeries[] = BOTS.map((b) => {
  const r = rng(b.id * 97);
  let v = 1000;
  return {
    bot_id: b.id,
    name: b.name,
    emoji: b.emoji,
    is_benchmark: b.bench,
    points: DAYS.map((t, i) => {
      if (i > 0) v *= 1 + b.drift + (r() - 0.5) * 2 * b.vol;
      return { t, v: Math.round(v * 100) / 100 };
    }),
  };
});

const SYMBOLS = ["AAPL", "MSFT", "NVDA", "QQQ", "SPY", "TSLA"];

const TRADES: Trade[] = (() => {
  const r = rng(7);
  const out: Trade[] = [];
  let id = 1;
  for (let i = 5; i < DAYS.length; i += 6) {
    const b = BOTS[1 + Math.floor(r() * 3)]!;
    const symbol = SYMBOLS[Math.floor(r() * SYMBOLS.length)]!;
    const price = 100 + r() * 300;
    const shares = Math.round(r() * 300) / 100;
    out.push({
      id: id++, bot_id: b.id, bot: b.name, emoji: b.emoji, t: DAYS[i]!, symbol,
      side: r() > 0.5 ? "buy" : "sell", shares, price, value: shares * price, fee: 0,
    });
  }
  out.push({ id: id++, bot_id: 1, bot: "SPY Hodler", emoji: "🐢", t: DAYS[1]!, symbol: "SPY", side: "buy", shares: 2.62, price: 381.2, value: 998.74, fee: 0 });
  return out.sort((a, b) => (a.t < b.t ? 1 : -1));
})();

const RISK: RiskEvent[] = [
  { id: 2, bot_id: 4, bot: "Random Monkey", emoji: "🐒", t: "2025-04-07", kind: "clipped", detail: "NVDA 61.0% -> 25.0%" },
  { id: 1, bot_id: 2, bot: "Momentum", emoji: "📈", t: "2024-08-05", kind: "clipped", detail: "TSLA 50.0% -> 25.0%" },
];

function stats(s: EquitySeries) {
  const v = s.points.map((p) => p.v);
  let peak = -Infinity;
  let dd = 0;
  for (const x of v) {
    peak = Math.max(peak, x);
    dd = Math.min(dd, x / peak - 1);
  }
  return { equity: v.at(-1) ?? null, ret: v.length ? v.at(-1)! / v[0]! - 1 : null, dd, spark: v.slice(-30) };
}

function summaries(runId: number): BotSummary[] {
  if (runId === 2) {
    return BOTS.map((b, i) => ({
      id: b.id + 10, name: b.name, emoji: b.emoji, status: "active", is_benchmark: b.bench, rank: i + 1,
      starting_cash: 1000, equity: null, total_return: null, max_drawdown: null, sharpe: null, sortino: null,
      exposure: null, trades: 0, sparkline: [],
    }));
  }
  return SERIES.map((s) => {
    const st = stats(s);
    return {
      id: s.bot_id, name: s.name, emoji: s.emoji, status: "active" as const, is_benchmark: s.is_benchmark, rank: 0,
      starting_cash: 1000, equity: st.equity, total_return: st.ret, max_drawdown: st.dd, sharpe: 1.1, sortino: 1.6,
      exposure: s.is_benchmark ? 1 : 0.8, trades: TRADES.filter((t) => t.bot_id === s.bot_id).length, sparkline: st.spark,
    };
  })
    .sort((a, b) => (b.equity ?? 0) - (a.equity ?? 0))
    .map((b, i) => ({ ...b, rank: i + 1 }));
}

const delay = <T,>(v: T): Promise<T> => new Promise((res) => setTimeout(() => res(structuredClone(v)), 120));
const run = (id: number) => RUNS.find((r) => r.id === id) ?? RUNS[1]!;

export const runs = () => delay(RUNS);
export const defaultRun = () => delay(RUNS[1]!);
export const leaderboard = (runId: number): Promise<Leaderboard> =>
  delay({ run: run(runId), as_of: runId === 2 ? null : DAYS.at(-1)!, bots: summaries(runId) });
export const equity = (runId: number) => delay(runId === 2 ? SERIES.map((s) => ({ ...s, bot_id: s.bot_id + 10, points: [] })) : SERIES);
export const trades = (runId: number, limit: number, botId?: number) =>
  delay(runId === 2 ? [] : TRADES.filter((t) => botId == null || t.bot_id === botId).slice(0, limit));
export const riskEvents = (runId: number, limit: number, botId?: number) =>
  delay(runId === 2 ? [] : RISK.filter((e) => botId == null || e.bot_id === botId).slice(0, limit));
export const bot = (runId: number, botId: number): Promise<BotDetail> => {
  const summary = summaries(runId).find((b) => b.id === botId) ?? summaries(runId)[0]!;
  return delay({
    summary,
    positions: [],
    trades: TRADES.filter((t) => t.bot_id === summary.id),
    risk_events: RISK.filter((e) => e.bot_id === summary.id),
  });
};
export const prices = (symbol: string): Promise<PricePoint[]> => {
  const r = rng(symbol.charCodeAt(0) * 31);
  let p = 100 + r() * 200;
  return delay(
    DAYS.map((t) => {
      const open = p;
      p *= 1 + (r() - 0.49) * 0.03;
      return { t, open: Math.round(open * 100) / 100, close: Math.round(p * 100) / 100 };
    }),
  );
};
