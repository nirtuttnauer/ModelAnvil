import { Button, Dialog, Disclosure, Field, KeyValueList, LinkButton, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { ObjectFields } from '../components/FormEditors';
import { objectInput } from '../components/form-data';
import { useDraft, DraftIndicator } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
import { InspectorPanel } from '../components/InspectorPanel';
import { Identifier } from '../components/Identifier';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { allResources } from '../api/resources';
import { runHash } from '../api/runs';
import { statusLabel } from '../api/status';
import { ChartPanel, ChartEmpty, SegmentBar, EventTimeline } from '../components/Charts';
import './operations.css';

interface DurableJob {
  job_id: string; name: string; pool: number; status: string; desired_action: string;
  priority: number; attempt_count: number; max_attempts: number; requirements: Record<string, unknown>;
  payload: Record<string, unknown>; created_at: string; updated_at: string;
  cancel_endpoint?: string;
}
interface Policy { policy_id: string; name: string; enabled: boolean; unit: string }
interface Pool { id: number; name: string; status: string }
interface Attempt { attempt_id: string; job_id: string; status: string; worker_id: number; progress: number; error: string; started_at: string }
const endpoint = '/api/v1/jobs/';

// Filters live in the address so a reload, a deep link or browser back/forward
// returns to the same job list with the same selection.
function filtersFromHash(): { query: string; status: string } {
  const params = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  return { query: params.get('q') ?? '', status: params.get('status') ?? 'all' };
}

export function WorkflowsPage({ token, refreshKey = 0 }: { token: string; refreshKey?: number }) {
  const draft = useDraft('workflow', { showForm: false as boolean, name: '', pool: '', priority: '50', slots: '1', accelerator: '', payload: '{}', policy: '', estimate: '' });
  const formId = useId();
  const [jobs, setJobs] = useState<DurableJob[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [pools, setPools] = useState<Pool[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState(filtersFromHash().query);
  const [status, setStatus] = useState(filtersFromHash().status);
  const [selected, setSelected] = useState<DurableJob | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [attemptError, setAttemptError] = useState<string | null>(null);
  const [showForm, setShowForm] = draft.field('showForm');
  const [name, setName] = draft.field('name');
  const [pool, setPool] = draft.field('pool');
  const [priority, setPriority] = draft.field('priority');
  const [slots, setSlots] = draft.field('slots');
  const [accelerator, setAccelerator] = draft.field('accelerator');
  const [payload, setPayload] = draft.field('payload');
  const [policy, setPolicy] = draft.field('policy');
  const [estimate, setEstimate] = draft.field('estimate');
  const [busy, setBusy] = useState(false);
  // An uncertain response can be retried with the same key and exact body.
  const submission = useRef<{ body: string; key: string } | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null);
    try {
      const [page, policyRows, poolRows] = await Promise.all([
        apiPage<DurableJob>(endpoint, token, signal), allResources<Policy>('/api/v1/budget-policies/', token, signal), allResources<Pool>('/api/v1/worker-pools/', token, signal),
      ]);
      if (signal?.aborted) return;
      setJobs(page.results); setNext(page.next || null); setPolicies(policyRows.filter(p => p.enabled)); setPools(poolRows);
      setSelected(current => current ? page.results.find(j => j.job_id === current.job_id) || current : null);
    } catch (e) { if (!signal?.aborted) { setJobs([]); setNext(null); setPolicies([]); setError(errorMessage(e)); } }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [token]);
  useEffect(() => {
    const controller = new AbortController();
    setJobs([]); setSelected(null); submission.current = null;
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => { if (refreshKey) { const c = new AbortController(); void load(c.signal); return () => c.abort(); } }, [refreshKey, load]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setAttempts([]); setAttemptError(null);
    apiPage<Attempt>(`/api/v1/job-attempts/?job_id=${encodeURIComponent(selected.job_id)}`, token, controller.signal).then(page => {
      if (!controller.signal.aborted) setAttempts(page.results.filter(a => a.job_id === selected.job_id));
    }).catch(e => { if (!controller.signal.aborted) setAttemptError(errorMessage(e)); });
    return () => controller.abort();
  }, [selected, token]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (query) params.set('q', query);
    if (status !== 'all') params.set('status', status);
    const search = params.toString();
    const nextHash = `#workflows${search ? `?${search}` : ''}`;
    if (window.location.hash !== nextHash) window.location.hash = nextHash;
  }, [query, status]);

  // Back/forward and cross-area navigation must not leave stale filters behind.
  useEffect(() => {
    const onHashChange = () => {
      const next = filtersFromHash();
      setQuery((current) => (current === next.query ? current : next.query));
      setStatus((current) => (current === next.status ? current : next.status));
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  async function createJob(e: React.FormEvent) {
    e.preventDefault(); if (busy) return;
    setFormError(null); setNotice('');
    let parsed: Record<string, unknown>;
    try { parsed = objectInput(payload); } catch (e) { setFormError(errorMessage(e)); return; }
    const body = JSON.stringify({ name: name.trim(), pool: Number(pool), priority: Number(priority),
      payload: parsed, requirements: { slots: Number(slots), ...(accelerator ? { accelerator } : {}) },
      ...(policy ? { budget_policy_id: policy, estimated_amount: estimate } : {}),
    });
    if (!submission.current || submission.current.body !== body) submission.current = { body, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const job = await apiRequest<DurableJob>(endpoint, token, { method: 'POST', body, headers: { 'Idempotency-Key': submission.current.key } });
      setNotice(`Job “${job.name}” created. Current state: ${job.status}.`);
      submission.current = null; setShowForm(false); setName('');
      await load(); setSelected(job);
    } catch (e) { setFormError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function cancelJob(job: DurableJob) {
    setBusy(true); setError(null); setNotice('');
    try {
      await apiRequest(job.cancel_endpoint || `${endpoint}${job.job_id}/cancel/`, token, { method: 'POST', body: '{}' });
      const updated = await apiRequest<DurableJob>(`${endpoint}${job.job_id}/`, token);
      setJobs(current => current.map(j => j.job_id === updated.job_id ? updated : j)); setSelected(updated);
      setNotice(updated.status === 'cancelled' ? `Job “${job.name}” cancelled.` : 'Cancellation requested. The worker must stop before the job is cancelled.');
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function loadMore() {
    if (!next) return;
    setLoading(true); setError(null);
    try {
      const page = await apiPage<DurableJob>(nextPagePath(next, endpoint), token);
      setJobs(current => [...current, ...page.results.filter(j => !current.some(x => x.job_id === j.job_id))]); setNext(page.next || null);
    } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); }
  }
  const poolName = (id: number) => pools.find(p => p.id === id)?.name || 'Pool unavailable';
  const statuses = [...new Set(jobs.map(j => j.status))];
  const filtered = jobs.filter(j => `${j.name} ${j.job_id}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || j.status === status));
  const jobStates = statuses.map(label => ({ label: statusLabel(label), value: jobs.filter(j => j.status === label).length }));
  const cancelRequested = !!selected && selected.desired_action === 'cancel' && selected.status !== 'cancelled';
  const ready = !!token.trim();

  return <div className="ops-page">
    <Section title="Jobs" description="Durable work from queue to recorded outcome." actions={<>
      <Field className="ops-search" aria-label="Search jobs" placeholder="Search jobs" value={query} onChange={e => setQuery(e.target.value)} />
      <Select aria-label="Job status" value={status} onChange={e => setStatus(e.target.value)}>
        <option value="all">All states</option>{statuses.map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}
      </Select>
      <Button type="button" variant="primary" disabled={!ready || busy} onClick={() => { setFormError(null); setShowForm(true); }}>Create job</Button>
    </>}>
      {notice && <Notice tone="success" role="status">{notice}</Notice>}
      <ResourceState loading={loading && !jobs.length} error={error} onRetry={() => void load()} />
      <div data-ui="split" data-open={selected ? '' : undefined}>
        <div className="ops-main">
          {!loading && !error && <p className="ops-count">{filtered.length} of {jobs.length} loaded jobs</p>}
          {!loading && !error && !filtered.length && <EmptyState title={jobs.length ? 'No jobs match these filters.' : 'No jobs yet'} description={jobs.length ? undefined : 'Create a job to start.'} />}
          {!!filtered.length && <div className="table-scroll" tabIndex={0}><RecordTable>
            <thead><tr><th>Job</th><th>Status</th><th>Pool</th><th>Attempts</th><th>Updated</th></tr></thead>
            <tbody>{filtered.map(j => <tr key={j.job_id} aria-selected={selected?.job_id === j.job_id || undefined}>
              <td><a href={runHash('job', j.job_id)}>{j.name}</a><div className="ops-row-actions"><Button type="button" variant="quiet" size="sm" onClick={() => setSelected(j)}>Inline details</Button></div></td>
              <td><StatusBadge status={j.status} />{j.desired_action === 'cancel' && j.status !== 'cancelled' && <small>Cancellation requested</small>}</td>
              <td>{poolName(j.pool)}</td>
              <td>{j.attempt_count} / {j.max_attempts || 'default'}</td>
              <td>{new Date(j.updated_at).toLocaleString()}</td>
            </tr>)}</tbody>
          </RecordTable></div>}
          {next && <Button type="button" disabled={loading} onClick={() => void loadMore()}>Load more jobs</Button>}
        </div>
        {selected && <InspectorPanel key={selected.job_id} title={selected.name} eyebrow="Job" closeLabel="Close job details" onClose={() => setSelected(null)}>
          <div data-ui="actions"><StatusBadge status={selected.status} /></div>
          {cancelRequested && <Notice tone="caution">Cancellation requested. The job stays in its current state until the worker stops.</Notice>}
          <KeyValueList items={[
            { label: 'Observed state', value: statusLabel(selected.status) },
            { label: 'Desired action', value: selected.desired_action ? statusLabel(selected.desired_action) : 'None' },
            { label: 'Priority', value: selected.priority },
            { label: 'Pool', value: poolName(selected.pool) },
            { label: 'Attempts', value: `${selected.attempt_count} / ${selected.max_attempts || 'default'}` },
            { label: 'Created', value: new Date(selected.created_at).toLocaleString() },
            { label: 'Job ID', value: <Identifier value={selected.job_id} label="Job ID" display="code" /> },
          ]} />
          <div data-ui="actions">
            <LinkButton variant="primary" href={runHash('job', selected.job_id)}>Open run</LinkButton>
            {['queued', 'running'].includes(selected.status) && !cancelRequested && <Button type="button" disabled={busy} onClick={() => void cancelJob(selected)}>Cancel job</Button>}
          </div>
          <h3>Attempts</h3>
          <ResourceState error={attemptError} />
          {attempts.length ? <EventTimeline events={[...attempts].sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at)).map((a, index) => ({
            label: `Attempt ${index + 1}`, status: a.status,
            detail: `Started ${new Date(a.started_at).toLocaleString()} · ${Math.round(a.progress * 100)}% progress${a.error ? ` · ${a.error}` : ''}`,
          }))} /> : <p className="muted">No attempts in this page.</p>}
          <Disclosure summary="Payload and requirements" variant="quiet"><DataInspector value={{ payload: selected.payload, requirements: selected.requirements }} /></Disclosure>
          <p className="ops-footnote">Progress, worker evidence and recovery blockers live in the run view.</p>
        </InspectorPanel>}
      </div>
    </Section>
    <Disclosure summary="Execution overview" variant="card"><div className="ops-charts">
      <ChartPanel title="Observed execution states" description={`${jobs.length} loaded jobs · observed backend state, separate from desired action.`}>{jobs.length ? <SegmentBar data={jobStates} unit="jobs" /> : <ChartEmpty message="Create a durable job to see its recorded execution state." />}</ChartPanel>
      <ChartPanel title="Recent execution records" description="Created and last updated timestamps from the loaded job list.">{jobs.length ? <EventTimeline events={[...jobs].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 4).map(j => ({ label: j.name, detail: `Created ${new Date(j.created_at).toLocaleString()} · updated ${new Date(j.updated_at).toLocaleString()}${j.desired_action === 'cancel' ? ' · cancellation requested' : ''}`, status: j.status }))} /> : <ChartEmpty message="Execution records appear after a job is created." />}</ChartPanel>
    </div></Disclosure>
    <Dialog title="Create a job" description="Queue durable work on a worker pool." open={showForm} onClose={() => setShowForm(false)} size="lg"
      footer={<><Button type="button" disabled={busy} onClick={() => setShowForm(false)}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || !name.trim()}>{busy ? 'Submitting…' : 'Queue job'}</Button></>}>
      <form id={formId} data-ui="form" onSubmit={createJob}>
        <DraftIndicator draft={draft} disabled={busy} />
        {formError && <Notice tone="error" role="alert">{formError}</Notice>}
        <div data-ui="field-grid">
          <TextControl label="Job name" required maxLength={200} value={name} onChange={e => setName(e.target.value)} />
          <Select label="Worker pool" hint={<>Check <a href="#infrastructure">Infrastructure</a> for worker capabilities.</>} required value={pool} onChange={e => setPool(e.target.value)}>
            <option value="">Select a pool</option>{pools.map(p => <option key={p.id} value={p.id} disabled={p.status !== 'active'}>{p.name} · {statusLabel(p.status)}</option>)}
          </Select>
          <TextControl label="Priority" required type="number" min="0" max="32767" step="1" value={priority} onChange={e => setPriority(e.target.value)} />
          <TextControl label="Execution slots" required type="number" min="1" max="1024" step="1" value={slots} onChange={e => setSlots(e.target.value)} />
          <Select label="Accelerator" value={accelerator} onChange={e => setAccelerator(e.target.value)}
            options={[{ value: '', label: 'Any compatible worker' }, { value: 'cpu', label: 'CPU' }, { value: 'gpu', label: 'GPU' }, { value: 'tpu', label: 'TPU' }]} />
          <Select label="Budget policy" required={policies.length > 0} value={policy} onChange={e => setPolicy(e.target.value)}>
            <option value="">{policies.length ? 'Select an enabled policy' : 'No enabled policies'}</option>{policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name} ({p.unit})</option>)}
          </Select>
          {policy && <TextControl label="Estimated usage" required type="number" min="0.000001" step="0.000001" value={estimate} onChange={e => setEstimate(e.target.value)} />}
        </div>
        <ObjectFields title="Job inputs" description="Named values for the worker. Use groups and lists for nested inputs." value={payload} onChange={setPayload} disabled={busy} />
      </form>
    </Dialog>
  </div>;
}
