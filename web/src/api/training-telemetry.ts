/** Measured per-step accelerator telemetry. A missing value is shown as missing, never estimated. */
export interface TelemetryMetric {
  step: number; loss?: number | null; measured_at?: string; validation_loss?: number | null; validation_prediction_tokens?: number;
  gradient_norm?: number | null; tokens_per_second?: number | null; training_pairs?: number; padding_positions?: number;
  gpu_allocated_bytes?: number | null; peak_allocated_bytes?: number | null; peak_reserved_bytes?: number | null;
  gpu_utilization_percent?: number | null; trainable_parameters?: number; total_parameters?: number;
  optimizer_state_bytes?: number; compute_precision?: string; unavailable_metrics?: Record<string, string>;
}
export interface OptimizationProfile {
  compute_precision?: string; gradient_checkpointing?: boolean; batch_samples?: number; sequence_layout?: string;
  attention_kernel?: string; optimizer?: string;
}

export const NOT_REPORTED = 'Not reported';
const REASON_LABELS: Record<string, string> = { not_exposed_by_mlx: 'Not exposed by MLX' };
const REASON_TEXT: Record<string, string> = {
  not_exposed_by_mlx: 'MLX exposes active, peak-active and cache memory, but no peak reserved-pool or GPU utilization counter. These values are not estimated.',
};
const METRIC_LABELS: Record<string, string> = {
  peak_reserved_bytes: 'Peak reserved memory', gpu_utilization_percent: 'GPU utilization', peak_allocated_bytes: 'Peak allocated memory',
  gpu_allocated_bytes: 'Allocated memory', gradient_norm: 'Gradient norm', tokens_per_second: 'Tokens per second',
};

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** Rows with a measurement time, one per step, latest last. */
export function telemetryRows<T extends TelemetryMetric>(metrics: T[] = [], limit = 10): T[] {
  const rows = metrics.filter(row => Number.isSafeInteger(row.step) && row.step >= 0 && typeof row.measured_at === 'string');
  return [...new Map(rows.map(row => [row.step, row])).values()].sort((a, b) => a.step - b.step).slice(-limit);
}

/** Display text for one value; a runtime-declared reason replaces the generic missing label. */
export function telemetryCell(row: TelemetryMetric, key: keyof TelemetryMetric, format: (value: number) => string): string {
  const value = row[key];
  if (finite(value)) return format(value);
  const code = row.unavailable_metrics?.[key as string];
  return code ? REASON_LABELS[code] ?? NOT_REPORTED : NOT_REPORTED;
}

export const mebibytes = (bytes: number) => (bytes / 1024 ** 2).toFixed(1);

/** UTC measurement time to the second; malformed timestamps are reported as missing. */
export function measuredAt(value: string | undefined): string {
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isFinite(parsed) ? `${new Date(parsed).toISOString().slice(0, 19).replace('T', ' ')} UTC` : 'Time not reported';
}

/** Distinct reasons declared by the runtime for values it cannot measure. */
export function missingReasons(rows: TelemetryMetric[]): { metrics: string[]; reason: string }[] {
  const grouped = new Map<string, Set<string>>();
  for (const row of rows) for (const [metric, code] of Object.entries(row.unavailable_metrics ?? {})) {
    if (finite(row[metric as keyof TelemetryMetric])) continue;
    if (!grouped.has(code)) grouped.set(code, new Set());
    grouped.get(code)!.add(METRIC_LABELS[metric] ?? metric.replaceAll('_', ' '));
  }
  return [...grouped].map(([code, metrics]) => ({ metrics: [...metrics], reason: REASON_TEXT[code] ?? 'The runtime declared this value unavailable. It is not estimated.' }));
}

const PRECISION: Record<string, string> = { fp32: 'FP32 compute', bf16: 'BF16 compute, FP32 adapters' };
const OPTIMIZER: Record<string, string> = { adamw: 'AdamW', adafactor: 'Adafactor (factored, no momentum)' };

/** Plain-language pinned optimization profile, or null when the run has none. */
export function optimizationSummary(profile: OptimizationProfile | null | undefined): string | null {
  if (!profile || typeof profile !== 'object') return null;
  const samples = profile.batch_samples ?? 1;
  return [
    PRECISION[profile.compute_precision ?? ''] ?? `${profile.compute_precision ?? 'Unknown'} compute`,
    samples === 1 ? 'one sample per step' : `${samples} samples per step, ${profile.sequence_layout === 'packed' ? 'packed with sample-boundary masks' : 'right-padded'}`,
    profile.gradient_checkpointing ? 'gradient checkpointing' : 'no gradient checkpointing',
    OPTIMIZER[profile.optimizer ?? ''] ?? profile.optimizer ?? 'unknown optimizer',
    profile.attention_kernel === 'mlx_fast_sdpa_force_fused' ? 'MLX fast attention, fused kernel forced' : 'MLX fast attention',
  ].join(' · ');
}
