/** One status vocabulary → tone mapping for every lifecycle rendered in the workspace. */
export type StatusTone = 'neutral' | 'info' | 'running' | 'success' | 'caution' | 'error';

const TONES: Record<Exclude<StatusTone, 'neutral' | 'info'>, string[]> = {
  running: ['running', 'generating', 'evaluating', 'ingesting', 'busy', 'reviewing', 'draining', 'in_progress', 'processing', 'preparing', 'downloading'],
  success: ['succeeded', 'completed', 'published', 'ready', 'approved', 'qualified', 'valid', 'ok', 'active', 'closed', 'connected', 'accepted_without_edit', 'corrected', 'pass', 'passed', 'included', 'enabled', 'healthy', 'verified', 'settled', 'released'],
  caution: ['interrupted', 'paused', 'expired', 'skipped', 'stale', 'opt_in_required', 'unknown', 'omitted', 'missing_evidence', 'missing', 'partial', 'degraded', 'unverified', 'cancellation_requested'],
  error: ['failed', 'rejected', 'invalid', 'denied', 'error', 'offline', 'blocked', 'fail', 'lost', 'incompatible'],
};

const LABELS: Record<string, string> = {
  accepted_without_edit: 'Accepted as drafted',
  opt_in_required: 'Opt-in required',
  integrated_execution: 'Measured on worker',
  fixture: 'Demo fixture',
  missing_evidence: 'Missing evidence',
  cancellation_requested: 'Cancellation requested',
};

export function normalizeStatus(status: string | null | undefined): string {
  return (status ?? '').trim().toLowerCase().replaceAll(/[\s-]+/g, '_');
}

export function statusTone(status: string | null | undefined): StatusTone {
  const key = normalizeStatus(status);
  if (!key) return 'neutral';
  for (const tone of Object.keys(TONES) as (keyof typeof TONES)[]) if (TONES[tone].includes(key)) return tone;
  return 'neutral';
}

/** Human label: "accepted_without_edit" → "Accepted as drafted", "" → "None". */
export function statusLabel(status: string | null | undefined): string {
  const key = normalizeStatus(status);
  if (!key) return 'None';
  if (LABELS[key]) return LABELS[key];
  const words = key.replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
