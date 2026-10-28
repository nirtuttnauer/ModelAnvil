import { Identifier } from '../components/Identifier';
import { Badge, Button, MultilineField, Notice, RecordTable } from '../components/ui';
import { resourceHash } from '../api/resource-routes';
import { useDraft, DraftStatus } from '../components/Draft';
import { DataInspector, DataValue } from '../components/DataInspector';
import { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw, XCircle } from 'lucide-react';
import { apiPage, apiRequest, errorMessage, nextPagePath, type ApiPage } from '../api/client';
import { attemptsPath, detailPath, runHash, sourceHash, type RunKind } from '../api/runs';
import { ResourceState } from '../components/ResourceState';
import { BarChart, ChartPanel, EventTimeline, LineChart } from '../components/Charts';
import './runs.css';

interface Bounded<T> {
  total: number;
  truncated: boolean;
  rows: T[];
}

interface Checkpoint {
  checkpoint_id: string;
  step: number;
  state_digest: string;
  is_valid: boolean;
  contract_digest: string | null;
  weights_sha256: string | null;
  created_at: string;
}

interface ResumeCandidate {
  available: boolean;
  reason: string;
  checkpoint_id: string | null;
  step: number | null;
  state_digest: string | null;
  contract_digest: string | null;
}

interface Attempt {
  attempt_id: string;
  job_id: string;
  worker: string | null;
  worker_status: string | null;
  status: string;
  progress: number;
  error: string;
  lease_expires_at: string | null;
  started_at: string;
  completed_at: string | null;
  has_result: boolean;
}

interface RunDetail {
  kind: RunKind;
  id: string;
  name: string;
  project: string | null;
  execution_mode: string;
  observed: {
    state: string;
    job_state: string | null;
    current_step: number | null;
    total_steps: number | null;
    progress: number | null;
    latest_loss: number | null;
    attempts: string | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    updated_at: string;
  };
  desired: { action: string; acknowledged: boolean; note: string };
  ownership: {
    state: string;
    worker: string | null;
    worker_status: string | null;
    lease_expires_at: string | null;
    reason: string;
  };
  inputs: Record<string, unknown>;
  metrics: Bounded<Record<string, unknown>> & { latest_loss: number | null };
  checkpoints: (Bounded<Checkpoint> & { resume_candidate: ResumeCandidate }) | null;
  usage: {
    reservations: Array<{
      reservation_id: string;
      policy_name: string;
      unit: string;
      state: string;
      estimated_amount: string;
      settled_amount: string | null;
    }>;
    events: Array<{ usage_id: string; quantity: string; unit: string; occurred_at: string }>;
    events_truncated: boolean;
  };
  links: Record<string, string | string[] | null>;
  evidence: { level: string; source: string } | null;
  actions: {
    cancel: {
      available: boolean;
      requested: boolean;
      acknowledged: boolean;
      endpoint: string | null;
      blocked_by: string[];
    };
    resume: {
      available: boolean;
      endpoint?: string;
      recovery_run_id?: string | null;
      blocked_by: string[];
      permission: { role: string | null; required: string; satisfied: boolean };
      checkpoint?: ResumeCandidate;
      budget?: { state: string; reservable: boolean; reason: string };
      operator_path?: string;
      preserves_history: string;
    };
  };
  generated_at: string;
}

const POLL_MS = 5000;
const MAX_POLL_MS = 30000;
const TERMINAL = ['completed', 'failed', 'cancelled', 'succeeded'];


