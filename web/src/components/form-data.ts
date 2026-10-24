export type FieldKind = 'text' | 'number' | 'boolean' | 'empty' | 'object' | 'array';
export interface FieldNode { id: string; name: string; kind: FieldKind; text: string; children: FieldNode[] }
export interface FieldState { kind: 'object' | 'array'; fields: FieldNode[] }
export interface FormField {
  key: string; label: string; kind?: 'text' | 'number' | 'object'; multiline?: boolean;
  required?: boolean; allowEmpty?: boolean; maxLength?: number; min?: number; max?: number; step?: number;
  defaultValue?: string; help?: string;
}
const PREFIX = 'form-fields-v1:';
const kinds: FieldKind[] = ['text', 'number', 'boolean', 'empty', 'object', 'array'];
function parseSaved(raw: string): unknown {
  try { return JSON.parse(raw); }
  catch { throw new Error('Saved fields could not be restored. Clear saved fields to start again.'); }
}

function node(value: unknown, name: string, id: string): FieldNode {
  const kind: FieldKind = value === null ? 'empty' : Array.isArray(value) ? 'array' : typeof value === 'object' ? 'object' : typeof value === 'number' ? 'number' : typeof value === 'boolean' ? 'boolean' : 'text';
  return { id, name, kind, text: value === null || typeof value === 'object' ? '' : String(value), children: kind === 'object' || kind === 'array' ? Object.entries(value as object).map(([key, item], i) => node(item, key, `${id}-${i}`)) : [] };
}
export function readFieldState(raw: string, emptyKind: 'object' | 'array' = 'object'): FieldState {
  if (!raw.trim()) return { kind: emptyKind, fields: [] };
  if (raw.startsWith(PREFIX)) {
    const state = parseSaved(raw.slice(PREFIX.length)) as FieldState;
    function check(fields: FieldNode[], depth = 0): void {
      if (!Array.isArray(fields) || depth > 20) throw new Error('Saved fields could not be restored.');
      for (const field of fields) {
        if (!field || typeof field.id !== 'string' || typeof field.name !== 'string' || typeof field.text !== 'string' || !kinds.includes(field.kind)) throw new Error('Saved fields could not be restored.');
        check(field.children, depth + 1);
      }
    }
    if (!state || !['object', 'array'].includes(state.kind)) throw new Error('Saved fields could not be restored.');
    check(state.fields);
    return state;
  }
  const parsed = parseSaved(raw);
  if (!parsed || typeof parsed !== 'object') throw new Error('Saved fields could not be restored.');
  return { kind: Array.isArray(parsed) ? 'array' : 'object', fields: Object.entries(parsed).map(([key, value], i) => node(value, key, String(i))) };
}
export const writeFieldState = (state: FieldState) => PREFIX + JSON.stringify(state);

function fieldValue(field: FieldNode): unknown {
  if (field.kind === 'object' || field.kind === 'array') return stateValue({ kind: field.kind, fields: field.children });
  if (field.kind === 'empty') return null;
  if (field.kind === 'boolean') {
    if (!['true', 'false'].includes(field.text)) throw new Error(`Choose Yes or No for ${field.name || 'this value'}.`);
    return field.text === 'true';
  }
  if (field.kind === 'number') {
    if (!field.text.trim() || !Number.isFinite(Number(field.text))) throw new Error(`Enter a finite number for ${field.name || 'this value'}.`);
    return Number(field.text);
  }
  return field.text;
}
function stateValue(state: FieldState): unknown[] | Record<string, unknown> {
  if (state.kind === 'array') return state.fields.map(fieldValue);
  const names = new Set<string>();
  return Object.fromEntries(state.fields.map(field => {
    if (!field.name.trim()) throw new Error('Every field needs a name.');
    if (names.has(field.name)) throw new Error(`Field names must be unique: ${field.name}.`);
    names.add(field.name);
    return [field.name, fieldValue(field)];
  }));
}
export function structuredInput(raw: string, emptyKind: 'object' | 'array' = 'object') { return stateValue(readFieldState(raw, emptyKind)); }
export function objectInput(raw: string): Record<string, unknown> {
  const value = structuredInput(raw);
  if (Array.isArray(value)) throw new Error('These inputs require named fields.');
  return value;
}

export function readRecords(raw: string): Record<string, unknown>[] {
  if (!raw.trim()) return [];
  const value = parseSaved(raw);
  if (!Array.isArray(value) || value.some(item => !item || typeof item !== 'object' || Array.isArray(item))) throw new Error('Saved records could not be restored.');
  return value;
}
export function recordsInput(raw: string, fields: FormField[], maximum: number, uniqueKey?: string) {
  const rows = readRecords(raw);
  if (!rows.length || rows.length > maximum) throw new Error(Number.isFinite(maximum) ? `Provide between 1 and ${maximum} records.` : 'Add at least one record.');
  const seen = new Set<string>();
  return rows.map((row, index) => {
    const result = { ...row };
    for (const field of fields) {
      const value = row[field.key];
      if (value === undefined) {
        if (field.required) throw new Error(`Record ${index + 1}: ${field.label.toLowerCase()} is required.`);
        continue;
      }
      if (field.kind === 'object') {
        result[field.key] = typeof value === 'string' ? objectInput(value) : objectInput(JSON.stringify(value));
      } else if (field.kind === 'number') {
        if (value === '' || value === null || (typeof value !== 'string' && typeof value !== 'number') || !Number.isFinite(Number(value)) || (field.min !== undefined && Number(value) < field.min) || (field.max !== undefined && Number(value) > field.max) || (field.step === 1 && !Number.isInteger(Number(value)))) throw new Error(`Record ${index + 1}: enter a valid ${field.label.toLowerCase()}.`);
        result[field.key] = Number(value);
      } else if (typeof value !== 'string' || (field.required && !field.allowEmpty && !value.trim()) || (field.maxLength !== undefined && value.length > field.maxLength)) throw new Error(`Record ${index + 1}: check ${field.label.toLowerCase()}.`);
    }
    if (uniqueKey) {
      const key = String(result[uniqueKey]);
      if (seen.has(key)) throw new Error(`Record ${index + 1}: ${fields.find(f => f.key === uniqueKey)?.label || 'ID'} must be unique.`);
      seen.add(key);
    }
    return result;
  });
}

