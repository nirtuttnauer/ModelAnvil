import { Button, Section, StatusBadge } from '../ui';
import { EmptyState } from '../Feedback';
import { ResourceState } from '../ResourceState';
import { runHash } from '../../api/runs';
import type { OverviewEvaluation } from '../../api/improvement';
import { evidenceTitle } from '../../api/evidence-label';

function outcome(evaluation: OverviewEvaluation): { status: string; label: string } {
  const decision = evaluation.improvement_decision?.outcome;
  return decision === 'accept' ? { status: 'approved', label: 'Accepted' } : decision === 'reject' ? { status: 'rejected', label: 'Rejected' } : { status: 'unknown', label: 'Undecided' };
}

export function LatestResults({ evaluations, loading, error, onNavigate }: { evaluations: OverviewEvaluation[]; loading: boolean; error: string | null; onNavigate: (page: string) => void }) {
  const completed = evaluations.filter(e => e.status === 'completed').slice(0, 3);
  const running = evaluations.filter(e => ['pending', 'running'].includes(e.status)).length;
  return <Section title="Latest results" actions={<Button type="button" variant="quiet" onClick={() => onNavigate('Evaluation')}>Evaluation</Button>}>
    <ResourceState loading={loading} error={error} />
    {!loading && !error && !completed.length && !running && <EmptyState title="No comparisons yet" description="Compare a trained model with its base model on held-out examples." />}
    {!loading && !error && (completed.length > 0 || running > 0) && <ul className="work-rows">
      {completed.map(e => { const result = outcome(e); const metric = e.metrics[0]; return <li key={e.run_id}>
        <span><strong>Candidate version {e.candidate_model_version}</strong><StatusBadge status={result.status} label={result.label} /></span>
        <a href={runHash('evaluation', e.run_id, '#overview')}>Review</a>
        {metric && <small>{metric.key} {metric.value.toLocaleString(undefined, { maximumFractionDigits: 3 })} · {metric.sample_count} samples · {metric.slice_name}</small>}{e.execution_evidence && <small>{evidenceTitle(e.execution_evidence.level)} · {e.execution_evidence.source}</small>}
      </li>; })}
      {running > 0 && <li><span><small>{running === 1 ? '1 comparison running' : `${running} comparisons running`}</small></span><a href="#evaluation">Progress</a></li>}
    </ul>}
  </Section>;
}
