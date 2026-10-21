export interface TrainingMetric {
  step: number; loss: number; validation_loss?: number | null; measured_at?: string;
  engine_wall_seconds?: number; updates_since_checkpoint?: number;
}
export interface TrainingProgressRun {
  status: string; current_step: number; progress_step?: number; total_steps: number;
  latest_loss: number | null; metrics_log?: TrainingMetric[];
  runtime?: { execution_mode?: string }; started_at?: string | null; completed_at?: string | null;
}

function timestamp(value: string | null | undefined): number | null {
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
}
export function trainingDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return 'Not reported';
  if (seconds < 1) return '< 1s';
  const rounded = Math.ceil(seconds);
  if (rounded < 60) return `${rounded}s`;
  const minutes = Math.floor(rounded / 60), remainder = rounded % 60;
  if (minutes < 60) return `${minutes}m${remainder ? ` ${remainder}s` : ''}`;
  return `${Math.floor(minutes / 60)}h${minutes % 60 ? ` ${minutes % 60}m` : ''}`;
}
export function trainingLossSeries(metrics: TrainingMetric[] = []) {
  const rows = [...new Map(metrics.filter(row => Number.isSafeInteger(row.step) && row.step >= 0).map(row => [row.step, row])).values()].sort((a, b) => a.step - b.step);
  return [
    { name: 'Training loss', points: rows.filter(row => Number.isFinite(row.loss)).map(row => ({ x: row.step, y: row.loss })) },
    { name: 'Validation loss', points: rows.flatMap(row => typeof row.validation_loss === 'number' && Number.isFinite(row.validation_loss) ? [{ x: row.step, y: row.validation_loss }] : []) },
  ].filter(series => series.points.length);
}

export function trainingProgress(run: TrainingProgressRun, now: number, fresh: boolean) {
  const total = Number.isSafeInteger(run.total_steps) && run.total_steps > 0 ? run.total_steps : 0;
  const bounded = (value: number | undefined) => Number.isSafeInteger(value) && value! >= 0 ? Math.min(value!, total) : 0;
  const committed = bounded(run.current_step), reported = Math.max(committed, bounded(run.progress_step));
  const active = run.status === 'running', terminal = !['pending', 'running'].includes(run.status);
  const start = timestamp(run.started_at), end = terminal ? timestamp(run.completed_at) : now;
  const elapsed = start !== null && end !== null && start <= end && end <= now ? (end - start) / 1000 : null;
  const metrics = [...new Map((run.metrics_log || []).filter(row => Number.isSafeInteger(row.step) && row.step > 0 && row.step <= committed).map(row => [row.step, row])).values()].sort((a, b) => a.step - b.step).slice(-6);
  let secondsPerStep: number | null = null, basis = '';
  // Timestamp intervals include the time between reports; engine timings omit some checkpoint overhead.
  const timed = metrics.filter(row => { const at = timestamp(row.measured_at); return at !== null && at <= now; });
  let seconds = 0, updates = 0;
  for (let i = 1; i < timed.length; i++) {
    const interval = (timestamp(timed[i].measured_at)! - timestamp(timed[i - 1].measured_at)!) / 1000;
    if (interval <= 0) { seconds = 0; updates = 0; continue; }
    seconds += interval; updates += timed[i].step - timed[i - 1].step;
  }
  if (updates > 0) { secondsPerStep = seconds / updates; basis = 'Based on recent measured step intervals. Validation and checkpoint work can change the finish time.'; }
  else {
    const engine = metrics.filter(row => Number.isFinite(row.engine_wall_seconds) && row.engine_wall_seconds! > 0 && Number.isSafeInteger(row.updates_since_checkpoint ?? 1) && (row.updates_since_checkpoint ?? 1) > 0);
    if (engine.length >= 2) {
      secondsPerStep = engine.reduce((sum, row) => sum + row.engine_wall_seconds!, 0) / engine.reduce((sum, row) => sum + (row.updates_since_checkpoint ?? 1), 0);
      basis = 'Based on recent measured engine time. Checkpoint storage and finalization may take additional time.';
    }
  }
  let remaining: number | null = null, remainingLabel = 'Waiting for measured step timings';
  if (run.runtime?.execution_mode === 'simulation') remainingLabel = 'Unavailable for synthetic runs';
  else if (terminal) remainingLabel = run.status === 'completed' ? 'Finished' : 'Run stopped';
  else if (!fresh) remainingLabel = 'Waiting for a fresh update';
  else if (!active) remainingLabel = 'Waiting to start';
  else if (!total) remainingLabel = 'Total steps not reported';
  else if (reported === total) remainingLabel = 'Finalizing run';
  else if (timed.length >= 2 && now - timestamp(timed.at(-1)!.measured_at)! > Math.max(60000, seconds * 3000)) remainingLabel = 'Waiting for new step timings';
  else if (secondsPerStep !== null && Number.isFinite(secondsPerStep) && secondsPerStep > 0) {
    remaining = (total - reported) * secondsPerStep;
    remainingLabel = `About ${trainingDuration(remaining)}`;
  }
  return { total, committed, reported, percent: total ? Math.floor(reported / total * 100) : null,
    elapsed, remaining, remainingLabel, basis, secondsPerStep };
}
