import type { RunKind } from './runs';

export interface Bounded<T> {
  total: number;
  truncated: boolean;
  rows: T[];
}

export interface Checkpoint {
  checkpoint_id: string;
  step: number;
  state_digest: string;
  is_valid: boolean;
  contract_digest: string | null;
  weights_sha256: string | null;
  created_at: string;
}

export interface ResumeCandidate {
  available: boolean;
  reason: string;
  checkpoint_id: string | null;
  step: number | null;
  state_digest: string | null;
  contract_digest: string | null;
}

export interface Attempt {
  attempt_id: string;
  job_id: string;
  worker: string | null;
  worker_status: string | null;
  status: string;
  progress: number;
  error: string;
  lease_expires_at: string | null;
  started_at: string;
  completed_at: string | null;
  has_result: boolean;
}

export interface RunDetail {
  kind: RunKind;
  id: string;
  name: string;
  project: string | null;
  execution_mode: string;
  observed: {
    state: string;
    job_state: string | null;
    current_step: number | null;
    total_steps: number | null;
    progress: number | null;
    latest_loss: number | null;
    attempts: string | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    updated_at: string;
  };
  desired: { action: string; acknowledged: boolean; note: string };
  ownership: {
    state: string;
    worker: string | null;
    worker_status: string | null;
    lease_expires_at: string | null;
    reason: string;
  };
  inputs: Record<string, unknown>;
  metrics: Bounded<Record<string, unknown>> & { latest_loss: number | null };
  checkpoints: (Bounded<Checkpoint> & { resume_candidate: ResumeCandidate }) | null;
  usage: {
    reservations: Array<{
      reservation_id: string;
      policy_name: string;
      unit: string;
      state: string;
      estimated_amount: string;
      settled_amount: string | null;
    }>;
    events: Array<{ usage_id: string; quantity: string; unit: string; occurred_at: string }>;
    events_truncated: boolean;
  };
  links: Record<string, string | string[] | null>;
  evidence: { level: string; source: string } | null;
  actions: {
    cancel: {
      available: boolean;
      requested: boolean;
      acknowledged: boolean;
      endpoint: string | null;
      blocked_by: string[];
    };
    resume: {
      available: boolean;
      endpoint?: string;
      recovery_run_id?: string | null;
      blocked_by: string[];
      permission: { role: string | null; required: string; satisfied: boolean };
      checkpoint?: ResumeCandidate;
      budget?: { state: string; reservable: boolean; reason: string };
      operator_path?: string;
      preserves_history: string;
    };
  };
  generated_at: string;
}

export function linkId(value: string | string[] | null | undefined) {
  return Array.isArray(value) ? value[0] ?? '' : (value ?? '');
}
