import { Identifier } from '../components/Identifier';
import { LocalMeasurements } from '../components/LocalMeasurements';
import { PrivacySettings } from '../components/PrivacySettings';
import { Badge, Button, Card, Field, MetricSummary } from '../components/ui';
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
import { runHash } from '../api/runs';

interface RecentJob {
  job_id: string;
  name: string;
  status: string;
  updated_at: string;
}

interface Evaluation {
  execution_evidence?: { level: string; source: string };
  improvement_decision?: { outcome: string; decision_id: string } | null;
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
  runtime?: { execution_mode?: string; setup_check?: boolean };
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
    description: 'Choose a pretrained model and fine-tune it on your examples.',
    prerequisite: 'Guided setup supplies the matching model and local training resources.',
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
  const [canInvite, setCanInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [inviteError, setInviteError] = useState('');
  const [inviteBusy, setInviteBusy] = useState(false);

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
        if (!c.signal.aborted) setEvaluations(p.results.slice(0, 8));
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

  useEffect(() => {
    if (token !== 'session') return;
    const controller = new AbortController();
    apiRequest<{ can_invite?: boolean }>('/api/v1/accounts/status/', token, { signal: controller.signal })
      .then(status => { if (!controller.signal.aborted) setCanInvite(!!status.can_invite); })
      .catch(() => { if (!controller.signal.aborted) setCanInvite(false); });
    return () => controller.abort();
  }, [token, refreshKey]);

  async function inviteTeammate() {
    setInviteBusy(true); setInviteError(''); setInviteCode('');
    try {
      const result = await apiRequest<{ invite_code: string }>('/api/v1/accounts/invitations/', token, {
        method: 'POST', body: JSON.stringify({ email: inviteEmail.trim() }),
      });
      setInviteCode(result.invite_code);
    } catch (reason) { setInviteError(errorMessage(reason)); }
    finally { setInviteBusy(false); }
  }

  const selectedTraining = training.find(r => r.run_id === trainingId) ?? training.find(r => r.metrics_log?.length) ?? training[0];
  const jobStates = [...new Set(jobs.map(j => j.status))].map(label => ({ label: label.replaceAll('_', ' '), value: jobs.filter(j => j.status === label).length }));
  const completedEvaluations = evaluations.filter(item => item.status === 'completed');
  const realTraining = training.filter(run => run.execution_evidence?.level === 'integrated_execution' && run.runtime?.execution_mode !== 'simulation' && !run.runtime?.setup_check);
  const activeTraining = realTraining.find(run => ['pending', 'running'].includes(run.status));
  const finishedTraining = realTraining.find(run => run.status === 'completed');
  const openComparison = completedEvaluations.find(item => item.execution_evidence?.level === 'integrated_execution' && !item.improvement_decision);
  const recordedDecision = completedEvaluations.find(item => item.improvement_decision);
  const next = activeTraining ? { title: 'Training is running', body: 'Follow this run. The next step is to compare the candidate with the base model.', label: 'Follow training', page: 'Training' }
    : openComparison ? { title: 'Record an accept or reject', body: 'The comparison is ready. Recording a choice does not deploy the model.', label: 'Record the decision', page: 'Training' }
    : finishedTraining && !recordedDecision ? { title: 'Compare the candidate with the base model', body: 'Chat and a lower loss are not evidence that the model improved.', label: 'Compare and decide', page: 'Training' }
    : recordedDecision ? { title: 'A decision is recorded', body: 'Local measurements below include that accept or reject. A downloaded model is not deployed.', label: 'Review the comparison', page: 'Evaluation' }
    : { title: 'Fine-tune an LLM with your own dataset', body: 'The guided flow prepares a pretrained model and local compute for you.', label: 'Start guided fine-tuning', page: 'Training' };

  return (
    <>
      <Card className="panel"><div className="panel-body"><h2>{next.title}</h2><p>{next.body}</p><Button className="primary" onClick={() => onNavigate(next.page)}>{next.label}</Button></div></Card>
      {canInvite && <Card className="panel"><div className="panel-body"><h2>Invite one teammate</h2><p>They can review the candidate and record the accept or reject decision. This workspace can have one teammate.</p>
        <form className="guided-form" onSubmit={event => { event.preventDefault(); void inviteTeammate(); }}><label>Teammate email<Field type="email" required value={inviteEmail} disabled={inviteBusy} onChange={event => setInviteEmail(event.target.value)} /></label><Button className="primary" disabled={inviteBusy || !inviteEmail.trim()}>{inviteBusy ? 'Creating invitation…' : 'Create invitation'}</Button></form>
        {inviteError && <p role="alert">{inviteError}</p>}
        {inviteCode && <p role="status">Share this one-time code. It is shown only now: <strong>{inviteCode}</strong></p>}
      </div></Card>}
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
        <ChartPanel title="Experiment performance" description={selectedTraining ? `Training run ${training.indexOf(selectedTraining) + 1} · ${selectedTraining.execution_evidence?.level || 'Evidence not reported'} · recorded measurements` : 'Training loss from your recorded experiments.'} action={training.length > 0 && <select aria-label="Overview training run" value={selectedTraining?.run_id || ''} onChange={e => setTrainingId(e.target.value)}>{training.map((r, index) => <option key={r.run_id} value={r.run_id}>Training run {index + 1} · {r.status}</option>)}</select>}>
          {selectedTraining && <Identifier value={selectedTraining.run_id} label="Run ID" />}
          <LineChart series={[{ name: 'Recorded training loss', points: (selectedTraining?.metrics_log ?? []).map(m => ({ x: m.step, y: m.loss })) }]} xLabel="Training step" yLabel="Loss" />
        </ChartPanel>
        <ChartPanel title="Active work" description="Status distribution of the recent jobs shown below; up to 5 loaded records.">
          <BarChart data={jobStates} unit="Jobs" emptyMessage="Create a workflow to track its observed execution state here." />
          <Button className="text-button" onClick={() => onNavigate('Workflows')}>Inspect execution <ArrowRight size={14} aria-hidden="true" /></Button>
        </ChartPanel>
      </div>

      <details className="workspace-details">
        <summary>Other workflows</summary>
        <div className="workflow-grid">
          {workflows.map(({ icon: Icon, ...w }) => (
            <Button className="workflow-card" key={w.page} onClick={() => onNavigate(w.page)}>
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
            </Button>
          ))}
        </div>
      </details>
      <div className="section-heading">
        <h2>Workspace resources</h2>
        <span>Counts describe inventory</span>
      </div>
      <ResourceState loading={loading} error={error} onRetry={() => void load()} />
      <div className="cards">
        {counts.map((c) => {
          const Icon = resourceIcons[c.page as keyof typeof resourceIcons];
          return (
            <MetricSummary
              key={c.name}
              onClick={() => onNavigate(c.page)}
              label={c.name}
              icon={<Icon size={16} aria-hidden="true" />}
              value={<>{c.value}{c.more ? '+' : ''}</>}
              detail={<>
                {c.total
                  ? 'Total resources'
                  : c.more
                  ? 'Loaded page · more available'
                  : 'Resources in loaded page'}{' '}
                <ArrowUpRight size={12} aria-hidden="true" />
              </>}
            />
          );
        })}
      </div>
      <div className="overview-columns">
        <Card className="panel">
          <div className="panel-title">
            <div>
              <h2>Recent activity</h2>
              <p>Observed states from the loaded jobs page.</p>
            </div>
            <Button className="text-button" onClick={() => onNavigate('Workflows')}>
              All jobs
              <ArrowUpRight size={14} aria-hidden="true" />
            </Button>
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
                <p>Training and evaluation jobs appear here after you start a fine-tune.</p>
                <Button onClick={() => onNavigate('Training')}>Start fine-tuning</Button>
              </div>
            )}
            {jobs.map((j) => (
              <div className="activity-row" key={j.job_id}>
                <div>
                  <a className="text-button" href={runHash('job', j.job_id)}>
                    {j.name}
                  </a>
                  <small className="id-text">
                    Updated {new Date(j.updated_at).toLocaleString()}
                  </small>
                </div>
                <Badge className={`state state-${j.status}`}>
                  {j.status.replaceAll('_', ' ')}
                </Badge>
              </div>
            ))}
          </div>
        </Card>
        <Card className="panel">
          <div className="panel-title">
            <div>
              <h2>Evaluation evidence</h2>
              <p>Completed runs in the loaded page.</p>
            </div>
            <CheckCheck size={19} aria-hidden="true" />
          </div>
          <div className="panel-body">
            <ResourceState loading={evidenceLoading} error={evidenceError} />
            {!evidenceLoading && !evidenceError && !completedEvaluations.length && (
              <div className="evidence-empty">
                <CheckCheck size={24} aria-hidden="true" />
                <h3>No completed evaluations yet</h3>
                <p>
                  Pin a candidate and suite to start collecting evidence for your release decision.
                </p>
              </div>
            )}
            {completedEvaluations.map((e) => (
              <div className="activity-row" key={e.run_id}>
                <div>
                  <strong>Candidate model</strong> <Identifier value={String(e.candidate_model_version)} label="Candidate model record ID" />
                  <Identifier value={e.run_id} label="Evaluation run ID" />
                  <small className="id-text">{e.execution_evidence?.level || 'Unknown execution evidence'} · {e.execution_evidence?.source || 'Execution provenance not recorded'}</small>
                  <a href={runHash('evaluation', e.run_id)}>Inspect this evaluation</a>
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
            <Button className="text-button" onClick={() => onNavigate('Evaluation')}>
              Review evaluations
              <ArrowRight size={14} aria-hidden="true" />
            </Button>
            <p className="muted">Completion alone does not qualify a release.</p>
          </div>
        </Card>
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
        <Button className="text-button" onClick={() => onNavigate('Budgets')}>
          Inspect usage
          <ArrowUpRight size={14} aria-hidden="true" />
        </Button>
      </div>
      <LocalMeasurements token={token} />
      <PrivacySettings token={token} />
    </>
  );
}
