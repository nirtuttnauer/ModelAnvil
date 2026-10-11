import { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight,
  ArrowUpRight,
  Database,
  Tags,
  FlaskConical,
  CheckCheck,
  CircleDollarSign,
  Activity,
  Bot,
  Workflow,
  Flame,
} from 'lucide-react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { OnboardingChecklist } from '../components/OnboardingChecklist';
import { BarChart, ChartPanel, LineChart } from '../components/Charts';
import type { UsageSummaryResponse } from './BudgetsPage';
import type { Project } from '../api/resources';

interface RecentJob {
  job_id: string;
  name: string;
  status: string;
  updated_at: string;
}

interface Evaluation {
  run_id: string;
  status: string;
  candidate_model_version: number;
  metrics: { key: string; value: number; sample_count: number; slice_name: string }[];
}

interface TrainingSummary {
  run_id: string;
  status: string;
  metrics_log?: { step: number; loss: number }[];
  execution_evidence?: { level: string; source: string };
}

const resourceIcons = {
  Datasets: Database,
  Models: Bot,
  Training: Flame,
  Workflows: Workflow,
};

const workflows = [
  {
    title: 'Prepare your data',
    description: 'Bring in source data and create a reproducible dataset version.',
    prerequisite: 'Start with a local file or a catalog source.',
    page: 'Datasets',
    action: 'Open datasets',
    icon: Database,
  },
  {
    title: 'Build better labels',
    description: 'Review samples against a rubric and freeze approved snapshots.',
    prerequisite: 'Define labels and review guidelines first.',
    page: 'Annotation',
    action: 'Open annotation',
    icon: Tags,
  },
  {
    title: 'Run an experiment',
    description: 'Pin your inputs, configure a recipe, and inspect training progress.',
    prerequisite: 'Requires a tokenizer and compatible model version.',
    page: 'Training',
    action: 'Open training',
    icon: FlaskConical,
  },
];

