import { Badge, Button } from './ui';
import { useEffect, useState } from 'react';
import { trainingDuration, trainingProgress, type TrainingProgressRun } from '../api/training-progress';

export function TrainingRunProgress({ run, refreshedAt, refreshError, onRefresh }: {
  run: TrainingProgressRun; refreshedAt: number; refreshError: string | null; onRefresh: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(timer); }, []);
  const active = ['pending', 'running'].includes(run.status);
  const fresh = !refreshError && refreshedAt > 0 && (!active || now - refreshedAt <= 15000);
  const progress = trainingProgress(run, Math.max(now, Date.now()), fresh);
  const latestValidation = [...(run.metrics_log || [])].reverse().find(row => typeof row.validation_loss === 'number' && Number.isFinite(row.validation_loss))?.validation_loss;
  return <section className="training-progress" aria-label="Live training progress">
    <header><div><h3>Training progress</h3><Badge className={`state state-${run.status}`}>{run.status}</Badge>
      <span className="training-progress-feed" role="status">{!fresh ? 'Updates interrupted' : active ? 'Live · refreshes every 3 seconds' : 'Final recorded state'}</span></div>
      <Button type="button" onClick={onRefresh}>Refresh progress</Button></header>
    {refreshError && <p role="alert">Could not refresh training progress: {refreshError}. Displaying the last received state.</p>}
    <div className="training-progress-bar"><strong>{progress.percent === null ? 'Progress not reported' : `${progress.percent}% complete`}</strong><span>{progress.reported} / {progress.total || 'unknown'} steps reported</span>
      {progress.total > 0 && <progress value={progress.reported} max={progress.total} aria-label="Training completion" />}
    </div>
    <p className="muted">{progress.committed} steps saved in checkpoints{progress.reported > progress.committed ? ` · ${progress.reported - progress.committed} additional steps reported by the worker` : ''}.</p>
    <dl className="training-progress-stats">
      <div><dt>Elapsed time</dt><dd>{trainingDuration(progress.elapsed)}</dd></div>
      <div><dt>Estimated time remaining</dt><dd>{progress.remainingLabel}</dd></div>
      <div><dt>Latest training loss</dt><dd>{typeof run.latest_loss === 'number' && Number.isFinite(run.latest_loss) ? run.latest_loss.toFixed(4) : 'Not reported'}</dd></div>
      <div><dt>Latest validation loss</dt><dd>{latestValidation == null ? 'Not reported' : latestValidation.toFixed(4)}</dd></div>
    </dl>
    {progress.remaining !== null && <p className="muted">{progress.basis}</p>}
    <p className="training-progress-updated muted">{refreshedAt > 0 ? `Last refreshed ${new Date(refreshedAt).toLocaleTimeString()}.` : 'Waiting for the first update.'} Progress changes only when the server reports it.</p>
  </section>;
}
