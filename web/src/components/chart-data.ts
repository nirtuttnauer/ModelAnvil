export interface Point { x: number; y: number }
export interface BarDatum { label: string; value: number; detail?: string; lower?: number; upper?: number; color?: number }

export function chartRange(values: number[], includeZero = false): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return [0, 1];
  let min = Math.min(...finite), max = Math.max(...finite);
  if (includeZero) { min = Math.min(0, min); max = Math.max(0, max); }
  if (min === max) {
    const padding = Math.abs(min) * .1 || 1;
    min = includeZero && min >= 0 ? 0 : min - padding;
    max += padding;
  }
  return [min, max];
}

export function validPoints(points: Point[]): Point[] {
  return points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y)).sort((a, b) => a.x - b.x);
}

export function formatValue(value: number, resolution?: number): string {
  if (resolution !== undefined && Number.isFinite(resolution) && resolution > 0) {
    const digits = Math.min(8, Math.max(2, Math.ceil(-Math.log10(resolution)) + 1));
    return value.toLocaleString(undefined, { maximumFractionDigits: digits });
  }
  if (value !== 0 && Math.abs(value) < .0001) return value.toExponential(3);
  return value.toLocaleString(undefined, { maximumFractionDigits: Math.abs(value) < 1 ? 4 : 2 });
}

export function interval(value: unknown): { lower: number; upper: number } | undefined {
  if (!value || typeof value !== 'object') return;
  const v = value as Record<string, unknown>;
  const lower = v.lower ?? v.ci_low;
  const upper = v.upper ?? v.ci_high;
  if (typeof lower !== 'number' || typeof upper !== 'number' || !Number.isFinite(lower) || !Number.isFinite(upper) || lower > upper) return;
  return { lower, upper };
}

export function numericEntries(value: unknown): BarDatum[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value).flatMap(([label, v]) => typeof v === 'number' && Number.isFinite(v) ? [{ label: label.replaceAll('_', ' '), value: v }] : []);
}
