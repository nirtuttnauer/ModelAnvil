export interface TrainingColumnMapping {
  mode: 'auto' | 'prompt_response' | 'messages' | 'text';
  prompt_field?: string; response_field?: string; messages_field?: string; text_field?: string;
  system_field?: string; context_field?: string; group_field?: string;
}
export interface TrainingSourceInspection {
  columns: string[]; row_count: number; sample_rows: Record<string, string>[];
  source_digest: string; recommended_mapping: TrainingColumnMapping; limits: string;
  validation: TrainingDatasetValidation;
}
export interface TrainingDatasetValidation {
  checked_rows: number; invalid_rows: number; missing_value_rows: number; duplicate_rows: number; formatting_error_rows: number;
  can_prepare: boolean; mapping: TrainingColumnMapping;
  issues: { code: string; severity: 'warning' | 'error'; message: string; count: number; rows: number[]; examples?: { row: number; message?: string; duplicate_of?: number }[] }[];
}
export interface TrainingSampleRow { sample_id?: string; source_group_id?: string; assigned_split?: string; blocks?: { role?: string; type?: string; text?: string }[] }
export function mappingFields(mode: TrainingColumnMapping['mode']): Array<{ key: keyof TrainingColumnMapping; label: string; required?: boolean }> {
  const required = mode === 'prompt_response' ? [{ key: 'prompt_field' as const, label: 'Prompt column', required: true }, { key: 'response_field' as const, label: 'Response column', required: true }]
    : mode === 'messages' ? [{ key: 'messages_field' as const, label: 'Messages column', required: true }]
    : mode === 'text' ? [{ key: 'text_field' as const, label: 'Text column', required: true }] : [];
  return mode === 'auto' ? [] : [...required, ...(mode === 'prompt_response' ? [{ key: 'context_field' as const, label: 'Additional context column' }, { key: 'system_field' as const, label: 'System instructions column' }] : []), { key: 'group_field', label: 'Source group column' }];
}
export function columnMappingError(mapping: TrainingColumnMapping, columns: string[]): string | null {
  const fields = mappingFields(mapping.mode);
  if (fields.some(field => field.required && !mapping[field.key])) return 'Map every required training field before previewing.';
  const selected = fields.map(field => mapping[field.key]).filter((value): value is string => !!value);
  if (selected.some(column => !columns.includes(column))) return 'A mapped column is missing from this file. Select an available column.';
  if (new Set(selected).size !== selected.length) return 'Map each training field to a different source column.';
  return null;
}
