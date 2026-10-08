import {
  ColorType,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import { cssVar } from "../colors";
import { money, qty, tickMark } from "../format";
import { useColorScheme } from "../hooks";
import type { PricePoint, Trade } from "../types";

interface Props {
  symbol: string;
  prices: PricePoint[];
  trades: Trade[];
}

/** Closing prices of one symbol, with the bot's buys (▲) and sells (▼) marked. */
export function PriceChart({ symbol, prices, trades }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const scheme = useColorScheme();

  useEffect(() => {
    const node = el.current;
    if (!node) return;
    const chart = createChart(node, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: cssVar("--muted"),
        fontFamily: getComputedStyle(document.body).fontFamily,
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--grid") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.08 } }, // room for the top label
      timeScale: { borderVisible: false, minBarSpacing: 0.01, tickMarkFormatter: tickMark }, // ~1,000 days fit on a phone
      localization: { priceFormatter: (p: number) => money(p) },
    });
    const line = chart.addSeries(LineSeries, { color: cssVar("--accent"), lineWidth: 2, priceLineVisible: false });
    line.setData(prices.map((p) => ({ time: p.t as Time, value: p.close })));

    const known = new Set(prices.map((p) => p.t));
    const mine = trades.filter((t) => t.symbol === symbol && known.has(t.t)).sort((a, b) => a.t.localeCompare(b.t));
    // Share counts as labels only while they stay readable.
    const labels = mine.length <= 24;
    const markers: SeriesMarker<Time>[] = mine.map((t) => ({
        time: t.t as Time,
        position: t.side === "buy" ? "belowBar" : "aboveBar",
        shape: t.side === "buy" ? "arrowUp" : "arrowDown",
        color: cssVar(t.side === "buy" ? "--up" : "--down"),
        text: labels ? `${t.side === "buy" ? "B" : "S"} ${qty(t.shares)}` : undefined,
      }));
    createSeriesMarkers(line, markers);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [symbol, prices, trades, scheme]);

  const buys = trades.filter((t) => t.symbol === symbol && t.side === "buy").length;
  const sells = trades.filter((t) => t.symbol === symbol && t.side === "sell").length;
  return (
    <div
      ref={el}
      className="chart"
      role="img"
      aria-label={`${symbol} closing prices with ${buys} buys and ${sells} sells marked`}
    />
  );
}
