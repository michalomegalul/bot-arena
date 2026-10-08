import type {
  BotDetail,
  EquitySeries,
  FeedMessage,
  JournalEntry,
  Leaderboard,
  PricePoint,
  RiskEvent,
  Run,
  Trade,
} from "./types";
import * as mock from "./mock";

const USE_MOCK = import.meta.env.VITE_MOCK === "1";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  runs: (): Promise<Run[]> => (USE_MOCK ? mock.runs() : get("/api/runs")),
  defaultRun: (): Promise<Run> => (USE_MOCK ? mock.defaultRun() : get("/api/runs/default")),
  leaderboard: (runId: number): Promise<Leaderboard> =>
    USE_MOCK ? mock.leaderboard(runId) : get(`/api/runs/${runId}/leaderboard`),
  equity: (runId: number): Promise<EquitySeries[]> =>
    USE_MOCK ? mock.equity(runId) : get(`/api/runs/${runId}/equity`),
  trades: (runId: number, limit = 100, botId?: number): Promise<Trade[]> =>
    USE_MOCK
      ? mock.trades(runId, limit, botId)
      : get(`/api/runs/${runId}/trades${query({ limit, bot_id: botId })}`),
  riskEvents: (runId: number, limit = 100, botId?: number): Promise<RiskEvent[]> =>
    USE_MOCK
      ? mock.riskEvents(runId, limit, botId)
      : get(`/api/runs/${runId}/risk-events${query({ limit, bot_id: botId })}`),
  bot: (runId: number, botId: number): Promise<BotDetail> =>
    USE_MOCK ? mock.bot(runId, botId) : get(`/api/runs/${runId}/bots/${botId}`),
  journal: (runId: number, botId?: number): Promise<JournalEntry[]> =>
    USE_MOCK ? Promise.resolve([]) : get(`/api/runs/${runId}/journal${query({ bot_id: botId })}`),
  prices: (symbol: string, start?: string | null, end?: string | null): Promise<PricePoint[]> =>
    USE_MOCK
      ? mock.prices(symbol)
      : get(`/api/prices/${encodeURIComponent(symbol)}${query({ start, end })}`),
};

/** Live updates for a run. Reconnects with backoff; gives up silently if the server has no feed. */
export function subscribeFeed(runId: number, onMessage: (msg: FeedMessage) => void): () => void {
  if (USE_MOCK) return () => {};
  let socket: WebSocket | null = null;
  let closed = false;
  let delay = 1000;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const connect = () => {
    if (closed) return;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${location.host}/api/runs/${runId}/feed`);
    socket.onopen = () => {
      delay = 1000;
    };
    socket.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data as string) as FeedMessage);
      } catch {
        /* ignore malformed messages */
      }
    };
    socket.onclose = () => {
      if (closed) return;
      timer = setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30_000);
    };
  };
  connect();

  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    socket?.close();
  };
}
