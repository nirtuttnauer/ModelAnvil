import type { ModelCapabilities } from './resources';
import type { GuidedRevision } from './guided-training';
import type { ModelExportOption } from './model-export';

export interface Tokenizer { id: number; tokenizer_id: string; name: string; revision_no: number; vocabulary_size?: number }
export interface ModelVersion { id: number; model_version_id: string; model_name: string; architecture_ref?: string; revision_no: number; state: string; capabilities?: ModelCapabilities }
export interface DatasetRevision { id: number; revision_id: string; dataset_name?: string; revision_no: number; manifest_digest: string; row_count?: number; state: string; metadata?: GuidedRevision['metadata'] }
export interface Runner { id: number; manifest_id: string; name: string; enabled: boolean; compatibility: { contract_digest?: string } }
export interface WorkerPool { id: number; name: string; status: string; queue_name?: string }
export interface BudgetPolicy { policy_id: string; name: string; limit_amount: string; unit: string; enabled: boolean; currency: string; allowance?: { remaining_amount: string } }
export interface Checkpoint {
  checkpoint_id: string; step: number; is_valid: boolean; state_digest: string;
  weights_manifest?: { format?: string; weights_sha256?: string; weights?: { weights_sha256: string }; tensors?: Record<string, unknown> };
}
export interface TrainingMetric {
  step: number; loss: number; measured_at?: string; gradient_norm?: number; tokens_per_second?: number; engine_wall_seconds?: number; updates_since_checkpoint?: number;
  gpu_allocated_bytes?: number; peak_allocated_bytes?: number | null; gpu_utilization_percent?: number | null; trainable_parameters?: number; total_parameters?: number;
  validation_loss?: number; validation_prediction_tokens?: number;
}
export interface TrainingRun {
  guided_evaluation?: { eligible: boolean; reason: string };
  runtime?: { execution_mode?: string; pins?: { runtime?: string } };
  execution_evidence?: { level: string; source: string };
  run_id: string; recipe_type: string; status: string; initialization_seed: number; current_step: number; progress_step?: number; total_steps: number;
  latest_loss: number | null; dataset_revision: number | null; dataset_manifest_digest?: string; pool: number | null; job: string | null;
  checkpoints: Checkpoint[]; tokenizer_version: number; base_model_version: number | null; metrics_log?: TrainingMetric[];
  output_model_version?: number | null; output_model_version_uuid?: string | null; export_options?: ModelExportOption[];
  quality_summary?: { selected_step: number; baseline_loss: number | null; validation_loss: number | null; validation_examples: number } | null;
  created_at: string; started_at?: string | null; completed_at?: string | null;
}
export interface InferResult {
  run_id: string;
  verification: { is_loadable: boolean; format: string; weights_sha256: string; num_tensors: number };
  inference: { is_verified: boolean; prompt: string; completion: string; generated_tokens: string[] };
}

const METHODS: Record<string, string> = {
  full_sft: 'Full fine-tuning', lora_adapter: 'LoRA adapter', qlora_adapter: 'QLoRA adapter (4-bit)',
  continued_pretraining: 'Continued pretraining', scratch_pretraining: 'Train from scratch',
};

/** Human label for a recipe type; raw identifiers never reach the screen. */
export function trainingMethodLabel(recipe: string | null | undefined): string {
  if (!recipe) return 'Unknown method';
  return METHODS[recipe] ?? recipe.replaceAll('_', ' ');
}

/** Stable per-list ordinal: "Training run 2". */
export function trainingRunLabel(runs: { run_id: string }[], id: string): string {
  return `Training run ${runs.findIndex(run => run.run_id === id) + 1}`;
}
