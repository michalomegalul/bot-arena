import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { date, percent, tone } from "../format";
import { useAsync } from "../hooks";
import type { JournalEntry } from "../types";
import { RunPicker } from "./Arena";
import { ErrorBox, Loading } from "./common";

/** What the AI bots decided, in their own words, and whether it worked. */
export function Journal() {
  const [params, setParams] = useSearchParams();
  const runParam = params.get("run");
  const botParam = params.get("bot");
  const runs = useAsync(api.runs, []);
  const fallback = useAsync(() => (runParam ? Promise.resolve(null) : api.defaultRun()), [runParam]);
  const runId = runParam ? Number(runParam) : fallback.data?.id;
  const entries = useAsync(
    () => (runId == null ? Promise.resolve([] as JournalEntry[]) : api.journal(runId)),
    [runId],
  );

  const bots = useMemo(() => {
    const seen = new Map<number, { id: number; name: string; emoji: string; model: string; n: number; wins: number }>();
    for (const e of entries.data ?? []) {
      const b = seen.get(e.bot_id) ?? { id: e.bot_id, name: e.bot, emoji: e.emoji, model: e.model, n: 0, wins: 0 };
      b.n += 1;
      if (e.outcome != null && e.benchmark_outcome != null && e.outcome - e.benchmark_outcome >= 0.0005) b.wins += 1;
      seen.set(e.bot_id, b);
    }
    return [...seen.values()];
  }, [entries.data]);

  const shown = (entries.data ?? []).filter((e) => !botParam || e.bot_id === Number(botParam));
  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "run") next.delete("bot");
    setParams(next);
  };

  if (fallback.error) return <ErrorBox error={fallback.error} />;
  if (runId == null || entries.loading) return <Loading />;
  if (entries.error) return <ErrorBox error={entries.error} />;

  const run = runs.data?.find((r) => r.id === runId);
  return (
    <>
      <section className="hero">
        <div>
          <h1>AI Journal</h1>
          <p className="lead muted">
            Every few days each AI bot reads a market briefing, picks its portfolio and explains why. Each entry shows
            how the bot did until its next decision, next to just holding SPY.
          </p>
        </div>
        {runs.data && run && <RunPicker runs={runs.data} value={runId} onChange={(id) => set("run", id)} />}
      </section>

      {bots.length === 0 ? (
        <p className="card empty">No AI decisions in this run. Pick a tournament run above.</p>
      ) : (
        <>
          <div className="journal-filter" role="group" aria-label="Filter by bot">
            <button className={!botParam ? "active" : ""} onClick={() => set("bot", null)}>
              All
            </button>
            {bots.map((b) => (
              <button
                key={b.id}
                className={botParam === String(b.id) ? "active" : ""}
                onClick={() => set("bot", String(b.id))}
                title={`${b.model}: beat SPY in ${b.wins} of ${b.n} decisions`}
              >
                {b.emoji} {b.name} <span className="muted small">{b.wins}/{b.n} beat SPY</span>
              </button>
            ))}
          </div>

          <ol className="journal">
            {shown.map((e) => (
              <Entry key={e.id} entry={e} runId={runId} />
            ))}
          </ol>
        </>
      )}
    </>
  );
}

function Entry({ entry: e, runId }: { entry: JournalEntry; runId: number }) {
  const held = e.targets && Object.keys(e.targets).length > 0;
  const cash = e.targets ? 1 - Object.values(e.targets).reduce((a, b) => a + b, 0) : null;
  // Within 0.05 percentage points counts as a tie: the displayed numbers would look identical.
  const diff = e.outcome != null && e.benchmark_outcome != null ? e.outcome - e.benchmark_outcome : null;
  const verdict = diff == null ? null : Math.abs(diff) < 0.0005 ? "➖" : diff > 0 ? "✅" : "❌";
  return (
    <li className="card journal-entry">
      <header>
        <Link to={`/bots/${runId}/${e.bot_id}`} className="journal-bot">
          <span aria-hidden="true">{e.emoji}</span> {e.bot}
        </Link>
        <time dateTime={e.t}>{date(e.t)}</time>
        {e.confidence != null && (
          <span className="confidence" title="How sure the model said it was">
            <span className="bar" style={{ width: `${Math.round(e.confidence * 100)}%` }} />
            <span className="small">confidence {Math.round(e.confidence * 100)}%</span>
          </span>
        )}
      </header>

      <div className="journal-targets">
        {e.targets == null ? (
          <span className="chip warn">answer unusable, held</span>
        ) : held ? (
          Object.entries(e.targets)
            .sort((a, b) => b[1] - a[1])
            .map(([s, w]) => (
              <span key={s} className="chip">
                {s} {Math.round(w * 100)}%
              </span>
            ))
        ) : null}
        {cash != null && cash > 0.005 && <span className="chip muted">cash {Math.round(cash * 100)}%</span>}
      </div>

      {e.reasoning && <blockquote>{e.reasoning}</blockquote>}

      {e.notes.length > 0 && (
        <ul className="journal-notes small muted" aria-label="Fixes applied to the answer">
          {e.notes.map((n) => (
            <li key={n}>⚠ {n}</li>
          ))}
        </ul>
      )}

      {e.outcome != null && (
        <footer className="small">
          {verdict} until {date(e.until)}: <span className={tone(e.outcome)}>{percent(e.outcome)}</span>
          <span className="muted">
            {" "}
            vs SPY <span className={tone(e.benchmark_outcome)}>{percent(e.benchmark_outcome)}</span>
          </span>
          {e.seconds != null && <span className="muted"> · answered in {e.seconds.toFixed(1)}s</span>}
        </footer>
      )}
    </li>
  );
}