function age(from: number | null, now: number) {
  if (from === null) return 'never';
  const seconds = Math.max(0, Math.round((now - from) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes}m ago` : `${Math.round(minutes / 60)}h ago`;
}

function linkId(value: string | string[] | null | undefined) {
  return Array.isArray(value) ? value[0] ?? '' : (value ?? '');
}

export function RunDetailPage({
  token,
  refreshKey = 0,
  kind,
  runId,
}: {
  token: string;
  refreshKey?: number;
  kind: RunKind;
  runId: string;
}) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [pollMs, setPollMs] = useState(POLL_MS);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [attemptsNext, setAttemptsNext] = useState<string | null>(null);
  const [attemptsError, setAttemptsError] = useState<string | null>(null);
  const [attemptsLoading, setAttemptsLoading] = useState(false);
  const [fullMetrics, setFullMetrics] = useState<Record<string, unknown>[] | null>(null);
  const [historyError, setHistoryError] = useState('');
  const [busy, setBusy] = useState(false);
  const [recoveryReview, setRecoveryReview] = useState<{ available: boolean; blocked_by: string[]; checkpoint_id: string; step: number; remaining_steps: number; policy_id: string; pins: Record<string, unknown>; replay_limits: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [cancelRequested, setCancelRequested] = useState(false);
  const noteDraft = useDraft('run-note', { note: '' }, `${kind}:${runId}`);
  const [note, setNote] = noteDraft.field('note');
  const hasDetail = useRef(false);

  const load = useCallback(
    async (signal?: AbortSignal, quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const next = await apiRequest<RunDetail>(detailPath(kind, runId), token, { signal });
        if (signal?.aborted) return;
        hasDetail.current = true;
        setDetail(next);
        setError(null);
        setConnectionError(null);
        setUpdatedAt(Date.now());
        setPollMs(POLL_MS);
      } catch (failure) {
        if (signal?.aborted) return;
        if (quiet && hasDetail.current) {
          setConnectionError(errorMessage(failure));
          setPollMs((value) => Math.min(value * 2, MAX_POLL_MS));
        } else {
          setError(errorMessage(failure));
          setDetail(null);
          hasDetail.current = false;
        }
      } finally {
        if (!signal?.aborted && !quiet) setLoading(false);
      }
    },
    [token, kind, runId]
  );

  useEffect(() => {
    const controller = new AbortController();
    hasDetail.current = false;
    setDetail(null);
    setError(null);
    setConnectionError(null);
    setUpdatedAt(null);
    setPollMs(POLL_MS);
    setAttempts([]);
    setAttemptsNext(null);
    setAttemptsError(null);
    setCancelRequested(false);
    void load(controller.signal);
    return () => controller.abort();
  }, [load, kind, runId]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const state = detail?.observed.state;
  useEffect(() => {
    if (!detail || !state || TERMINAL.includes(state)) return;
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void load(undefined, true);
    }, pollMs);
    return () => clearInterval(timer);
  }, [detail, state, pollMs, load]);

  useEffect(() => {
    if (!refreshKey) return;
    const controller = new AbortController();
    void load(controller.signal, hasDetail.current);
    return () => controller.abort();
  }, [refreshKey, load]);

  const loadAttempts = useCallback(
    async (path: string, append: boolean, signal?: AbortSignal) => {
      setAttemptsLoading(true);
      try {
        const page: ApiPage<Attempt> = await apiPage<Attempt>(path, token, signal);
        if (signal?.aborted) return;
        if (append) {
          setAttempts((current) => [...current, ...page.results]);
        } else {
          setAttempts((current) => {
            const seen = new Set<string>();
            return [...page.results, ...current].filter((row) => {
              if (seen.has(row.attempt_id)) return false;
              seen.add(row.attempt_id);
              return true;
            });
          });
        }
        if (append) setAttemptsNext(page.next || null);
        setAttemptsError(null);
      } catch (failure) {
        if (!signal?.aborted) setAttemptsError(errorMessage(failure));
      } finally {
        if (!signal?.aborted) setAttemptsLoading(false);
      }
    },
    [token]
  );

  const attemptFingerprint = `${detail?.observed.updated_at ?? ''}|${detail?.observed.attempts ?? ''}`;

  useEffect(() => {
    if (!detail?.links.job) return;
    const controller = new AbortController();
    void loadAttempts(attemptsPath(kind, runId), false, controller.signal);
    return () => controller.abort();
    // attemptFingerprint changes only when the recorded run actually moved.
  }, [kind, runId, attemptFingerprint, loadAttempts]);

  async function requestCancellation() {
    const endpoint = detail?.actions.cancel.endpoint;
    if (!detail || !endpoint || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      await apiRequest(endpoint, token, { method: 'POST', body: '{}' });
      setCancelRequested(true);
      await load(undefined, true);
      if (detail?.links.job) await loadAttempts(attemptsPath(kind, runId), false);
    } catch (failure) {
      setActionError(errorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function reviewRecovery() {
    if (!detail?.actions.resume.endpoint) return;
    setBusy(true); setActionError(null);
    try { setRecoveryReview(await apiRequest(detail.actions.resume.endpoint, token)); }
    catch (e) { setActionError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function resumeRecovery() {
    if (!recoveryReview || !detail?.actions.resume.endpoint) return;
    setBusy(true); setActionError(null);
    try {
      const child = await apiRequest<{ run_id: string }>(detail.actions.resume.endpoint, token, { method: 'POST', body: JSON.stringify({ checkpoint_id: recoveryReview.checkpoint_id, budget_policy_id: recoveryReview.policy_id }) });
      window.location.hash = runHash('training', child.run_id);
    } catch (e) { setActionError(errorMessage(e)); setRecoveryReview(null); await load(undefined, true); }
    finally { setBusy(false); }
  }

  function updateNote(value: string) {
    setNote(value);
  }

  const cancel = detail?.actions.cancel;
  const resume = detail?.actions.resume;
  const requested = cancelRequested || Boolean(cancel?.requested);
  const acknowledged = Boolean(cancel?.acknowledged) || detail?.observed.state === 'cancelled';
  const live = Boolean(detail) && !TERMINAL.includes(state ?? '');
  const stale = updatedAt !== null && now - updatedAt > pollMs * 2;
  const links = detail?.links ?? {};
  const displayName = detail?.name?.replace(/^(Training run|Evaluation) [a-f0-9]{8}$/i, kind === 'training' ? 'Training run' : 'Evaluation run');

  return (
    <div className="runs-page">
      <section className="runs-panel">
        <div className="runs-heading">
          <div>
            <h2>{displayName ?? 'Run detail'}</h2>
            <p className="runs-hint">
              {kind === 'training'
                ? 'Training run'
                : kind === 'evaluation'
                ? 'Evaluation run'
                : 'Durable job'}{' '}
              <Identifier value={runId} label="Run ID" />
              {detail?.project && (
                <>
                  {' '}
                  · project <Identifier value={detail.project} label="Project ID" />
                </>
              )}
            </p>
          </div>
          <div className="actions">
            <Button type="button" onClick={() => void load()}>
              <RefreshCw size={15} aria-hidden="true" /> Refresh
            </Button>
            <a href={sourceHash(window.location.hash, kind === 'training' ? '#training' : kind === 'evaluation' ? '#evaluation' : '#workflows')}>Back to {kind === 'training' ? 'training' : kind === 'evaluation' ? 'evaluation' : 'workflows'}</a>
          </div>
        </div>

        <ResourceState loading={loading} error={error} onRetry={() => void load()} />

        <div className={`runs-freshness ${connectionError ? 'offline' : live && stale ? 'stale' : ''}`}>
          <span>
            {connectionError
              ? 'Live updates interrupted'
              : `Last successful update ${age(updatedAt, now)}`}
          </span>
          <span className="muted">Polling every {Math.round(pollMs / 1000)}s</span>
          <Badge className={`state state-${live ? 'running' : 'paused'}`}>
            {!detail ? 'Waiting for run data' : live ? 'Live updates on' : 'Terminal state — polling stopped'}
          </Badge>
        </div>
        <p className="runs-note-status" role="status" aria-live="polite">
          {connectionError
            ? `Live updates interrupted: ${connectionError} The last recorded values stay on screen.`
            : live && stale
            ? 'The last successful update is older than two poll intervals.'
            : !detail
            ? 'Load a durable run record to inspect its execution state.'
            : live
            ? 'Live updates are current.'
            : 'This run is terminal, so polling stopped.'}
        </p>

        {detail && (
          <>
            <div className="runs-states">
              <div className="runs-state-card">
                <h3>
                  Observed state{' '}
                  <Badge className={`state state-${detail.observed.state}`}>{detail.observed.state}</Badge>
                </h3>
                <dl className="runs-kv">
                  <div>
                    <dt>Progress</dt>
                    <dd>
                      {detail.observed.current_step === null
                        ? 'Not tracked by this run type'
                        : `${detail.observed.current_step} / ${detail.observed.total_steps}`}
                    </dd>
                  </div>
                  <div>
                    <dt>Attempts</dt>
                    <dd>{detail.observed.attempts ?? 'No durable job'}</dd>
                  </div>
                  {detail.observed.job_state &&
                    detail.observed.job_state !== detail.observed.state && (
                      <div>
                        <dt>Linked job state (differs from this record)</dt>
                        <dd>
                          <Badge
                            className={`state state-${detail.observed.job_state}`}
                          >
                            {detail.observed.job_state}
                          </Badge>
                        </dd>
                      </div>
                    )}
                  <div>
                    <dt>Recorded update</dt>
                    <dd>{new Date(detail.observed.updated_at).toLocaleString()}</dd>
                  </div>
                </dl>
              </div>
              <div className="runs-state-card">
                <h3>
                  Desired state{' '}
                  <Badge className={`state state-${requested ? 'pending' : 'ready'}`}>
                    {detail.desired.action}
                  </Badge>
                </h3>
                <p className="muted">{detail.desired.note}</p>
                <dl className="runs-kv">
                  <div>
                    <dt>Worker acknowledgement</dt>
                    <dd>
                      {acknowledged
                        ? 'Acknowledged'
                        : requested
                        ? 'Requested — not yet acknowledged by the worker'
                        : detail.desired.action === 'cancel'
                        ? 'Not requested'
                        : detail.desired.acknowledged
                        ? 'Acknowledged'
                        : 'Pending'}
                    </dd>
                  </div>
                  <div>
                    <dt>Ownership</dt>
                    <dd>
                      {detail.ownership.state}
                      {detail.ownership.worker ? ` · ${detail.ownership.worker}` : ''}
                    </dd>
                  </div>
                  <div>
                    <dt>Lease</dt>
                    <dd>
                      {detail.ownership.lease_expires_at
                        ? new Date(detail.ownership.lease_expires_at).toLocaleString()
                        : 'No active lease'}
                    </dd>
                  </div>
                </dl>
                <p className="runs-hint">{detail.ownership.reason}</p>
              </div>
            </div>

            {actionError && (
              <Notice tone="error" className="notice error" role="alert">
                {actionError}
              </Notice>
            )}

            <div className="runs-actions">
              <Button
                type="button"
                disabled={!cancel?.available || busy || requested}
                onClick={() => void requestCancellation()}
              >
                <XCircle size={15} aria-hidden="true" />
                {acknowledged
                  ? 'Cancellation acknowledged'
                  : requested
                  ? 'Cancellation requested'
                  : 'Request cancellation'}
              </Button>
              {(cancel?.blocked_by ?? []).map((reason) => (
                <span key={reason} className="runs-hint">
                  {reason}
                </span>
              ))}
            </div>


          </>
        )}
      </section>

      {detail && (
        <>
          <details className="workspace-details"><summary>Run charts and timeline</summary><div className="visualization-grid">
            {kind === 'training' && <ChartPanel title="Recorded loss" description={`Exact metric steps · evidence: ${detail.evidence?.level ?? 'not reported'}`}>
              <LineChart series={[
                { name: 'Training loss', points: detail.metrics.rows.flatMap(row => typeof row.step === 'number' && typeof row.loss === 'number' ? [{ x: row.step, y: row.loss }] : []) },
                { name: 'Validation loss', points: detail.metrics.rows.flatMap(row => typeof row.step === 'number' && typeof row.validation_loss === 'number' ? [{ x: row.step, y: row.validation_loss }] : []) },
              ].filter(series => series.points.length)} yLabel="Loss" />
              {detail.metrics.truncated && <p className="runs-hint">The API returned a bounded metric window. Inspect recorded metrics below for its total.</p>}
            </ChartPanel>}
            {kind === 'evaluation' && <ChartPanel title="Evaluation measurements" description="Frozen scoring metrics and case coverage; inspect sample counts and uncertainty below.">
              <BarChart data={detail.metrics.rows.filter(row => typeof row.value === 'number').map(row => ({ label: String(row.key || 'Metric'), value: Number(row.value) }))} />
            </ChartPanel>}
            <ChartPanel title="Execution record" description="Recorded timestamps and the current observed state.">
              <EventTimeline events={[
                { label: 'Created', detail: new Date(detail.observed.created_at).toLocaleString() },
                ...(detail.observed.started_at ? [{ label: 'Execution started', detail: new Date(detail.observed.started_at).toLocaleString() }] : []),
                { label: 'Current observed state', status: detail.observed.state, detail: new Date(detail.observed.updated_at).toLocaleString() },
                ...(detail.observed.completed_at ? [{ label: 'Execution ended', detail: new Date(detail.observed.completed_at).toLocaleString() }] : []),
              ]} />
              <p className="runs-hint">Execution mode: {detail.execution_mode}. Worker: {detail.ownership.worker ?? 'not assigned'}.</p>
            </ChartPanel>
          </div>
          </details>
          <section className="runs-panel runs-recovery">
            <h2>Next actions and blockers</h2>
            {resume?.available && <Button type="button" disabled={busy || stale || !!connectionError} onClick={() => void reviewRecovery()}>Review checkpoint recovery</Button>}
            {resume?.recovery_run_id && <a href={runHash('training', resume.recovery_run_id)}>Open linked recovery execution</a>}
            {recoveryReview && <div className="detail-box" aria-label="Recovery review">
              <h3>Resume from step {recoveryReview.step}</h3><p>Reserve {recoveryReview.remaining_steps} remaining training steps. Prior committed usage stays on the parent execution.</p>
              <p>{recoveryReview.replay_limits}</p><DataInspector value={recoveryReview.pins} />
              {recoveryReview.blocked_by.map(reason => <p key={reason} role="alert">{reason}</p>)}
              <div className="actions"><Button className="primary" disabled={busy || !recoveryReview.available} onClick={() => void resumeRecovery()}>Resume from verified checkpoint</Button><Button disabled={busy} onClick={() => setRecoveryReview(null)}>Close recovery review</Button></div>
            </div>}
            <p className="runs-hint">
              Resume and retry eligibility is re-evaluated from recorded evidence on every load: the caller role,
              the committed checkpoint's runtime contract and cursor, and the budget state. Nothing here restarts
              work on its own.
            </p>
            <ul className="runs-blockers">
              {(resume?.blocked_by ?? []).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            {resume?.budget && (
              <p className="runs-hint">
                Budget ({resume.budget.state}): {resume.budget.reason}
              </p>
            )}
            {resume?.checkpoint && (
              <p className="runs-hint">
                Checkpoint: {resume.checkpoint.reason}
                {resume.checkpoint.step === null ? '' : ` (step ${resume.checkpoint.step})`}
              </p>
            )}
            {resume?.operator_path && <p className="runs-hint">{resume.operator_path}</p>}
            <p className="runs-hint">{resume?.preserves_history}</p>
          </section>
          <section className="runs-panel">
            <h2>Linked records</h2>
            <p className="runs-hint">
              Every link below opens the record this run pinned, produced or was executed under.
            </p>
            <div className="runs-links">
              {links.job && <a href={runHash('job', linkId(links.job))}>Durable job</a>}
              {links.training_run && (
                <a href={runHash('training', linkId(links.training_run))}>Training run</a>
              )}
              {links.output_model_version && <a href={resourceHash('model-version', linkId(links.output_model_version))}>Trained candidate</a>}
              {links.base_model_version && <a href={resourceHash('model-version', linkId(links.base_model_version))}>Pinned base version</a>}
              {links.recovery_parent && <a href={runHash('training', linkId(links.recovery_parent))}>Parent execution</a>}
              {links.model_version && <a href={resourceHash('model-version', linkId(links.model_version))}>Model version</a>}
              {links.dataset_revision && <a href={resourceHash('dataset-revision', linkId(links.dataset_revision))}>Dataset revision</a>}
              {Array.isArray(links.evaluation_runs) &&
                links.evaluation_runs.map((id, index) => (
                  <span key={id}><a href={runHash('evaluation', id)}>Evaluation run {index + 1}</a> <Identifier value={id} label="Evaluation run ID" /></span>
                ))}
              <a href="#infrastructure">Worker pools</a>
              <a href="#budgets">Budgets</a>
              <a href="#audit">Audit</a>
            </div>
          </section>

          <div className="runs-columns">
            <section className="runs-panel">
              <h2>Pinned inputs</h2>
              <DataInspector value={detail.inputs} />
            </section>

            <section className="runs-panel">
              <h2>Recorded evidence</h2>
              {detail.evidence ? (
                <dl className="runs-kv">
                  <div>
                    <dt>Level</dt>
                    <dd>{detail.evidence.level}</dd>
                  </div>
                  <div>
                    <dt>Source</dt>
                    <dd>{detail.evidence.source}</dd>
                  </div>
                  <div>
                    <dt>Execution mode</dt>
                    <dd>{detail.execution_mode}</dd>
                  </div>
                  <div>
                    <dt>Projection generated</dt>
                    <dd>{new Date(detail.generated_at).toLocaleString()}</dd>
                  </div>
                </dl>
              ) : (
                <p className="runs-empty">
                  Durable jobs carry no runtime evidence level; the worker outcome is recorded on the attempts
                  below.
                </p>
              )}
              <h3>Budget reservation</h3>
              {detail.usage.reservations.length === 0 ? (
                <p className="runs-empty">No budget reservation is recorded for this run.</p>
              ) : (
                <ul>
                  {detail.usage.reservations.map((item) => (
                    <li key={item.reservation_id}>
                      {item.policy_name}: {item.state} · estimated {item.estimated_amount} {item.unit}
                      {item.settled_amount ? ` · settled ${item.settled_amount}` : ''}
                    </li>
                  ))}
                </ul>
              )}
              <h3>Usage events</h3>
              {detail.usage.events.length === 0 ? (
                <p className="runs-empty">No usage events recorded.</p>
              ) : (
                <>
                  <ul>
                    {detail.usage.events.map((event) => (
                      <li key={event.usage_id}>
                        {new Date(event.occurred_at).toLocaleString()} · {event.quantity} {event.unit}
                      </li>
                    ))}
                  </ul>
                  {detail.usage.events_truncated && (
                    <p className="runs-hint">Only the most recent usage events are loaded.</p>
                  )}
                </>
              )}
            </section>
          </div>

          {Boolean(detail.links.job) && (
            <section className="runs-panel">
              <h2>Worker attempts ({attempts.length} loaded)</h2>
              <p className="runs-hint">
                Attempts are append-only: every recorded failure stays visible after any later action.
              </p>
              <ResourceState
                error={attemptsError}
                onRetry={() => void loadAttempts(attemptsPath(kind, runId), false)}
              />
              {attempts.length === 0 && !attemptsLoading && (
                <p className="runs-empty">No worker attempt has claimed this job.</p>
              )}
              {attempts.length > 0 && (
                <div className="table-scroll" tabIndex={0}>
                  <RecordTable className="resource-table runs-attempts">
                    <thead>
                      <tr>
                        <th scope="col">Attempt</th>
                        <th scope="col">Status</th>
                        <th scope="col">Worker</th>
                        <th scope="col">Progress</th>
                        <th scope="col">Started</th>
                        <th scope="col">Recorded outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {attempts.map((attempt, index) => (
                        <tr key={attempt.attempt_id}>
                          <td>
                            Attempt {index + 1} <Identifier value={attempt.attempt_id} label="Attempt ID" />
                            <small className="id-text">
                              {attempt.lease_expires_at
                                ? `lease until ${new Date(attempt.lease_expires_at).toLocaleTimeString()}`
                                : 'no lease'}
                            </small>
                          </td>
                          <td>
                            <Badge className={`state state-${attempt.status}`}>{attempt.status}</Badge>
                          </td>
                          <td>
                            {attempt.worker ?? 'Unassigned'}
                            {attempt.worker_status && (
                              <small className="id-text">{attempt.worker_status}</small>
                            )}
                          </td>
                          <td>{Math.round((attempt.progress ?? 0) * 100)}%</td>
                          <td>{new Date(attempt.started_at).toLocaleString()}</td>
                          <td>
                            {attempt.error ||
                              (attempt.has_result ? 'Result envelope recorded' : 'No outcome recorded')}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </RecordTable>
                </div>
              )}
              {attemptsNext && (
                <Button
                  type="button"
                  disabled={attemptsLoading}
                  onClick={() =>
                    void loadAttempts(nextPagePath(attemptsNext, attemptsPath(kind, runId)), true)
                  }
                >
                  {attemptsLoading ? 'Loading…' : 'Load more attempts'}
                </Button>
              )}
            </section>
          )}

          {detail.checkpoints && (
            <section className="runs-panel">
              <h2>Checkpoints ({detail.checkpoints.total})</h2>
              <p className="runs-hint">
                {detail.checkpoints.total === 0
                  ? 'No checkpoint has been committed for this run.'
                  : `${detail.checkpoints.rows.length} of ${detail.checkpoints.total} loaded.`}
              </p>
              {detail.checkpoints.rows.length > 0 && (
                <div className="table-scroll" tabIndex={0}>
                  <RecordTable className="resource-table">
                    <thead>
                      <tr>
                        <th scope="col">Step</th>
                        <th scope="col">State digest</th>
                        <th scope="col">Recorded validity</th>
                        <th scope="col">Runtime contract</th>
                        <th scope="col">Committed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.checkpoints.rows.map((checkpoint) => (
                        <tr key={checkpoint.checkpoint_id}>
                          <td>{checkpoint.step}</td>
                          <td>
                            <Identifier value={checkpoint.state_digest} label="Checkpoint state digest" />
                          </td>
                          <td>
                            <Badge className={`state state-${checkpoint.is_valid ? 'completed' : 'failed'}`}>
                              {checkpoint.is_valid ? 'valid' : 'invalid'}
                            </Badge>
                          </td>
                          <td>
                            {checkpoint.contract_digest
                              ? <Identifier value={checkpoint.contract_digest} label="Runtime contract digest" />
                              : 'not recorded'}
                          </td>
                          <td>{new Date(checkpoint.created_at).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </RecordTable>
                </div>
              )}
            </section>
          )}

          <section className="runs-panel">
            <h2>Recorded metrics ({detail.metrics.total})</h2>
            {kind === 'training' && detail.metrics.truncated && <Button disabled={busy} onClick={async () => {
              setBusy(true); setHistoryError('');
              try { const record = await apiRequest<{ metrics_log: Record<string, unknown>[] }>(`/api/v1/training-runs/${runId}/`, token); setFullMetrics(record.metrics_log); }
              catch (e) { setHistoryError(errorMessage(e)); } finally { setBusy(false); }
            }}>Inspect complete training history</Button>}
            {historyError && <p role="alert">{historyError}</p>}
            {fullMetrics && <details open><summary>Complete recorded training history ({fullMetrics.length} points)</summary><DataInspector value={fullMetrics} /></details>}
            {detail.metrics.total === 0 ? (
              <p className="runs-empty">No metrics have been recorded for this run.</p>
            ) : (
              <>
                <p className="runs-hint">
                  Showing the {detail.metrics.rows.length} most recent of {detail.metrics.total} recorded points.
                </p>
                <div className="table-scroll" tabIndex={0}>
                  <RecordTable className="resource-table">
                    <thead>
                      <tr>
                        <th scope="col">{kind === 'training' ? 'Step' : 'Metric'}</th>
                        <th scope="col">{kind === 'training' ? 'Loss' : 'Value'}</th>
                        <th scope="col">Other recorded values</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.metrics.rows.map((row, index) => {
                        const rest = Object.entries(row).filter(([key]) => key !== 'step' && key !== 'loss');
                        return (
                          <tr key={`${String(row.step ?? index)}-${index}`}>
                            <td><DataValue value={kind === 'training' ? row.step ?? '—' : row.key ?? '—'} /></td>
                            <td>
                              {kind === 'training' ? typeof row.loss === 'number' ? row.loss.toFixed(6) : 'Not reported' : <DataValue value={row.value ?? 'Not reported'} />}
                            </td>
                            <td>
                              {rest.length === 0
                                ? '—'
                                : <DataValue value={Object.fromEntries(rest)} />}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </RecordTable>
                </div>
              </>
            )}
          </section>

          <section className="runs-panel">
            <h2>Recovery note</h2><DraftStatus draft={noteDraft} />
            <p className="runs-hint">
              A private draft kept in this browser tab. Live updates never clear it and it is never sent to the
              API.
            </p>
            <label className="runs-hint" htmlFor="run-recovery-note">
              What you observed and what you tried
            </label>
            <MultilineField
              id="run-recovery-note"
              className="runs-note"
              value={note}
              onChange={(event) => updateNote(event.target.value)}
              placeholder="e.g. Attempt 3 failed on worker cpu-1 after a lease expiry; checked the pool before re-queueing."
            />
            <p className="runs-note-status" aria-live="polite">
              {note ? `${note.length} characters kept in this browser session.` : 'No draft stored yet.'}
            </p>
          </section>
        </>
      )}
    </div>
  );
}
