export interface Review {
  record_id: string; revision_no: number; decision: string; reviewer_id: string;
  human_label: { label?: unknown }; original_prediction: unknown; created_at: string;
}
export interface AnnotationTask {
  assigned_reviewer: string; needs_adjudication: boolean; task_id: string; sample_ref: string; status: string;
  content: Record<string, unknown> & { draft_prediction?: { predicted_label?: unknown; model_version_id?: string } };
  latest_review: Review | null;
}
export interface LabelSchema { kind: string; classes: string[] }
export const preferenceLabels = ['candidate_a', 'candidate_b', 'tie', 'abstain'];

export function initialLabel(task: AnnotationTask): string {
  const label = task.latest_review?.human_label.label ?? task.content.draft_prediction?.predicted_label;
  return label === undefined ? '' : typeof label === 'string' ? label : JSON.stringify(label, null, 2);
}
export function validLabel(schema: LabelSchema, label: unknown): boolean {
  if (typeof label !== 'string') return false;
  if (schema.kind === 'classification') return schema.classes.includes(label);
  if (schema.kind === 'preference_ranking') return preferenceLabels.includes(label);
  return schema.kind === 'text_generation' && !!label.trim();
}
export function matchesQueue(task: AnnotationTask, filter: string, search = ''): boolean {
  const matches = filter === 'pending' ? !task.latest_review && !task.needs_adjudication
    : filter === 'flagged' ? task.needs_adjudication
    : filter === 'reviewed' ? !!task.latest_review
    : filter === 'skipped' ? task.latest_review?.decision === 'skipped' : true;
  const source = [task.sample_ref, ...Object.entries(task.content).filter(([key]) => !['draft_prediction', 'arena_vote', 'comparison_origin'].includes(key)).map(([, value]) => typeof value === 'string' ? value : '')].join(' ').toLocaleLowerCase();
  return matches && source.includes(search.trim().toLocaleLowerCase());
}
export function nextPending(tasks: AnnotationTask[], current: string): string | null {
  const index = tasks.findIndex(task => task.task_id === current);
  const ordered = [...tasks.slice(index + 1), ...tasks.slice(0, Math.max(0, index))];
  return ordered.find(task => !task.latest_review && !task.needs_adjudication)?.task_id || null;
}

// Batches are bounded to 500 samples, matching the API's import limit.
export function parseSamples(text: string): Record<string, unknown>[] {
  const raw = text.replace(/^\uFEFF/, '').trim();
  if (!raw) throw new Error('The file is empty. Choose a JSON array or JSONL file.');
  let rows: unknown;
  if (raw.startsWith('[')) {
    try { rows = JSON.parse(raw); } catch { throw new Error('Invalid JSON. Use an array of sample objects.'); }
  } else {
    rows = raw.split(/\r?\n/).flatMap((line, index) => {
      if (!line.trim()) return [];
      try { return [JSON.parse(line)]; } catch { throw new Error(`Invalid JSON on line ${index + 1}. Each JSONL line must contain one sample object.`); }
    });
  }
  if (!Array.isArray(rows) || !rows.length || rows.length > 500) throw new Error('Import between 1 and 500 samples per batch.');
  if (rows.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error('Every sample must be an object with an id and source content.');
  return rows;
}

export function validateSamples(rows: Record<string, unknown>[], schema: LabelSchema, modelId: string | null, auditRefs: string[] = []): void {
  if (!rows.length || rows.length > 500) throw new Error('Add between 1 and 500 samples.');
  const ids = new Set<string>();
  for (const [index, row] of rows.entries()) {
    const prefix = `Sample ${index + 1}`;
    if (typeof row.id !== 'string' || !row.id.trim() || row.id.length > 128) throw new Error(`${prefix} needs an id of 1–128 characters.`);
    if (ids.has(row.id)) throw new Error(`Duplicate sample id: ${row.id}.`);
    ids.add(row.id);
    const source = 'text' in row ? row.text : 'prompt' in row ? row.prompt : row.input;
    if (schema.kind !== 'preference_ranking' && (typeof source !== 'string' || !source.trim())) throw new Error(`${prefix} (${row.id}) needs nonempty text, prompt, or input. The first field present in that order is used.`);
    if (schema.kind === 'preference_ranking' && !['candidate_a', 'candidate_b'].every(key => typeof row[key] === 'string' && row[key].trim())) throw new Error(`${prefix} (${row.id}) needs both candidate A and candidate B responses.`);
    if (auditRefs.includes(row.id) || row.protected || ['split', 'assigned_split'].some(key => ['audit', 'test', 'validation', 'val', 'evaluation', 'eval', 'protected_eval', 'held_out'].includes(String(row[key] ?? '').trim().toLowerCase()))) throw new Error(`${prefix} (${row.id}) is protected audit or evaluation data.`);
    if (row.draft_prediction !== undefined) {
      const prediction = row.draft_prediction as AnnotationTask['content']['draft_prediction'];
      if (!modelId || !prediction || typeof prediction !== 'object' || prediction.model_version_id !== modelId) throw new Error(`${prefix} (${row.id}) must identify the campaign’s pinned model version in draft_prediction.model_version_id.`);
      if (!validLabel(schema, prediction.predicted_label)) throw new Error(`${prefix} (${row.id}) has a prediction outside the label schema.`);
    }
  }
}
