export function comparisonBlockers(runs: { recipe_type: string; runtime?: { execution_mode?: string; pins?: Record<string, unknown> } }[]): string[] {
  if (runs.length !== 2) return ['Select exactly two runs.'];
  const [a, b] = runs;
  if (a.runtime?.execution_mode !== 'worker' || b.runtime?.execution_mode !== 'worker') return ['Synthetic fixture measurements cannot enter a real experiment comparison.'];
  const keys = ['runtime', 'contract_digest', 'build_digest', 'dataset_digest', 'tokenizer_digest', 'config', 'validation'];
  const missing = keys.filter(key => a.runtime?.pins?.[key] === undefined || b.runtime?.pins?.[key] === undefined);
  const differing = keys.filter(key => JSON.stringify(a.runtime?.pins?.[key]) !== JSON.stringify(b.runtime?.pins?.[key]));
  return [...(a.recipe_type !== b.recipe_type ? ['Recipes differ.'] : []), ...(missing.length ? [`Compatibility is unreported: ${missing.join(', ')}.`] : []), ...(differing.length ? [`Measurement inputs or protocols differ: ${differing.join(', ')}.`] : [])];
}
