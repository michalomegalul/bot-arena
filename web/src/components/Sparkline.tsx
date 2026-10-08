interface Props {
  values: number[];
  color: string;
  baseline?: number;
  dashed?: boolean;
}

/** A tiny inline equity line. Decorative: the card shows the numbers as text. */
export function Sparkline({ values, color, baseline, dashed }: Props) {
  if (values.length < 2) return <svg className="spark" aria-hidden="true" />;
  const w = 120;
  const h = 32;
  // Scale to the values only: including the starting cash would flatten a 30-day window.
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo;
  const x = (i: number) => (i / (values.length - 1)) * w;
  // A flat line (e.g. a bot sitting in cash) goes through the middle.
  const y = (v: number) => (span ? h - 2 - ((v - lo) / span) * (h - 4) : h / 2);
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      {baseline !== undefined && baseline >= lo && baseline <= hi && (
        <line x1="0" x2={w} y1={y(baseline)} y2={y(baseline)} className="spark-base" />
      )}
      <path d={d} fill="none" stroke={color} strokeWidth="2" strokeDasharray={dashed ? "4 3" : undefined} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
