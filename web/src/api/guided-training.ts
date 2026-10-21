import type { ModelMemory } from './model-hardware';
import type { TrainingSampleRow } from './training-dataset';

export interface GuidedInputs {
  project: string; execution_mode: 'worker'; recipe_type: 'full_sft' | 'lora_adapter'; base_model_version: number;
  tokenizer_version: number; runner_manifest: number; pool: number; budget_policy_id: string; initialization_seed: number;
}
export interface GuidedOptions {
  compute: { available: boolean; busy: boolean; device: string | null; message: string; memory_bytes?: number | null; memory_observed_at?: string | null; memory_basis?: string };
  model: { id: string; name: string; description: string; parameters: number; license: string; max_examples: number; max_tokens: number; source: { repo_id: string; revision: string }; memory_requirements?: ModelMemory };
  default_epochs: number; max_steps: number;
}
export interface GuidedPreview {
  row_count: number; source_group_count: number; split_counts: Record<string, number>; recipe_digest: string;
  examples: { role?: string; text: string }[][]; warnings: string[]; dropped_count: number; objectives: string[];
  sample_rows?: TrainingSampleRow[];
}
export interface GuidedRevision {
  id: number; revision_id: string; row_count: number; dataset_name: string;
  metadata: { split_counts: Record<string, number>; source_group_count: number };
}
export function readGuidedValue<T>(value: string): T | null {
  try { return value ? JSON.parse(value) as T : null; } catch { return null; }
}
export function guidedLaunch(inputs: GuidedInputs, revision: GuidedRevision, steps: number) {
  if (!Number.isInteger(steps) || steps < 1 || steps > 3000) throw new Error('Choose between 1 and 3,000 training steps.');
  if (!Number.isInteger(revision.id) || revision.id < 1) throw new Error('Choose a published dataset revision.');
  return { ...inputs, dataset_revision: revision.id, total_steps: steps };
}

export function guidedPlan(revision: GuidedRevision | null, large = false) {
  const trainingExamples = revision?.metadata?.split_counts?.train ?? 0;
  const epochs = large && trainingExamples < 100 ? 6 : 3;
  const steps = trainingExamples * epochs;
  return { trainingExamples, epochs, steps,
    minutesLow: Math.max(1, Math.ceil(steps * (large ? 0.5 : 0.25) / 60)), minutesHigh: Math.max(1, Math.ceil((steps * (large ? 5 : 2) + 30) / 60)) };
}
