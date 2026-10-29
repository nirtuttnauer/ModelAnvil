import type { ModelCapabilities } from './resources';

/** A model family as listed by /api/v1/models/. */
export interface Model { id?: number; model_id: string; name: string; description: string; intended_tasks: string[] }

/** One registered model version as listed by /api/v1/model-versions/. */
export interface ModelVersion {
  id: number; model_version_id: string; model?: number; model_name: string; revision_no: number; state: string;
  architecture_ref?: string; tokenizer?: number; parameters_count?: number | null; license_evidence?: string; created_at?: string;
  capabilities?: ModelCapabilities;
}

/** Versions that belong to a model, newest revision first. */
export function versionsOf(model: Model, versions: ModelVersion[]): ModelVersion[] {
  return versions
    .filter(version => (version.model != null && model.id != null ? version.model === model.id : version.model_name === model.name))
    .sort((a, b) => b.revision_no - a.revision_no);
}

/** `text_generation` → `Text generation`. */
export function taskLabel(task: string): string {
  const text = task.replace(/[_-]+/g, ' ').trim();
  return text ? text[0].toUpperCase() + text.slice(1) : task;
}

export function parseTasks(text: string): string[] {
  return [...new Set(text.split(',').map(task => task.trim()).filter(Boolean))];
}

export function formatParameters(count?: number | null): string {
  if (count == null) return 'Not reported';
  if (count >= 1e9) return `${(count / 1e9).toFixed(count % 1e9 ? 1 : 0)}B parameters`;
  if (count >= 1e6) return `${(count / 1e6).toFixed(count % 1e6 ? 1 : 0)}M parameters`;
  return `${count.toLocaleString()} parameters`;
}