export function OverviewPage({
  token,
  refreshKey,
  activeProject,
  onNavigate,
  onOpenConnection,
  onProjectCreated,
  onPrerequisiteAdded,
}: {
  token: string;
  refreshKey: number;
  activeProject: Project | null;
  onNavigate: (page: string) => void;
  onOpenConnection?: () => void;
  onProjectCreated?: (project: Project) => void;
  onPrerequisiteAdded?: () => void;
}) {
  const [counts, setCounts] = useState<
    { name: string; value: number; more: boolean; total: boolean; page: string }[]
  >([]);
  const [jobs, setJobs] = useState<RecentJob[]>([]);
  const [training, setTraining] = useState<TrainingSummary[]>([]);
  const [trainingId, setTrainingId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(true);
  const [usage, setUsage] = useState<UsageSummaryResponse | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);
  const [usageLoading, setUsageLoading] = useState(true);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const resources = [
          { name: 'Datasets', path: 'datasets', page: 'Datasets' },
          { name: 'Models', path: 'models', page: 'Models' },
          { name: 'Training runs', path: 'training-runs', page: 'Training' },
          { name: 'Jobs', path: 'jobs', page: 'Workflows' },
        ];
        const pages = await Promise.all(
          resources.map((r) => apiPage<RecentJob>(`/api/v1/${r.path}/`, token, signal))
        );
        if (signal?.aborted) return;
        setCounts(
          pages.map((p, i) => ({
            name: resources[i].name,
            page: resources[i].page,
            value: p.count ?? p.results.length,
            total: p.count !== undefined,
            more: p.count === undefined && !!p.next,
          }))
        );
        setJobs(pages[3].results.slice(0, 5));
        setTraining(pages[2].results as unknown as TrainingSummary[]);
      } catch (e) {
        if (!signal?.aborted) {
          setCounts([]);
          setJobs([]);
          setTraining([]);
          setError(errorMessage(e));
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [token]
  );

  useEffect(() => {
    const c = new AbortController();
    void load(c.signal);
    return () => c.abort();
  }, [load, refreshKey]);

  useEffect(() => {
    const c = new AbortController();
    setEvidenceLoading(true);
    setEvidenceError(null);
    setEvaluations([]);
    apiPage<Evaluation>('/api/v1/evaluation-runs/', token, c.signal)
      .then((p) => {
        if (!c.signal.aborted)
          setEvaluations(p.results.filter((r) => r.status === 'completed').slice(0, 3));
      })
      .catch((e) => {
        if (!c.signal.aborted) setEvidenceError(errorMessage(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setEvidenceLoading(false);
      });
    return () => c.abort();
  }, [token, refreshKey]);

  useEffect(() => {
    const c = new AbortController();
    setUsageLoading(true);
    setUsageError(null);
    setUsage(null);
    apiRequest<UsageSummaryResponse>('/api/v1/usage-events/summary/', token, { signal: c.signal })
      .then((s) => {
        if (!c.signal.aborted) setUsage(s);
      })
      .catch((e) => {
        if (!c.signal.aborted) setUsageError(errorMessage(e));
      })
      .finally(() => {
        if (!c.signal.aborted) setUsageLoading(false);
      });
    return () => c.abort();
  }, [token, refreshKey]);

  const selectedTraining = training.find(r => r.run_id === trainingId) ?? training.find(r => r.metrics_log?.length) ?? training[0];
  const jobStates = [...new Set(jobs.map(j => j.status))].map(label => ({ label: label.replaceAll('_', ' '), value: jobs.filter(j => j.status === label).length }));

  return (
    <>
      <OnboardingChecklist
        token={token}
        refreshKey={refreshKey}
        activeProject={activeProject}
        onNavigate={onNavigate}
        onOpenConnection={onOpenConnection || (() => {})}
        onProjectCreated={onProjectCreated || (() => {})}
        onPrerequisiteAdded={onPrerequisiteAdded || (() => {})}
      />

      <div className="visualization-grid">
        <ChartPanel title="Experiment performance" description={selectedTraining ? `Run ${selectedTraining.run_id.slice(0, 8)} · ${selectedTraining.execution_evidence?.level || 'Evidence not reported'} · recorded measurements` : 'Training loss from your recorded experiments.'} action={training.length > 0 && <select aria-label="Overview training run" value={selectedTraining?.run_id || ''} onChange={e => setTrainingId(e.target.value)}>{training.map(r => <option key={r.run_id} value={r.run_id}>Run {r.run_id.slice(0, 8)} · {r.status}</option>)}</select>}>
          <LineChart series={[{ name: 'Recorded training loss', points: (selectedTraining?.metrics_log ?? []).map(m => ({ x: m.step, y: m.loss })) }]} xLabel="Training step" yLabel="Loss" />
        </ChartPanel>
        <ChartPanel title="Active work" description="Status distribution of the recent jobs shown below; up to 5 loaded records.">
          <BarChart data={jobStates} unit="Jobs" emptyMessage="Create a workflow to track its observed execution state here." />
          <button className="text-button" onClick={() => onNavigate('Workflows')}>Inspect execution <ArrowRight size={14} aria-hidden="true" /></button>
        </ChartPanel>
      </div>

      <div className="section-heading">
        <h2>Move your project forward</h2>
        <span>Choose your next step</span>
      </div>
      <div className="workflow-grid">
        {workflows.map(({ icon: Icon, ...w }) => (
          <button className="workflow-card" key={w.page} onClick={() => onNavigate(w.page)}>
            <span className="workflow-icon">
              <Icon size={19} aria-hidden="true" />
            </span>
            <div>
              <strong>{w.title}</strong>
              <p>{w.description}</p>
            </div>
            <span className="workflow-prerequisite">{w.prerequisite}</span>
            <span className="workflow-link">
              {w.action}
              <ArrowRight size={15} aria-hidden="true" />
            </span>
          </button>
        ))}
      </div>
      <div className="section-heading">
        <h2>Workspace resources</h2>
        <span>Counts describe inventory</span>
      </div>
      <ResourceState loading={loading} error={error} onRetry={() => void load()} />
      <div className="cards">
        {counts.map((c) => {
          const Icon = resourceIcons[c.page as keyof typeof resourceIcons];
          return (
            <button
              className="summary-card"
              key={c.name}
              onClick={() => onNavigate(c.page)}
            >
              <span className="summary-top">
                <span>{c.name}</span>
                <Icon size={16} aria-hidden="true" />
              </span>
              <b>
                {c.value}
                {c.more ? '+' : ''}
              </b>
              <small>
                {c.total
                  ? 'Total resources'
                  : c.more
                  ? 'Loaded page · more available'
                  : 'Resources in loaded page'}{' '}
                <ArrowUpRight size={12} aria-hidden="true" />
              </small>
            </button>
          );
        })}
      </div>
      <div className="overview-columns">
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>Recent activity</h2>
              <p>Observed states from the loaded jobs page.</p>
            </div>
            <button className="text-button" onClick={() => onNavigate('Workflows')}>
              All jobs
              <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          </div>
          <div className="panel-body">
            {loading && <ResourceState loading />}
            {error && (
              <p className="muted">Job activity is unavailable. Retry workspace resources above.</p>
            )}
            {!loading && !error && !jobs.length && (
              <div className="evidence-empty">
                <Activity size={24} aria-hidden="true" />
                <h3>Your work will appear here</h3>
                <p>Create a workflow to follow its execution and recorded attempts.</p>
                <button onClick={() => onNavigate('Workflows')}>Open workflows</button>
              </div>
            )}
            {jobs.map((j) => (
              <div className="activity-row" key={j.job_id}>
                <div>
                  <button className="text-button" onClick={() => onNavigate('Workflows')}>
                    {j.name}
                  </button>
                  <small className="id-text">
                    Updated {new Date(j.updated_at).toLocaleString()}
                  </small>
                </div>
                <span className={`state state-${j.status}`}>
                  {j.status.replaceAll('_', ' ')}
                </span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>Evaluation evidence</h2>
              <p>Completed runs in the loaded page.</p>
            </div>
            <CheckCheck size={19} aria-hidden="true" />
          </div>
          <div className="panel-body">
            <ResourceState loading={evidenceLoading} error={evidenceError} />
            {!evidenceLoading && !evidenceError && !evaluations.length && (
              <div className="evidence-empty">
                <CheckCheck size={24} aria-hidden="true" />
                <h3>No completed evaluations yet</h3>
                <p>
                  Pin a candidate and suite to start collecting evidence for your release decision.
                </p>
              </div>
            )}
            {evaluations.map((e) => (
              <div className="activity-row" key={e.run_id}>
                <div>
                  <strong>Model version record #{e.candidate_model_version}</strong>
                  <small className="id-text">Run {e.run_id.slice(0, 8)}</small>
                  {e.metrics.length ? (
                    e.metrics.slice(0, 2).map((m, i) => (
                      <p className="muted" key={i}>
                        {m.key}: {m.value.toLocaleString(undefined, { maximumFractionDigits: 4 })} ·{' '}
                        {m.sample_count} samples · {m.slice_name}
                      </p>
                    ))
                  ) : (
                    <p className="muted">No metrics recorded.</p>
                  )}
                </div>
              </div>
            ))}
            <button className="text-button" onClick={() => onNavigate('Evaluation')}>
              Review evaluations
              <ArrowRight size={14} aria-hidden="true" />
            </button>
            <p className="muted">Completion alone does not qualify a release.</p>
          </div>
        </section>
      </div>
      <div className="usage-link">
        <CircleDollarSign size={21} aria-hidden="true" />
        <div>
          <strong>Usage & budgets</strong>
          {usageError ? (
            <p>{usageError}</p>
          ) : (
            <p>
              {usageLoading
                ? 'Loading recorded usage…'
                : usage
                ? `${usage.active_reservations_count} active reservations · ${usage.total_policies} budget policies · ${usage.usage_by_unit.length} recorded resource units`
                : 'Usage unavailable'}
            </p>
          )}
        </div>
        <button className="text-button" onClick={() => onNavigate('Budgets')}>
          Inspect usage
          <ArrowUpRight size={14} aria-hidden="true" />
        </button>
      </div>
    </>
  );
}
