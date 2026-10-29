import { Button, Section, StatusBadge } from '../ui';
import { EmptyState } from '../Feedback';
import { ResourceState } from '../ResourceState';
import { activeJobDisplayName, type ActiveJob } from '../../api/active-jobs';
import { runHash } from '../../api/runs';

export function ActiveWorkList({ jobs, loading, error, onRetry, onNavigate }: { jobs: ActiveJob[]; loading: boolean; error: string | null; onRetry: () => void; onNavigate: (page: string) => void }) {
  return <Section title="Active work" actions={<Button type="button" variant="quiet" onClick={() => onNavigate('Workflows')}>All jobs</Button>}>
    <ResourceState loading={loading} error={error} onRetry={onRetry} />
    {!loading && !error && !jobs.length && <EmptyState title="No active work" description="Training, evaluations and other queued work appear here while they run." />}
    {!loading && !error && jobs.length > 0 && <ul className="work-rows">{jobs.slice(0, 5).map(job => <li key={job.job_id}>
      <span><strong>{activeJobDisplayName(job.name)}</strong><StatusBadge status={job.desired_action === 'cancel' ? 'cancellation_requested' : job.status} label={job.desired_action === 'cancel' ? 'Cancelling' : undefined} /></span>
      <a href={runHash('job', job.job_id, '#overview')}>Open run</a>
      {job.status === 'running' && job.progress != null && <progress value={job.progress} max={100} aria-label={`${activeJobDisplayName(job.name)} progress`} />}
    </li>)}</ul>}
  </Section>;
}
