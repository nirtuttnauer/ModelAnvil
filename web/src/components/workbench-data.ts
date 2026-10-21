export interface RecordedMetric {
  key: string; slice_name: string; value: number | null; sample_count?: number | null; uncertainty_interval?: unknown;
}

export function compareMetrics(candidate: RecordedMetric[], baseline: RecordedMetric[]) {
  const key = (metric: RecordedMetric) => JSON.stringify([metric.key, metric.slice_name]);
  const candidates = new Map(candidate.map(metric => [key(metric), metric]));
  const baselines = new Map(baseline.map(metric => [key(metric), metric]));
  return [...new Set([...candidates.keys(), ...baselines.keys()])].map(id => {
    const current = candidates.get(id), previous = baselines.get(id), metric = current || previous!;
    return { key: metric.key, slice: metric.slice_name, candidate: current, baseline: previous,
      delta: typeof current?.value === 'number' && typeof previous?.value === 'number' && Number.isFinite(current.value) && Number.isFinite(previous.value) && Number.isFinite(current.value - previous.value) ? current.value - previous.value : null };
  });
}

export function highlightTerms(text: string, query: string) {
  const terms = [...new Set(query.toLowerCase().match(/[\p{L}\p{N}_]+/gu) || [])].sort((a, b) => b.length - a.length);
  if (!terms.length) return [{ text, matched: false }];
  const pattern = new RegExp(`(${terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'giu');
  return text.split(pattern).filter(part => part !== '').map(part => ({ text: part, matched: terms.includes(part.toLowerCase()) }));
}
