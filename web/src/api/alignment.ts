import { apiRequest } from './client';

export interface PreferencePair { prompt: string; chosen: string; rejected: string; source_group_id?: string }
export interface PreferenceArtifact { artifact_id: string; name: string; sha256: string; byte_size: number; row_count: number; state: string }
export interface AlignmentRun {
  run_id: string; algorithm: string; status: string; current_step: number; total_steps: number;
  execution_capabilities?: { can_execute: boolean; can_resume?: boolean; reason: string; runtime?: string; supported_algorithms?: string[] };
  execution_evidence?: { level: string; source: string };
  policy_model_version: number; reference_model_version: number | null; reward_model_version: number | null;
  train_dataset_artifact?: string | null; held_out_dataset_artifact?: string | null;
  regression_dataset_artifact?: string | null; worker_pool?: number | null; job_id?: string | null; job_status?: string | null;
  dataset_manifest_digest: string; held_out_validation_digest: string;
  hyperparameters: Record<string, unknown>; verifier_spec: Record<string, unknown>; latest_metrics: unknown;
  metrics_history?: Array<Record<string, unknown>>; output_model_version?: number | null;
  execution_pins?: Record<string, unknown>; stop_reason: string;
}
export interface AlignmentPlan {
  algorithm: string; policy_model_version: number; reference_model_version: number | null; reward_model_version: number | null;
  train_dataset_artifact: string; held_out_dataset_artifact: string; total_steps: number;
  regression_dataset_artifact?: string | null; worker_pool?: number | null;
  hyperparameters: Record<string, unknown>; verifier_spec: Record<string, unknown>;
}

export function preferencePairs(raw: string): PreferencePair[] {
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { throw new Error('Could not read the preference records. Each pair needs a prompt, a preferred response, and a rejected response.'); }
  if (!Array.isArray(parsed) || !parsed.length || parsed.length > 32) throw new Error('Provide between 1 and 32 preference pairs.');
  const seen = new Set<string>();
  return parsed.map(value => {
    if (!value || typeof value !== 'object' || Array.isArray(value) || ['prompt', 'chosen', 'rejected'].some(key => typeof value[key] !== 'string' || !value[key].trim())) throw new Error('Each pair needs nonempty prompt, chosen, and rejected strings.');
    const pair = value as PreferencePair;
    if (pair.chosen === pair.rejected) throw new Error('Chosen and rejected responses must differ.');
    if (pair.chosen.length > 32 || pair.rejected.length > 32 || pair.prompt.length + Math.max(pair.chosen.length, pair.rejected.length) > 62) throw new Error('Responses support at most 32 characters; prompt plus response supports 62.');
    const identity = JSON.stringify([pair.prompt, pair.chosen, pair.rejected]);
    if (seen.has(identity)) throw new Error('Preference pairs must be unique.');
    seen.add(identity);
    if (pair.source_group_id !== undefined && (typeof pair.source_group_id !== 'string' || !pair.source_group_id.trim() || pair.source_group_id.length > 128)) throw new Error('Source group IDs must contain 1–128 characters.');
    return { prompt: pair.prompt, chosen: pair.chosen, rejected: pair.rejected, ...(pair.source_group_id !== undefined ? { source_group_id: pair.source_group_id } : {}) };
  });
}

export function registerPreferences(token: string, name: string, samples: PreferencePair[], signal?: AbortSignal, labelsReviewed = false) {
  return apiRequest<PreferenceArtifact>('/api/v1/alignment-runs/register-preferences/', token,
    { method: 'POST', body: JSON.stringify({ name, samples, ...(labelsReviewed ? { labels_reviewed: true } : {}) }), signal });
}
export function createAlignmentPlan(token: string, plan: AlignmentPlan, signal?: AbortSignal) {
  const limit = plan.worker_pool ? 20 : 100;
  if (!Number.isInteger(plan.total_steps) || plan.total_steps < 1 || plan.total_steps > limit) throw new Error(`Choose between 1 and ${limit} ${plan.worker_pool ? 'Apple GPU' : 'CPU'} steps.`);
  if (plan.worker_pool && (plan.algorithm !== 'dpo' || !plan.regression_dataset_artifact ||
      [plan.train_dataset_artifact, plan.held_out_dataset_artifact].includes(plan.regression_dataset_artifact))) throw new Error('Apple GPU DPO requires a separate regression artifact.');
  if (!plan.train_dataset_artifact || !plan.held_out_dataset_artifact || plan.train_dataset_artifact === plan.held_out_dataset_artifact) throw new Error('Pin separate training and held-out preference artifacts.');
  return apiRequest<AlignmentRun>('/api/v1/alignment-runs/', token,
    { method: 'POST', body: JSON.stringify(plan), signal });
}
export function alignmentAction(token: string, runId: string, action: 'execute' | 'cancel' | 'resume', signal?: AbortSignal) {
  if (!['execute', 'cancel', 'resume'].includes(action)) throw new Error('Unsupported alignment action.');
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(runId)) throw new Error('Invalid alignment run identifier.');
  return apiRequest<AlignmentRun>(`/api/v1/alignment-runs/${runId}/${action}/`, token,
    { method: 'POST', body: '{}', signal });
}
