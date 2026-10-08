const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: "exceptZero",
});
const pctPlain = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 0 });
const num2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const shares = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });
const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

const dash = "—";

export const money = (v: number | null | undefined) => (v == null ? dash : usd.format(v));
export const money0 = (v: number | null | undefined) => (v == null ? dash : usd0.format(v));
export const percent = (v: number | null | undefined) => (v == null ? dash : pct.format(v));
export const percentPlain = (v: number | null | undefined) => (v == null ? dash : pctPlain.format(v));
export const ratio = (v: number | null | undefined) => (v == null ? dash : num2.format(v));
export const qty = (v: number) => shares.format(v);
export const date = (d: string | null | undefined) => (d ? dateFmt.format(new Date(`${d}T00:00:00Z`)) : dash);

export function tone(v: number | null | undefined): "up" | "down" | "flat" {
  if (v == null || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Time-axis labels: lone day numbers ("13") read badly, so days show as "Mar 13". */
export function tickMark(time: unknown, type: number): string | null {
  let parts: [number, number, number];
  if (typeof time === "string") {
    const [y = 0, m = 1, d = 1] = time.split("-").map(Number);
    parts = [y, m, d];
  } else if (typeof time === "number") {
    const date = new Date(time * 1000);
    parts = [date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate()];
  } else if (time && typeof time === "object" && "year" in time) {
    const t = time as { year: number; month: number; day: number };
    parts = [t.year, t.month, t.day];
  } else {
    return null;
  }
  const [y, m, d] = parts;
  const month = MONTHS[m - 1] ?? "";
  if (type === 0) return String(y); // year
  if (type === 1) return month; // month
  if (type === 2) return `${month} ${d}`; // day of month
  return null;
}
