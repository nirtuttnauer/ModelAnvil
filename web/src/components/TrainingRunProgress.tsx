import { Button, Stat, StatRow, StatusBadge } from './ui';
import { useEffect, useState } from 'react';
import { trainingDuration, trainingProgress, type TrainingProgressRun } from '../api/training-progress';

export function TrainingRunProgress({ run, label = 'Training progress', refreshedAt, refreshError, onRefresh, onCancel, cancelBusy = false }: {
  run: TrainingProgressRun; label?: string; refreshedAt: number; refreshError: string | null; onRefresh: () => void; onCancel?: () => void; cancelBusy?: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(timer); }, []);
  const active = ['pending', 'running'].includes(run.status);
  const fresh = !refreshError && refreshedAt > 0 && (!active || now - refreshedAt <= 15000);
  const progress = trainingProgress(run, Math.max(now, Date.now()), fresh);
  const latestValidation = [...(run.metrics_log || [])].reverse().find(row => typeof row.validation_loss === 'number' && Number.isFinite(row.validation_loss))?.validation_loss;
  return <section className="training-progress" aria-label="Live training progress">
    <header>
      <div><h2>{label}</h2><StatusBadge status={run.status} /><span className="training-progress-feed" role="status">{!fresh ? 'Updates interrupted' : active ? 'Live · refreshes every 3 seconds' : 'Final recorded state'}</span></div>
      <div data-ui="actions">{onCancel && active && <Button type="button" size="sm" disabled={cancelBusy} onClick={onCancel}>Cancel run</Button>}<Button type="button" variant="quiet" size="sm" onClick={onRefresh}>Refresh progress</Button></div>
    </header>
    {refreshError && <p role="alert">Could not refresh training progress: {refreshError}. Displaying the last received state.</p>}
    <div className="training-progress-bar"><strong>{progress.percent === null ? 'Progress not reported' : `${progress.percent}% complete`}</strong><span className="muted">{progress.reported} / {progress.total || 'unknown'} steps reported</span>
      {progress.total > 0 && <progress value={progress.reported} max={progress.total} aria-label="Training completion" />}
    </div>
    <p className="muted">{progress.committed} steps saved in checkpoints{progress.reported > progress.committed ? ` · ${progress.reported - progress.committed} additional steps reported by the worker` : ''}.</p>
    <StatRow>
      <Stat label="Elapsed time" value={trainingDuration(progress.elapsed)} />
      <Stat label="Estimated time remaining" value={progress.remainingLabel} />
      <Stat label="Latest training loss" value={typeof run.latest_loss === 'number' && Number.isFinite(run.latest_loss) ? run.latest_loss.toFixed(4) : 'Not reported'} />
      <Stat label="Latest validation loss" value={latestValidation == null ? 'Not reported' : latestValidation.toFixed(4)} />
    </StatRow>
    {progress.remaining !== null && <p className="muted">{progress.basis}</p>}
    <p className="training-progress-updated muted">{refreshedAt > 0 ? `Last refreshed ${new Date(refreshedAt).toLocaleTimeString()}.` : 'Waiting for the first update.'}</p>
  </section>;
}
