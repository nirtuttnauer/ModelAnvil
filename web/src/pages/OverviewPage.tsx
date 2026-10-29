import { useCallback, useEffect, useState } from 'react';
import { Button, Disclosure } from '../components/ui';
import { TeamAccess } from '../components/TeamAccess';
import { useReviewOnly } from '../components/Access';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { OnboardingChecklist } from '../components/OnboardingChecklist';
import { NextStepCard } from '../components/overview/NextStepCard';
import { ActiveWorkList } from '../components/overview/ActiveWorkList';
import { LatestResults } from '../components/overview/LatestResults';
import { loadActiveJobs, type ActiveJob } from '../api/active-jobs';
import type { UsageSummaryResponse } from './BudgetsPage';
import type { Project } from '../api/resources';
import { nextExperimentAction, type ImprovementTraining, type OverviewEvaluation } from '../api/improvement';
import './overview.css';

export function OverviewPage({ token, refreshKey, activeProject, onNavigate, onOpenConnection, onProjectCreated, onPrerequisiteAdded, onCreateProject }: {
  token: string; refreshKey: number; activeProject: Project | null; onNavigate: (page: string) => void;
  onOpenConnection?: () => void; onProjectCreated?: (project: Project) => void; onPrerequisiteAdded?: () => void; onCreateProject?: () => void;
}) {
  const [training, setTraining] = useState<ImprovementTraining[]>([]);
  const [evaluations, setEvaluations] = useState<OverviewEvaluation[]>([]);
  const [jobs, setJobs] = useState<ActiveJob[]>([]);
  const [usage, setUsage] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState({ training: true, evaluations: true, jobs: true, usage: true });
  const [errors, setErrors] = useState<{ training: string | null; evaluations: string | null; jobs: string | null; usage: string | null }>({ training: null, evaluations: null, jobs: null, usage: null });
  const [retry, setRetry] = useState(0);

  const run = useCallback(<T,>(key: keyof typeof loading, request: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void, signal: AbortSignal) => {
    setLoading(current => ({ ...current, [key]: true })); setErrors(current => ({ ...current, [key]: null }));
    request(signal).then(value => { if (!signal.aborted) apply(value); })
      .catch(e => { if (!signal.aborted) setErrors(current => ({ ...current, [key]: errorMessage(e) })); })
      .finally(() => { if (!signal.aborted) setLoading(current => ({ ...current, [key]: false })); });
  }, []);

  useEffect(() => {
    const controller = new AbortController(); const signal = controller.signal;
    run('training', s => apiPage<ImprovementTraining>('/api/v1/training-runs/', token, s), page => setTraining(page.results), signal);
    run('evaluations', s => apiPage<OverviewEvaluation>('/api/v1/evaluation-runs/', token, s), page => setEvaluations(page.results), signal);
    run('jobs', s => loadActiveJobs(token, s), setJobs, signal);
    run('usage', s => apiRequest<UsageSummaryResponse>('/api/v1/usage-events/summary/', token, { signal: s }), setUsage, signal);
    return () => controller.abort();
  }, [token, refreshKey, retry, run]);

  const nextAction = nextExperimentAction(training, evaluations);
  const reviewOnly = useReviewOnly();
  const [teamOpen, setTeamOpen] = useState(false);
  return <div className="overview-page">
    {reviewOnly ? <p className="muted">Review workspace: your role lets you inspect evidence and submit reviews. Setup and training actions are hidden.</p> : <>
    <NextStepCard action={nextAction} loading={loading.training || loading.evaluations} error={!!(errors.training || errors.evaluations)} hasRuns={training.length > 0} onNavigate={onNavigate} />
    <OnboardingChecklist
      token={token}
      refreshKey={refreshKey}
      activeProject={activeProject}
      onNavigate={onNavigate}
      onOpenConnection={onOpenConnection || (() => {})}
      onCreateProject={onCreateProject || (() => {})}
      onProjectCreated={onProjectCreated}
      onPrerequisiteAdded={onPrerequisiteAdded}
    />
    </>}
    <div className="overview-columns">
      <ActiveWorkList jobs={jobs} loading={loading.jobs} error={errors.jobs} onRetry={() => setRetry(value => value + 1)} onNavigate={onNavigate} />
      <LatestResults evaluations={evaluations} loading={loading.evaluations} error={errors.evaluations} onNavigate={onNavigate} />
    </div>
    <Disclosure summary="Team access" variant="card" open={teamOpen} onToggle={event => setTeamOpen(event.currentTarget.open)}>{teamOpen && <TeamAccess token={token} refreshKey={refreshKey} />}</Disclosure>
    <p className="overview-usage">
      {errors.usage ? errors.usage : loading.usage ? 'Loading recorded usage…' : usage
        ? `${usage.active_reservations_count} active ${usage.active_reservations_count === 1 ? 'reservation' : 'reservations'} · ${usage.total_policies} budget ${usage.total_policies === 1 ? 'policy' : 'policies'}`
        : 'Usage unavailable'}
      <Button type="button" variant="quiet" size="sm" onClick={() => onNavigate('Budgets')}>Budgets</Button>
    </p>
  </div>;
}