export const evaluationFields: FormField[] = [
  { key: 'case_id', label: 'Case ID', required: true, maxLength: 128 },
  { key: 'slice', label: 'Slice', maxLength: 64, defaultValue: 'general' },
  { key: 'source_group_id', label: 'Source group ID', required: true, maxLength: 128 },
  { key: 'sample_id', label: 'Source sample ID (optional)', maxLength: 128 },
  { key: 'input_prompt', label: 'Input prompt', multiline: true, required: true, allowEmpty: true, maxLength: 1024, defaultValue: '' },
  { key: 'expected_output', label: 'Expected response', multiline: true, required: true, allowEmpty: true, maxLength: 4096, defaultValue: '' },
];
export const preferenceFields: FormField[] = [
  { key: 'source_group_id', label: 'Source group ID (required for GRPO)', maxLength: 128 },
  { key: 'prompt', label: 'Prompt', multiline: true, required: true, maxLength: 61 },
  { key: 'chosen', label: 'Preferred response', multiline: true, required: true, maxLength: 32 },
  { key: 'rejected', label: 'Rejected response', multiline: true, required: true, maxLength: 32 },
];
export const sampleFields: FormField[] = [
  { key: 'id', label: 'Sample ID', required: true, maxLength: 128 },
  { key: 'text', label: 'Source text', multiline: true }, { key: 'prompt', label: 'Prompt', multiline: true },
  { key: 'input', label: 'Input', multiline: true }, { key: 'candidate_a', label: 'Candidate A', multiline: true },
  { key: 'candidate_b', label: 'Candidate B', multiline: true },
  { key: 'draft_prediction', label: 'Imported prediction', kind: 'object' },
];
export const spanFields: FormField[] = [
  { key: 'start', label: 'Start character', kind: 'number', required: true, min: 0, step: 1 },
  { key: 'end', label: 'End character', kind: 'number', required: true, min: 1, step: 1 },
  { key: 'label', label: 'Entity label', required: true },
];
export function alignmentFields(algorithm: string): FormField[] {
  const fields: FormField[] = [
    { key: 'learning_rate', label: 'Learning rate', kind: 'number', min: 0.000001, max: 0.2, defaultValue: '0.05' },
    { key: 'max_gradient_norm', label: 'Maximum gradient norm', kind: 'number', min: 0.01, max: 10, defaultValue: '1' },
  ];
  if (algorithm === 'dpo') fields.push({ key: 'beta', label: 'DPO beta', kind: 'number', min: 0.001, max: 1, defaultValue: '0.1' });
  if (['ppo_rlhf', 'verifier_rl'].includes(algorithm)) fields.push(
    { key: 'kl_coefficient', label: 'KL coefficient', kind: 'number', min: 0, max: 2, defaultValue: '0.1' },
    { key: 'clip_range', label: 'Clip range', kind: 'number', min: 0.01, max: 0.5, defaultValue: '0.2' },
    { key: 'ppo_epochs', label: 'PPO epochs', kind: 'number', min: 1, max: 4, step: 1, defaultValue: '2' },
    { key: 'rollout_batch_size', label: 'Rollout batch size', kind: 'number', min: 1, max: 4, step: 1, defaultValue: '2' },
    { key: 'max_new_tokens', label: 'Maximum new tokens', kind: 'number', min: 1, max: 16, step: 1, defaultValue: '8' },
    { key: 'value_learning_rate', label: 'Value learning rate', kind: 'number', min: 0.000001, max: 0.2, defaultValue: '0.05' },
  );
  if (algorithm === 'rloo') fields.push(
    { key: 'beta', label: 'Reward KL coefficient', kind: 'number', min: 0, max: 1, defaultValue: '0.1' },
    { key: 'max_kl_divergence', label: 'Maximum categorical KL', kind: 'number', min: 0, max: 2.5, defaultValue: '0.5' },
    { key: 'rollout_group_size', label: 'Fresh completions per prompt', kind: 'number', min: 2, max: 4, step: 1, defaultValue: '2' },
    { key: 'max_new_tokens', label: 'Maximum new tokens', kind: 'number', min: 1, max: 8, step: 1, defaultValue: '4' },
  );
  if (algorithm === 'grpo') fields.push(
    { key: 'kl_coefficient', label: 'KL coefficient', kind: 'number', min: 0, max: 2, defaultValue: '0.1' },
    { key: 'clip_range', label: 'Clip range', kind: 'number', min: 0.01, max: 0.5, defaultValue: '0.2' },
    { key: 'ppo_epochs', label: 'Policy epochs per group', kind: 'number', min: 1, max: 4, step: 1, defaultValue: '2' },
    { key: 'group_size', label: 'Completions per prompt', kind: 'number', min: 2, max: 8, step: 1, defaultValue: '4' },
    { key: 'max_new_tokens', label: 'Maximum new tokens', kind: 'number', min: 1, max: 16, step: 1, defaultValue: '8' },
  );
  return fields;
}
