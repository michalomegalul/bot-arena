// Mirrors src/bot_arena/api/models.py exactly. Dates are "YYYY-MM-DD"; fractions stay fractions.

export type RunKind = "backtest" | "paper" | "live";

export interface Run {
  id: number;
  kind: RunKind;
  topic: string | null;
  start_date: string | null;
  end_date: string | null;
  started_at: string;
  bots: number;
}

export interface BotSummary {
  id: number;
  name: string;
  emoji: string;
  status: "active" | "eliminated";
  is_benchmark: boolean;
  rank: number;
  starting_cash: number;
  equity: number | null;
  total_return: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  sortino: number | null;
  exposure: number | null;
  trades: number;
  sparkline: number[];
}

export interface Leaderboard {
  run: Run;
  as_of: string | null;
  bots: BotSummary[];
}

export interface EquityPoint {
  t: string;
  v: number;
}

export interface EquitySeries {
  bot_id: number;
  name: string;
  emoji: string;
  is_benchmark: boolean;
  points: EquityPoint[];
}

export interface Trade {
  id: number;
  bot_id: number;
  bot: string;
  emoji: string;
  t: string;
  symbol: string;
  side: "buy" | "sell";
  shares: number;
  price: number;
  value: number;
  fee: number;
}

export interface RiskEvent {
  id: number;
  bot_id: number;
  bot: string;
  emoji: string;
  t: string;
  kind: string;
  detail: string;
}

export interface Position {
  symbol: string;
  shares: number;
  price: number | null;
  value: number | null;
  weight: number | null;
}

export interface BotDetail {
  summary: BotSummary;
  positions: Position[];
  trades: Trade[];
  risk_events: RiskEvent[];
}

export interface PricePoint {
  t: string;
  open: number;
  close: number;
}

export interface FeedMessage {
  type: "trade" | "risk" | "equity";
  trade?: Trade | null;
  risk?: RiskEvent | null;
  equity?: EquitySeries | null;
}
