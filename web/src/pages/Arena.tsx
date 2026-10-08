import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, subscribeFeed } from "../api";
import { BotCard } from "../components/BotCard";
import { Feed, itemKey, mergeFeed, type FeedItem } from "../components/Feed";
import { RaceChart } from "../components/RaceChart";
import { botColor } from "../colors";
import { date, money0 } from "../format";
import { useAsync } from "../hooks";
import type { EquitySeries, Leaderboard, Run } from "../types";
import { ErrorBox, Loading } from "./common";

export function Arena() {
  const [params, setParams] = useSearchParams();
  const runParam = params.get("run");
  const runs = useAsync(api.runs, []);
  const fallback = useAsync(() => (runParam ? Promise.resolve(null) : api.defaultRun()), [runParam]);
  const runId = runParam ? Number(runParam) : fallback.data?.id;

  const loaded = useAsync(
    () =>
      runId == null
        ? Promise.resolve(undefined)
        : Promise.all([api.leaderboard(runId), api.equity(runId), api.trades(runId, 100), api.riskEvents(runId, 100)]),
    [runId],
  );

  const [board, setBoard] = useState<Leaderboard>();
  const [series, setSeries] = useState<EquitySeries[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!loaded.data) return;
    const [lb, eq, trades, risk] = loaded.data;
    setBoard(lb);
    setSeries(eq);
    setFeed(mergeFeed(trades, risk));
    setFresh(new Set());
  }, [loaded.data]);

  // Live updates: new trades, risk events and equity points as the recorder writes them.
  useEffect(() => {
    if (runId == null) return;
    return subscribeFeed(runId, (msg) => {
      if (msg.type === "trade" && msg.trade) {
        const item: FeedItem = { kind: "trade", trade: msg.trade };
        addItem(item);
      } else if (msg.type === "risk" && msg.risk) {
        addItem({ kind: "risk", risk: msg.risk });
      } else if (msg.type === "equity" && msg.equity) {
        const update = msg.equity;
        setSeries((prev) =>
          prev.map((s) => {
            if (s.bot_id !== update.bot_id) return s;
            const known = new Set(s.points.map((p) => p.t));
            return { ...s, points: [...s.points, ...update.points.filter((p) => !known.has(p.t))] };
          }),
        );
        api.leaderboard(runId).then(setBoard, () => {});
      }
    });

    function addItem(item: FeedItem) {
      const key = itemKey(item);
      setFeed((prev) => (prev.some((i) => itemKey(i) === key) ? prev : [item, ...prev]));
      setFresh((prev) => new Set(prev).add(key));
    }
  }, [runId]);

  const colorIndex = useMemo(
    () => new Map([...(board?.bots ?? [])].sort((a, b) => a.id - b.id).map((b, i) => [b.id, i])),
    [board],
  );

  const selectRun = (id: string) => setParams(id ? { run: id } : {});

  if (runs.error || fallback.error || loaded.error) return <ErrorBox error={runs.error ?? fallback.error ?? loaded.error} />;
  if (!board) return <Loading />;

  const run = board.run;
  const started = board.as_of != null;
  const startingCash = board.bots[0]?.starting_cash ?? 1000;

  return (
    <>
      <section className="hero">
        <div className="hero-text">
          <div className="hero-meta">
            <span className={`badge badge-${run.kind}`}>{run.kind === "paper" ? "● Paper · live" : run.kind}</span>
            <span className="muted small">
              {date(run.start_date)} – {run.end_date ? date(run.end_date) : "today"}
            </span>
          </div>
          <h1>Bot Arena</h1>
          <p className="lede">
            {board.bots.length} bots each started with {money0(startingCash)}.
            Can any of them beat just holding the S&amp;P&nbsp;500?
          </p>
        </div>
        <RunPicker runs={runs.data ?? [run]} value={run.id} onChange={selectRun} />
      </section>

      {!started && (
        <section className="card waiting" role="status">
          <span className="pulse" aria-hidden="true" />
          <div>
            <h2>Waiting for the first market close</h2>
            <p className="muted">
              The bots trade once a day. After the US market closes, the day's prices arrive, the bots decide, and their
              orders fill at the next day's open. Everything below updates live.
            </p>
          </div>
        </section>
      )}

      <section aria-labelledby="board-title">
        <div className="section-head">
          <h2 id="board-title">Leaderboard</h2>
          {started && <span className="muted small">as of {date(board.as_of)}</span>}
        </div>
        <ol className="cards">
          {board.bots.map((b) => (
            <BotCard
              key={b.id}
              bot={b}
              runId={run.id}
              started={started}
              color={botColor(b.name, b.is_benchmark, colorIndex.get(b.id) ?? 0)}
            />
          ))}
        </ol>
      </section>

      <div className="split">
        {started ? (
          <RaceChart series={series} startingCash={startingCash} colorIndex={colorIndex} />
        ) : (
          <section className="card chart-card empty-chart">
            <h2>Equity race</h2>
            <p className="muted">The race chart appears after the first close.</p>
          </section>
        )}
        <Feed items={feed} runId={run.id} fresh={fresh} />
      </div>
    </>
  );
}

export function RunPicker({ runs, value, onChange }: { runs: Run[]; value: number; onChange: (id: string) => void }) {
  const label = (r: Run) =>
    r.kind === "paper" || r.kind === "live"
      ? `${r.kind === "paper" ? "Paper run" : "Live run"} · since ${date(r.start_date)}`
      : `Backtest #${r.id} · ${date(r.start_date)} – ${date(r.end_date)}`;
  return (
    <label className="picker">
      <span className="muted small">Run</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {label(r)}
          </option>
        ))}
      </select>
    </label>
  );
}
