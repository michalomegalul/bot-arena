import {
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { botColor, cssVar } from "../colors";
import { date, money, money0, tickMark } from "../format";
import { useColorScheme } from "../hooks";
import type { EquitySeries } from "../types";

export type Range = "1M" | "3M" | "1Y" | "ALL";
const RANGES: Range[] = ["1M", "3M", "1Y", "ALL"];
const MONTHS: Record<Exclude<Range, "ALL">, number> = { "1M": 1, "3M": 3, "1Y": 12 };

interface Props {
  series: EquitySeries[];
  startingCash: number;
  colorIndex?: Map<number, number>;
  title?: string;
  height?: number;
}

/** Every bot's equity on one chart, with the benchmark dashed and a $1,000 start line. */
export function RaceChart({ series, startingCash, colorIndex, title = "Equity race", height }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const scheme = useColorScheme();
  const [range, setRange] = useState<Range>("ALL");
  const rangeRef = useRef<Range>(range);
  rangeRef.current = range;
  const [hover, setHover] = useState<{ t: string; values: Map<number, number> } | null>(null);

  const lastDate = useMemo(() => {
    let last = "";
    for (const s of series) {
      const t = s.points.at(-1)?.t;
      if (t && t > last) last = t;
    }
    return last;
  }, [series]);

  const colors = useMemo(
    () => new Map(series.map((s, i) => [s.bot_id, botColor(s.name, s.is_benchmark, colorIndex?.get(s.bot_id) ?? i)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [series, colorIndex, scheme],
  );

  useEffect(() => {
    const node = el.current;
    if (!node) return;
    const text = cssVar("--muted");
    const grid = cssVar("--grid");
    const chart = createChart(node, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: text,
        fontFamily: getComputedStyle(document.body).fontFamily,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.08 } }, // room for the top label
      timeScale: { borderVisible: false, minBarSpacing: 0.01, tickMarkFormatter: tickMark }, // ~1,000 days fit on a phone
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { priceFormatter: (p: number) => money0(p) },
    });
    chartRef.current = chart;

    const bySeries = new Map<ISeriesApi<"Line">, number>();
    let first: ISeriesApi<"Line"> | null = null;
    // Benchmark last, so it is drawn on top of the others.
    const ordered = [...series].sort((a, b) => Number(a.is_benchmark) - Number(b.is_benchmark));
    for (const s of ordered) {
      const line = chart.addSeries(LineSeries, {
        color: colors.get(s.bot_id),
        lineWidth: 2,
        lineStyle: s.is_benchmark ? LineStyle.Dashed : LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerRadius: 4,
      });
      line.setData(s.points.map((p) => ({ time: p.t as Time, value: p.v })));
      bySeries.set(line, s.bot_id);
      first ??= line;
    }
    first?.createPriceLine({
      price: startingCash,
      color: text,
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: "start",
    });

    const onMove = (param: MouseEventParams<Time>) => {
      if (!param.time || !param.point) return setHover(null);
      const values = new Map<number, number>();
      for (const [line, botId] of bySeries) {
        const d = param.seriesData.get(line);
        if (d && "value" in d) values.set(botId, d.value);
      }
      setHover({ t: String(param.time), values });
    };
    chart.subscribeCrosshairMove(onMove);
    // autoSize measures the container asynchronously; fitting before that uses the wrong width.
    applyRange(chart, range, lastDate);
    const frame = requestAnimationFrame(() => applyRange(chart, range, lastDate));
    const resize = new ResizeObserver(() => applyRange(chart, rangeRef.current, lastDate));
    resize.observe(node);

    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
    };
    // Range changes are applied separately without rebuilding the chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, colors, startingCash, lastDate]);

  useEffect(() => {
    if (chartRef.current) applyRange(chartRef.current, range, lastDate);
  }, [range, lastDate]);

  const latest = (s: EquitySeries) => hover?.values.get(s.bot_id) ?? s.points.at(-1)?.v ?? null;
  const legendOrder = [...series].sort((a, b) => (latest(b) ?? 0) - (latest(a) ?? 0));
  const summary = legendOrder.map((s) => `${s.name} ${money(latest(s))}`).join(", ");

  return (
    <section className="card chart-card" aria-labelledby="race-title">
      <div className="chart-top">
        <div>
          <h2 id="race-title">{title}</h2>
          <p className="muted small">{hover ? date(hover.t) : `as of ${date(lastDate)}`}</p>
        </div>
        <div className="seg" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>
              {r}
            </button>
          ))}
        </div>
      </div>
      <ul className="legend">
        {legendOrder.map((s) => (
          <li key={s.bot_id}>
            <span
              className={`swatch${s.is_benchmark ? " dashed" : ""}`}
              style={{ color: colors.get(s.bot_id) }}
              aria-hidden="true"
            />
            <span aria-hidden="true">{s.emoji}</span> {s.name}
            <strong className="num">{money(latest(s))}</strong>
          </li>
        ))}
      </ul>
      <div
        ref={el}
        className="chart"
        style={height ? { height } : undefined}
        role="img"
        aria-label={`${title} chart. Latest values: ${summary}. Starting value ${money(startingCash)}.`}
      />
    </section>
  );
}

function applyRange(chart: IChartApi, range: Range, lastDate: string) {
  if (range === "ALL" || !lastDate) {
    chart.timeScale().fitContent();
    return;
  }
  const to = new Date(`${lastDate}T00:00:00Z`);
  const from = new Date(to);
  from.setUTCMonth(from.getUTCMonth() - MONTHS[range]);
  try {
    chart.timeScale().setVisibleRange({
      from: from.toISOString().slice(0, 10) as Time,
      to: lastDate as Time,
    });
  } catch {
    chart.timeScale().fitContent();
  }
}
