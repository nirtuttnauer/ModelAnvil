import { Identifier } from '../components/Identifier';
import { Button, Disclosure, KeyValueList, LinkButton, MultilineControl, Notice, RecordTable, StatusBadge } from '../components/ui';
import { RunMetrics } from '../components/run-detail/RunMetrics';
import { RunCheckpoints } from '../components/run-detail/RunCheckpoints';
import { RunLinks } from '../components/run-detail/RunLinks';
import type { Attempt, RunDetail } from '../api/run-detail';
import { useDraft, DraftIndicator } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath, type ApiPage } from '../api/client';
import { attemptsPath, detailPath, runHash, sourceHash, type RunKind } from '../api/runs';
import { ResourceState } from '../components/ResourceState';
import { statusLabel } from '../api/status';
import { EventTimeline } from '../components/Charts';
import './runs.css';

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
  const attemptsInitialized = useRef(false);
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
        if (append || !attemptsInitialized.current) setAttemptsNext(page.next || null);
        attemptsInitialized.current = true;
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

          {detail.checkpoints && <RunCheckpoints checkpoints={detail.checkpoints} />}

          <RunMetrics kind={kind} detail={detail} busy={busy} fullMetrics={fullMetrics} historyError={historyError} onLoadHistory={() => void loadHistory()} />

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

          <RunLinks links={links} />

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
