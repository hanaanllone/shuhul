// Number formatting shared by every page.

const EMPTY = "—";

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;

  return value.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function withUnit(value: number | null | undefined, unit: string, digits = 0): string {
  const text = num(value, digits);
  return text === EMPTY ? text : `${text} ${unit}`;
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return EMPTY;
  return `${value > 0 ? "+" : ""}${num(value, digits)}`;
}

// Square metres as hectares once the number gets large.
export function area(value: number | null | undefined): string {
  if (value === null || value === undefined) return EMPTY;
  return value >= 10000 ? `${num(value / 10000, 2)} ha` : `${num(value)} m²`;
}

export function day(value: string | null | undefined): string {
  if (!value) return EMPTY;

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);

  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

// "Route A — Shortest" -> { letter: "A", label: "Shortest" }
export function routeParts(name: string): { letter: string; label: string } {
  const match = name.match(/Route\s+([A-Z])\s*[—-]\s*(.*)/);
  return match ? { letter: match[1], label: match[2] } : { letter: name.slice(0, 1), label: name };
}

export const ROUTE_COLORS: Record<string, string> = {
  A: "#c0563a",
  B: "#d9a441",
  C: "#2f8f6b",
};
