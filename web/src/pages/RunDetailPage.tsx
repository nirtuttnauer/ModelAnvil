import { Identifier } from '../components/Identifier';
import { Button, Disclosure, KeyValueList, LinkButton, MultilineControl, Notice, RecordTable, StatusBadge } from '../components/ui';
import { resourceHash } from '../api/resource-routes';
import { useDraft, DraftIndicator } from '../components/Draft';
import { DataInspector, DataValue } from '../components/DataInspector';
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath, type ApiPage } from '../api/client';
import { attemptsPath, detailPath, runHash, sourceHash, type RunKind } from '../api/runs';
import { ResourceState } from '../components/ResourceState';
import { statusLabel } from '../api/status';
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
const KIND_LABEL: Record<RunKind, string> = { training: 'Training run', evaluation: 'Evaluation run', job: 'Job' };
const BACK: Record<RunKind, { hash: string; label: string }> = { training: { hash: '#training', label: 'Back to training' }, evaluation: { hash: '#evaluation', label: 'Back to evaluation' }, job: { hash: '#workflows', label: 'Back to workflows' } };

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

/** Relative time that ticks on its own, so the rest of the page does not re-render every second. */
function RelativeTime({ from, prefix, suffix = '' }: { from: number | null; prefix: string; suffix?: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>{prefix} {age(from, now)}{suffix}</>;
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
  const [staleNow, setStaleNow] = useState(() => Date.now());
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
    setRecoveryReview(null);
    void load(controller.signal);
    return () => controller.abort();
  }, [load, kind, runId]);

  const state = detail?.observed.state;
  useEffect(() => {
    if (!detail || !state || TERMINAL.includes(state)) return;
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void load(undefined, true);
    }, pollMs);
    return () => clearInterval(timer);
  }, [detail, state, pollMs, load]);

  // Staleness only needs to be re-checked at the poll cadence, not every second.
  useEffect(() => {
    const timer = setInterval(() => setStaleNow(Date.now()), pollMs);
    return () => clearInterval(timer);
  }, [pollMs]);

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
  async function loadHistory() {
    setBusy(true); setHistoryError('');
    try { const record = await apiRequest<{ metrics_log: Record<string, unknown>[] }>(`/api/v1/training-runs/${runId}/`, token); setFullMetrics(record.metrics_log); }
    catch (e) { setHistoryError(errorMessage(e)); } finally { setBusy(false); }
  }

  const cancel = detail?.actions.cancel;
  const resume = detail?.actions.resume;
  const requested = cancelRequested || Boolean(cancel?.requested);
  const acknowledged = Boolean(cancel?.acknowledged) || detail?.observed.state === 'cancelled';
  const live = Boolean(detail) && !TERMINAL.includes(state ?? '');
  const stale = updatedAt !== null && staleNow - updatedAt > pollMs * 2;
  const links = detail?.links ?? {};
  const displayName = detail?.name?.replace(/^(Training run|Evaluation) [a-f0-9]{8}$/i, KIND_LABEL[kind]);
  const blockers = [...(cancel?.blocked_by ?? []), ...(resume?.blocked_by ?? [])].slice(0, 3);
  const desiredAction = detail?.desired.action
    ? `${statusLabel(detail.desired.action)} · ${acknowledged ? 'Acknowledged' : requested ? 'Requested — not yet acknowledged by the worker' : detail.desired.acknowledged ? 'Acknowledged' : 'Pending'}`
    : 'None';
  const freshnessTone = connectionError ? 'error' : live && stale ? 'caution' : undefined;

  return (
    <div className="runs-page">
      <ResourceState loading={loading && !detail} error={error} onRetry={() => void load()} />
      {detail && (
        <>
          <header className="runs-states">
            <div className="runs-head-main">
              <h2>{displayName ?? 'Run detail'}</h2>
              <div data-ui="actions">
                <StatusBadge status={detail.observed.state} />
                <span className="muted">{KIND_LABEL[kind]}</span>
                {requested && <StatusBadge status="cancellation_requested" label={acknowledged ? 'Cancellation acknowledged' : 'Cancellation requested'} />}
              </div>
              {detail.observed.current_step !== null && (
                <div className="runs-progress">
                  <span>Progress</span>
                  <strong>{detail.observed.current_step} / {detail.observed.total_steps}</strong>
                  <progress value={detail.observed.current_step} max={detail.observed.total_steps || 1} aria-label="Run progress" />
                </div>
              )}
              <p className="runs-freshness" role="status" aria-live="polite" data-tone={freshnessTone}>
                {connectionError
                  ? `Live updates interrupted: ${connectionError} The last recorded values stay on screen.`
                  : live
                  ? <><RelativeTime from={updatedAt} prefix="Last successful update" /> · polling every {Math.round(pollMs / 1000)}s{stale ? ' · older than two poll intervals' : ''}</>
                  : <>Final state · <RelativeTime from={updatedAt} prefix="last successful update" /></>}
              </p>
            </div>
            <div data-ui="actions">
              {(cancel?.available || requested) && (
                <Button type="button" variant="primary" disabled={!cancel?.available || busy || requested} onClick={() => void requestCancellation()}>
                  {acknowledged ? 'Cancellation acknowledged' : requested ? 'Cancellation requested' : 'Cancel run'}
                </Button>
              )}
              {resume?.available && <Button type="button" variant={cancel?.available ? 'secondary' : 'primary'} disabled={busy || stale || !!connectionError} onClick={() => void reviewRecovery()}>Review checkpoint recovery</Button>}
              {resume?.recovery_run_id && <LinkButton href={runHash('training', resume.recovery_run_id)}>Open recovery run</LinkButton>}
              <Button type="button" variant="quiet" onClick={() => void load()}>Refresh</Button>
              <LinkButton variant="quiet" href={sourceHash(window.location.hash, BACK[kind].hash)}>{BACK[kind].label}</LinkButton>
            </div>
          </header>

          {actionError && <Notice tone="error" role="alert">{actionError}</Notice>}
          {blockers.length > 0 && <ul className="runs-blockers">{blockers.map((reason) => <li key={reason}>{reason}</li>)}</ul>}

          {recoveryReview && (
            <div className="runs-review" aria-label="Recovery review">
              <h3>Resume from step {recoveryReview.step}</h3>
              <p>Reserve {recoveryReview.remaining_steps} remaining training steps. Prior committed usage stays on the parent execution.</p>
              <p>{recoveryReview.replay_limits}</p>
              <DataInspector value={recoveryReview.pins} />
              {recoveryReview.blocked_by.map(reason => <p key={reason} role="alert">{reason}</p>)}
              <div data-ui="actions">
                <Button type="button" variant="primary" disabled={busy || !recoveryReview.available} onClick={() => void resumeRecovery()}>Resume from verified checkpoint</Button>
                <Button type="button" disabled={busy} onClick={() => setRecoveryReview(null)}>Close recovery review</Button>
              </div>
            </div>
          )}

          <KeyValueList columns={2} items={[
            { label: 'Observed state', value: `${statusLabel(detail.observed.state)}${detail.observed.job_state && detail.observed.job_state !== detail.observed.state ? ` · job ${statusLabel(detail.observed.job_state)}` : ''}` },
            { label: 'Desired action', value: desiredAction },
            { label: 'Progress', value: detail.observed.current_step === null ? 'Not tracked by this run type' : `${detail.observed.current_step} / ${detail.observed.total_steps}` },
            { label: 'Attempts', value: detail.observed.attempts ?? 'No durable job' },
            { label: 'Worker', value: `${detail.ownership.worker ?? 'Not assigned'} · ${statusLabel(detail.ownership.state)}` },
            { label: 'Lease', value: detail.ownership.lease_expires_at ? new Date(detail.ownership.lease_expires_at).toLocaleString() : 'No active lease' },
            { label: 'Execution mode', value: detail.execution_mode },
            { label: 'Evidence', value: detail.evidence ? `${detail.evidence.level} · ${detail.evidence.source}` : 'No runtime evidence level' },
            { label: 'Updated', value: new Date(detail.observed.updated_at).toLocaleString() },
            { label: 'Run ID', value: <Identifier value={runId} label="Run ID" display="code" /> },
          ]} />
          {detail.ownership.reason && <p className="runs-hint">{detail.ownership.reason}</p>}

          {Boolean(detail.links.job) && (
            <Disclosure summary={`Attempts (${attempts.length} loaded)`} variant="card">
              <ResourceState error={attemptsError} onRetry={() => void loadAttempts(attemptsPath(kind, runId), false)} />
              {attempts.length === 0 && !attemptsLoading && <p className="muted">No worker attempt has claimed this job.</p>}
              {attempts.length > 0 && (
                <div className="table-scroll" tabIndex={0}>
                  <RecordTable>
                    <thead><tr><th scope="col">Attempt</th><th scope="col">Status</th><th scope="col">Worker</th><th scope="col">Progress</th><th scope="col">Started</th><th scope="col">Recorded outcome</th></tr></thead>
                    <tbody>
                      {attempts.map((attempt, index) => (
                        <tr key={attempt.attempt_id}>
                          <td>Attempt {index + 1}<small>{attempt.lease_expires_at ? `lease until ${new Date(attempt.lease_expires_at).toLocaleTimeString()}` : 'no lease'}</small></td>
                          <td><StatusBadge status={attempt.status} /></td>
                          <td>{attempt.worker ?? 'Unassigned'}{attempt.worker_status && <small>{attempt.worker_status}</small>}</td>
                          <td>{Math.round((attempt.progress ?? 0) * 100)}%</td>
                          <td>{new Date(attempt.started_at).toLocaleString()}</td>
                          <td>{attempt.error || (attempt.has_result ? 'Result envelope recorded' : 'No outcome recorded')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </RecordTable>
                </div>
              )}
              {attemptsNext && (
                <div data-ui="actions"><Button type="button" disabled={attemptsLoading} onClick={() => void loadAttempts(nextPagePath(attemptsNext, attemptsPath(kind, runId)), true)}>
                  {attemptsLoading ? 'Loading…' : 'Load more attempts'}
                </Button></div>
              )}
              <p className="runs-hint">Attempts are append-only: every recorded failure stays visible after any later action.</p>
            </Disclosure>
          )}

          {detail.checkpoints && (
            <Disclosure summary={`Checkpoints (${detail.checkpoints.total})`} variant="card">
              <p className="runs-hint">{detail.checkpoints.total === 0 ? 'No checkpoint has been committed for this run.' : `${detail.checkpoints.rows.length} of ${detail.checkpoints.total} loaded.`}</p>
              {detail.checkpoints.rows.length > 0 && (
                <div className="table-scroll" tabIndex={0}>
                  <RecordTable>
                    <thead><tr><th scope="col">Step</th><th scope="col">State digest</th><th scope="col">Validity</th><th scope="col">Runtime contract</th><th scope="col">Committed</th></tr></thead>
                    <tbody>
                      {detail.checkpoints.rows.map((checkpoint) => (
                        <tr key={checkpoint.checkpoint_id}>
                          <td>{checkpoint.step}</td>
                          <td><Identifier value={checkpoint.state_digest} label="Checkpoint state digest" display="code" /></td>
                          <td><StatusBadge status={checkpoint.is_valid ? 'valid' : 'invalid'} /></td>
                          <td>{checkpoint.contract_digest ? <Identifier value={checkpoint.contract_digest} label="Runtime contract digest" display="code" /> : 'Not recorded'}</td>
                          <td>{new Date(checkpoint.created_at).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </RecordTable>
                </div>
              )}
            </Disclosure>
          )}

          <Disclosure summary={`Metrics (${detail.metrics.total})`} variant="card" open={kind === 'training' && detail.metrics.total > 0}>
            {kind === 'training' && detail.metrics.rows.length > 0 && <ChartPanel title="Recorded loss" description={`Exact metric steps · evidence: ${detail.evidence?.level ?? 'not reported'}`} bordered={false}>
              <LineChart series={[
                { name: 'Training loss', points: detail.metrics.rows.flatMap(row => typeof row.step === 'number' && typeof row.loss === 'number' ? [{ x: row.step, y: row.loss }] : []) },
                { name: 'Validation loss', points: detail.metrics.rows.flatMap(row => typeof row.step === 'number' && typeof row.validation_loss === 'number' ? [{ x: row.step, y: row.validation_loss }] : []) },
              ].filter(series => series.points.length)} yLabel="Loss" />
            </ChartPanel>}
            {kind === 'evaluation' && detail.metrics.rows.length > 0 && <ChartPanel title="Evaluation measurements" description="Frozen scoring metrics; sample counts and uncertainty are in the table." bordered={false}>
              <BarChart data={detail.metrics.rows.filter(row => typeof row.value === 'number').map(row => ({ label: String(row.key || 'Metric'), value: Number(row.value) }))} />
            </ChartPanel>}
            {detail.metrics.truncated && <p className="runs-hint">Showing the {detail.metrics.rows.length} most recent of {detail.metrics.total} recorded points.</p>}
            {kind === 'training' && detail.metrics.truncated && <div data-ui="actions"><Button type="button" disabled={busy} onClick={() => void loadHistory()}>Inspect complete training history</Button></div>}
            {historyError && <p role="alert" className="error-text">{historyError}</p>}
            {fullMetrics && <Disclosure summary={`Complete recorded training history (${fullMetrics.length} points)`} variant="quiet" open><DataInspector value={fullMetrics} /></Disclosure>}
            {detail.metrics.total === 0 ? <p className="muted">No metrics have been recorded for this run.</p> : (
              <div className="table-scroll" tabIndex={0}>
                <RecordTable>
                  <thead><tr><th scope="col">{kind === 'training' ? 'Step' : 'Metric'}</th><th scope="col">{kind === 'training' ? 'Loss' : 'Value'}</th><th scope="col">Other recorded values</th></tr></thead>
                  <tbody>
                    {detail.metrics.rows.map((row, index) => {
                      const rest = Object.entries(row).filter(([key]) => key !== 'step' && key !== 'loss');
                      return (
                        <tr key={`${String(row.step ?? index)}-${index}`}>
                          <td><DataValue value={kind === 'training' ? row.step ?? '—' : row.key ?? '—'} /></td>
                          <td>{kind === 'training' ? typeof row.loss === 'number' ? row.loss.toFixed(6) : 'Not reported' : <DataValue value={row.value ?? 'Not reported'} />}</td>
                          <td>{rest.length === 0 ? '—' : <DataValue value={Object.fromEntries(rest)} />}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </RecordTable>
              </div>
            )}
          </Disclosure>

          <Disclosure summary="Evidence and usage" variant="card">
            <div className="runs-columns">
              <div>
                <h3>Execution record</h3>
                <EventTimeline events={[
                  { label: 'Created', detail: new Date(detail.observed.created_at).toLocaleString() },
                  ...(detail.observed.started_at ? [{ label: 'Execution started', detail: new Date(detail.observed.started_at).toLocaleString() }] : []),
                  { label: 'Current observed state', status: detail.observed.state, detail: new Date(detail.observed.updated_at).toLocaleString() },
                  ...(detail.observed.completed_at ? [{ label: 'Execution ended', detail: new Date(detail.observed.completed_at).toLocaleString() }] : []),
                ]} />
                <h3>Recorded evidence</h3>
                {detail.evidence ? <KeyValueList items={[
                  { label: 'Level', value: detail.evidence.level },
                  { label: 'Source', value: detail.evidence.source },
                  { label: 'Projection generated', value: new Date(detail.generated_at).toLocaleString() },
                ]} /> : <p className="muted">Durable jobs carry no runtime evidence level; the worker outcome is recorded on the attempts.</p>}
              </div>
              <div>
                <h3>Budget reservation</h3>
                {detail.usage.reservations.length === 0 ? <p className="muted">No budget reservation is recorded for this run.</p> : <ul className="runs-list">
                  {detail.usage.reservations.map((item) => <li key={item.reservation_id}>{item.policy_name}: {statusLabel(item.state)} · estimated {item.estimated_amount} {item.unit}{item.settled_amount ? ` · settled ${item.settled_amount}` : ''}</li>)}
                </ul>}
                <h3>Usage events</h3>
                {detail.usage.events.length === 0 ? <p className="muted">No usage events recorded.</p> : <>
                  <ul className="runs-list">{detail.usage.events.map((event) => <li key={event.usage_id}>{new Date(event.occurred_at).toLocaleString()} · {event.quantity} {event.unit}</li>)}</ul>
                  {detail.usage.events_truncated && <p className="runs-hint">Only the most recent usage events are loaded.</p>}
                </>}
                {resume?.budget && <p className="runs-hint">Budget ({resume.budget.state}): {resume.budget.reason}</p>}
                {resume?.checkpoint && <p className="runs-hint">Checkpoint: {resume.checkpoint.reason}{resume.checkpoint.step === null ? '' : ` (step ${resume.checkpoint.step})`}</p>}
                {resume?.operator_path && <p className="runs-hint">{resume.operator_path}</p>}
                {resume?.preserves_history && <p className="runs-hint">{resume.preserves_history}</p>}
              </div>
            </div>
            <h3>Pinned inputs</h3>
            <DataInspector value={detail.inputs} />
          </Disclosure>

          <Disclosure summary="Links" variant="card">
            <div data-ui="actions">
              {links.job && <LinkButton href={runHash('job', linkId(links.job))}>Job</LinkButton>}
              {links.training_run && <LinkButton href={runHash('training', linkId(links.training_run))}>Training run</LinkButton>}
              {links.output_model_version && <LinkButton href={resourceHash('model-version', linkId(links.output_model_version))}>Trained model</LinkButton>}
              {links.base_model_version && <LinkButton href={resourceHash('model-version', linkId(links.base_model_version))}>Base model version</LinkButton>}
              {links.recovery_parent && <LinkButton href={runHash('training', linkId(links.recovery_parent))}>Parent run</LinkButton>}
              {links.model_version && <LinkButton href={resourceHash('model-version', linkId(links.model_version))}>Model version</LinkButton>}
              {links.dataset_revision && <LinkButton href={resourceHash('dataset-revision', linkId(links.dataset_revision))}>Dataset version</LinkButton>}
              {Array.isArray(links.evaluation_runs) && links.evaluation_runs.map((id, index) => <LinkButton key={id} href={runHash('evaluation', id)}>Evaluation run {index + 1}</LinkButton>)}
              <LinkButton variant="quiet" href="#infrastructure">Infrastructure</LinkButton>
              <LinkButton variant="quiet" href="#budgets">Budgets</LinkButton>
              <LinkButton variant="quiet" href="#audit">Audit</LinkButton>
            </div>
          </Disclosure>

          <Disclosure summary="Recovery note" variant="card">
            <DraftIndicator draft={noteDraft} />
            <MultilineControl id="run-recovery-note" label="What you observed and what you tried" hint="A private draft kept in this browser tab. It is never sent to the API." value={note} onChange={(event) => setNote(event.target.value)} placeholder="e.g. Attempt 3 failed on worker cpu-1 after a lease expiry; checked the pool before re-queueing." />
            <p className="runs-hint" aria-live="polite">{note ? `${note.length} characters kept in this browser session.` : 'No draft stored yet.'}</p>
          </Disclosure>
        </>
      )}
    </div>
  );
}
