import { Link } from "react-router-dom";
import { date, money, money0, qty } from "../format";
import type { RiskEvent, Trade } from "../types";

export type FeedItem = { kind: "trade"; trade: Trade } | { kind: "risk"; risk: RiskEvent };

export const itemKey = (i: FeedItem) => (i.kind === "trade" ? `t${i.trade.id}` : `r${i.risk.id}`);
const itemDate = (i: FeedItem) => (i.kind === "trade" ? i.trade.t : i.risk.t);

/** Newest first; on the same day risk events (e.g. an elimination) come before the trades they caused. */
export function mergeFeed(trades: Trade[], risk: RiskEvent[]): FeedItem[] {
  const items: FeedItem[] = [
    ...trades.map((trade) => ({ kind: "trade" as const, trade })),
    ...risk.map((r) => ({ kind: "risk" as const, risk: r })),
  ];
  return items.sort((a, b) => {
    const d = itemDate(b).localeCompare(itemDate(a));
    if (d) return d;
    if (a.kind !== b.kind) return a.kind === "risk" ? -1 : 1;
    return (b.kind === "trade" ? b.trade.id : b.risk.id) - (a.kind === "trade" ? a.trade.id : a.risk.id);
  });
}

const RISK_LABEL: Record<string, string> = {
  eliminated: "was eliminated",
  kill_switch: "kill switch",
  clipped: "was capped",
  dropped: "order dropped",
  rejected: "order rejected",
};

interface Props {
  items: FeedItem[];
  runId: number;
  fresh?: Set<string>;
  title?: string;
  limit?: number;
  showBot?: boolean;
}

export function Feed({ items, runId, fresh, title = "Trade feed", limit = 60, showBot = true }: Props) {
  return (
    <section className="card feed-card" aria-labelledby="feed-title">
      <h2 id="feed-title">{title}</h2>
      {items.length === 0 ? (
        <p className="muted">No trades yet.</p>
      ) : (
        <ol className="feed" aria-live="polite">
          {items.slice(0, limit).map((item) => {
            const key = itemKey(item);
            const isFresh = fresh?.has(key) ? " fresh" : "";
            if (item.kind === "trade") {
              const t = item.trade;
              return (
                <li key={key} className={`feed-item${isFresh}`}>
                  <time dateTime={t.t}>{date(t.t)}</time>
                  <p>
                    {showBot && <BotName runId={runId} id={t.bot_id} emoji={t.emoji} name={t.bot} />}
                    <span className={`side ${t.side}`}>{t.side === "buy" ? "bought" : "sold"}</span>{" "}
                    <span className="num">{qty(t.shares)}</span> × <strong>{t.symbol}</strong> @{" "}
                    <span className="num">{money(t.price)}</span>{" "}
                    <span className="muted num">({money0(t.value)})</span>
                  </p>
                </li>
              );
            }
            const r = item.risk;
            const loud = r.kind === "eliminated" || r.kind === "kill_switch";
            return (
              <li key={key} className={`feed-item risk${loud ? " loud" : ""}${isFresh}`}>
                <time dateTime={r.t}>{date(r.t)}</time>
                <p>
                  <span aria-hidden="true">{r.kind === "eliminated" ? "💀 " : r.kind === "kill_switch" ? "🛑 " : "⚖️ "}</span>
                  {showBot && <BotName runId={runId} id={r.bot_id} emoji={r.emoji} name={r.bot} />}
                  <strong>{RISK_LABEL[r.kind] ?? r.kind}</strong>
                  <span className="muted">: {r.detail}</span>
                </p>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function BotName({ runId, id, emoji, name }: { runId: number; id: number; emoji: string; name: string }) {
  return (
    <>
      <Link to={`/bots/${runId}/${id}`} className="bot-ref">
        <span aria-hidden="true">{emoji}</span> {name}
      </Link>{" "}
    </>
  );
}
