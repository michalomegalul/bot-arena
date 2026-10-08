// Okabe–Ito palette: distinguishable with the common kinds of colour blindness.
// Yellow is left out because it disappears on the light theme.
const BY_NAME: Record<string, string> = {
  Momentum: "#56B4E9",
  "Mean Reversion": "#E69F00",
  "Random Monkey": "#CC79A7",
  "Claude PM": "#D55E00",
};
const FALLBACK = ["#009E73", "#0072B2", "#D55E00", "#56B4E9", "#E69F00", "#CC79A7"];

/** The benchmark is drawn in the text colour (dashed), so it reads as "the reference line". */
export function botColor(name: string, isBenchmark: boolean, index = 0): string {
  if (isBenchmark) return cssVar("--benchmark");
  return BY_NAME[name] ?? FALLBACK[index % FALLBACK.length] ?? "#56B4E9";
}

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
