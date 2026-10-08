import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { Feed, mergeFeed } from "../components/Feed";
import { PriceChart } from "../components/PriceChart";
import { RaceChart } from "../components/RaceChart";
import { botColor } from "../colors";
import { date, money, percent, percentPlain, qty, ratio, tone } from "../format";
import { useAsync } from "../hooks";
import { ErrorBox, Loading } from "./common";

export function BotPage() {
  const { runId: runParam, botId: botParam } = useParams();
  const runId = Number(runParam);
  const botId = Number(botParam);

  const loaded = useAsync(
    () => Promise.all([api.bot(runId, botId), api.leaderboard(runId), api.equity(runId)]),
    [runId, botId],
  );
  const [symbol, setSymbol] = useState<string>();
  const [showAll, setShowAll] = useState(false);

  const detail = loaded.data?.[0];
  const board = loaded.data?.[1];

  // Symbols this bot traded or holds, most traded first.
  const symbols = useMemo(() => {
    if (!detail) return [];
    const counts = new Map<string, number>();
    for (const t of detail.trades) counts.set(t.symbol, (counts.get(t.symbol) ?? 0) + 1);
    for (const p of detail.positions) if (!counts.has(p.symbol)) counts.set(p.symbol, 0);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([s]) => s);
  }, [detail]);

  useEffect(() => {
    setSymbol(symbols[0]);
  }, [symbols]);

  const prices = useAsync(
    () => (symbol && board ? api.prices(symbol, board.run.start_date, board.as_of) : Promise.resolve([])),
    [symbol, board],
  );

  if (loaded.error) return <ErrorBox error={loaded.error} />;
  if (!loaded.data || !detail || !board) return <Loading />;

  const equity = loaded.data[2];
  const bot = detail.summary;
  const benchmark = equity.find((s) => s.is_benchmark);
  const mine = equity.filter((s) => s.bot_id === bot.id || (benchmark && s.bot_id === benchmark.bot_id));
  const colorIndex = new Map([...board.bots].sort((a, b) => a.id - b.id).map((b, i) => [b.id, i]));
  const color = botColor(bot.name, bot.is_benchmark, colorIndex.get(bot.id) ?? 0);
  const eliminated = bot.status === "eliminated";
  const trades = showAll ? detail.trades : detail.trades.slice(0, 25);

  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={`/?run=${runId}`}>← Arena</Link>
      </nav>

      <section className="bot-hero" style={{ "--bot": color } as CSSProperties}>
        <span className="emoji big" aria-hidden="true">
          {eliminated ? "💀" : bot.emoji}
        </span>
        <div>
          <h1>{bot.name}</h1>
          <div className="tags">
            <span className="tag">Rank #{bot.rank}</span>
            {bot.is_benchmark && <span className="tag tag-bench">Benchmark</span>}
            {eliminated ? <span className="tag tag-dead">Eliminated</span> : <span className="tag tag-live">Active</span>}
            <span className="tag">{board.run.kind === "backtest" ? `Backtest #${board.run.id}` : "Paper run"}</span>
          </div>
        </div>
        <div className="bot-hero-money">
          <span className="equity num">{money(bot.equity ?? bot.starting_cash)}</span>
          <span className={`ret num ${tone(bot.total_return)}`}>{percent(bot.total_return)}</span>
        </div>
      </section>

      <dl className="metrics card">
        <Metric label="Started with" value={money(bot.starting_cash)} />
        <Metric label="Max drawdown" value={percent(bot.max_drawdown)} />
        <Metric label="Sharpe" value={ratio(bot.sharpe)} />
        <Metric label="Sortino" value={ratio(bot.sortino)} />
        <Metric label="Invested" value={percentPlain(bot.exposure)} />
        <Metric label="Trades" value={String(bot.trades)} />
      </dl>

      {mine.some((s) => s.points.length > 0) && (
        <RaceChart
          series={mine}
          startingCash={bot.starting_cash}
          colorIndex={colorIndex}
          title={bot.is_benchmark ? "Equity" : "Equity vs the benchmark"}
        />
      )}

      {detail.positions.length > 0 && (
        <section className="card" aria-labelledby="pos-title">
          <h2 id="pos-title">Holdings</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Symbol</th>
                  <th scope="col" className="r">Shares</th>
                  <th scope="col" className="r">Price</th>
                  <th scope="col" className="r">Value</th>
                  <th scope="col" className="r">Weight</th>
                </tr>
              </thead>
              <tbody>
                {detail.positions.map((p) => (
                  <tr key={p.symbol}>
                    <th scope="row">{p.symbol}</th>
                    <td className="r num">{qty(p.shares)}</td>
                    <td className="r num">{money(p.price)}</td>
                    <td className="r num">{money(p.value)}</td>
                    <td className="r num">{percentPlain(p.weight)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {symbols.length > 0 && symbol && (
        <section className="card chart-card" aria-labelledby="price-title">
          <div className="chart-top">
            <div>
              <h2 id="price-title">Trades on the chart</h2>
              <p className="muted small">▲ buy · ▼ sell, at the next day's open</p>
            </div>
            <div className="seg" role="group" aria-label="Symbol">
              {symbols.map((s) => (
                <button key={s} type="button" aria-pressed={s === symbol} onClick={() => setSymbol(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
          {prices.error ? (
            <p className="muted">No price history for {symbol} in this run.</p>
          ) : prices.data && prices.data.length > 0 ? (
            <PriceChart symbol={symbol} prices={prices.data} trades={detail.trades} />
          ) : prices.loading ? (
            <Loading />
          ) : (
            <p className="muted">No price history for {symbol} in this run.</p>
          )}
        </section>
      )}

      <div className="split">
        <section className="card" aria-labelledby="hist-title">
          <h2 id="hist-title">Trade history</h2>
          {detail.trades.length === 0 ? (
            <p className="muted">No trades yet.</p>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col">Side</th>
                      <th scope="col">Symbol</th>
                      <th scope="col" className="r">Shares</th>
                      <th scope="col" className="r">Price</th>
                      <th scope="col" className="r">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={t.id}>
                        <td className="num nowrap">{date(t.t)}</td>
                        <td>
                          <span className={`side ${t.side}`}>{t.side}</span>
                        </td>
                        <th scope="row">{t.symbol}</th>
                        <td className="r num">{qty(t.shares)}</td>
                        <td className="r num">{money(t.price)}</td>
                        <td className="r num">{money(t.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {detail.trades.length > 25 && (
                <button type="button" className="link-btn" onClick={() => setShowAll((v) => !v)}>
                  {showAll ? "Show fewer" : `Show all ${detail.trades.length} trades`}
                </button>
              )}
            </>
          )}
        </section>
        <Feed
          items={mergeFeed([], detail.risk_events)}
          runId={runId}
          title="Risk manager"
          showBot={false}
          limit={200}
        />
      </div>
      <p className="muted small">Last updated {date(board.as_of)}.</p>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className="num">{value}</dd>
    </div>
  );
}
