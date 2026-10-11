import { useCallback, useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { allResources } from '../api/resources';
import { runHash } from '../api/runs';
import { ChartPanel, ChartEmpty, SegmentBar, EventTimeline } from '../components/Charts';
import { Plus, ArrowUpRight, X } from 'lucide-react';
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
  const [jobs, setJobs] = useState<DurableJob[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [pools, setPools] = useState<Pool[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState(filtersFromHash().query);
  const [status, setStatus] = useState(filtersFromHash().status);
  const [selected, setSelected] = useState<DurableJob | null>(null);
  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [attemptError, setAttemptError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [pool, setPool] = useState('');
  const [priority, setPriority] = useState('50');
  const [slots, setSlots] = useState('1');
  const [accelerator, setAccelerator] = useState('');
  const [payload, setPayload] = useState('{}');
  const [policy, setPolicy] = useState('');
  const [estimate, setEstimate] = useState('');
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
    setJobs([]); setSelected(null); setShowForm(false); submission.current = null;
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
    setError(null); setNotice('');
    let parsed: unknown;
    try { parsed = JSON.parse(payload); } catch { setError('Payload must be valid JSON.'); return; }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) { setError('Payload must be a JSON object.'); return; }
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
    } catch (e) { setError(errorMessage(e)); }
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
  const filtered = jobs.filter(j => `${j.name} ${j.job_id}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || j.status === status));
  const jobStates = [...new Set(jobs.map(j => j.status))].map(label => ({ label, value: jobs.filter(j => j.status === label).length }));
  return <div className="resource-view operations-page">
    <div className="ops-heading"><div><span className="eyebrow">Execution control</span><h2>Durable execution</h2><p>Follow durable work from queue to recorded outcome.</p></div><button className="primary" disabled={!token.trim() || busy || loading || !!error} aria-expanded={showForm} onClick={() => setShowForm(v => !v)}><Plus size={16} aria-hidden="true" />{showForm ? 'Close composer' : 'Create job'}</button></div>
    <div className="ops-state-filters" aria-label="Filter by observed job state"><button aria-pressed={status === 'all'} className={status === 'all' ? 'active' : ''} onClick={() => setStatus('all')}>All jobs <b>{jobs.length}</b></button>{jobStates.map(s => <button key={s.label} aria-pressed={status === s.label} className={status === s.label ? 'active' : ''} onClick={() => setStatus(s.label)}>{s.label.replaceAll('_', ' ')}<b>{s.value}</b></button>)}</div>
    <div className="ops-chart-grid">
      <ChartPanel title="Observed execution states" description={`${jobs.length} loaded jobs · observed backend state, separate from desired action.`}>{jobs.length ? <SegmentBar data={jobStates} unit="jobs" /> : <ChartEmpty message="Create a durable job to see its recorded execution state." />}</ChartPanel>
      <ChartPanel title="Recent execution records" description="Created and last updated timestamps from the loaded job list.">{jobs.length ? <EventTimeline events={[...jobs].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 4).map(j => ({ label: j.name, detail: `Created ${new Date(j.created_at).toLocaleString()} · updated ${new Date(j.updated_at).toLocaleString()}${j.desired_action === 'cancel' ? ' · cancellation requested' : ''}`, status: j.status }))} /> : <ChartEmpty message="Execution records appear after a job is created." />}</ChartPanel>
    </div>
    <div className={`ops-workspace ${selected ? 'with-inspector' : ''}`}>

    <section className="panel">
      <div className="panel-title"><div><h2>Job pool</h2><p>Search the loaded jobs and inspect a recorded execution.</p></div><span className="badge">{jobs.length} loaded</span></div>
      <div className="panel-body">
        {notice && <div className="notice success" role="status">{notice}</div>}
        <ResourceState loading={loading} error={error} onRetry={() => void load()} />
        {showForm && <form className="form-grid" onSubmit={createJob}>
          <label>Job name<input required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label>
          <label>Worker pool<select required value={pool} onChange={e => setPool(e.target.value)}><option value="">Select a registered pool</option>{pools.map(p => <option key={p.id} value={p.id} disabled={p.status !== 'active'}>{p.name} · #{p.id} · {p.status}</option>)}</select><small><a href="#infrastructure">Inspect workers and capabilities</a> before choosing a pool.</small></label>
          <label>Priority<input required type="number" min="0" max="32767" step="1" value={priority} onChange={e => setPriority(e.target.value)} /></label>
          <label>Execution slots<input required type="number" min="1" max="1024" step="1" value={slots} onChange={e => setSlots(e.target.value)} /></label>
          <label>Accelerator<select value={accelerator} onChange={e => setAccelerator(e.target.value)}><option value="">Any compatible worker</option><option value="cpu">CPU</option><option value="gpu">GPU</option><option value="tpu">TPU</option></select></label>
          <label>Budget policy<select required={policies.length > 0} value={policy} onChange={e => setPolicy(e.target.value)}><option value="">{policies.length ? 'Select an enabled policy' : 'No enabled policies'}</option>{policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name} ({p.unit})</option>)}</select></label>
          {policy && <label>Estimated usage<input required type="number" min="0.000001" step="0.000001" value={estimate} onChange={e => setEstimate(e.target.value)} /></label>}
          <label className="full-width">Payload (JSON)<textarea rows={6} value={payload} onChange={e => setPayload(e.target.value)} spellCheck={false} /></label>
          <div className="full-width actions"><button className="primary" disabled={busy || !name.trim()}>{busy ? 'Submitting…' : 'Queue job'}</button><button type="button" disabled={busy} onClick={() => setShowForm(false)}>Cancel</button></div>
        </form>}
        <div className="toolbar"><input aria-label="Search jobs" placeholder="Search jobs by name or ID" value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="Job status" value={status} onChange={e => setStatus(e.target.value)}><option value="all">All states</option>{[...new Set(jobs.map(j => j.status))].map(s => <option key={s}>{s}</option>)}</select><small className="muted">{filtered.length} of {jobs.length} loaded jobs</small></div>
        {!loading && !error && !filtered.length && <p className="muted">{jobs.length ? 'No jobs match these filters.' : 'No jobs yet. Create a job to start.'}</p>}
        {!!filtered.length && <div className="table-scroll" tabIndex={0}><table className="resource-table"><thead><tr><th>Job</th><th>State</th><th>Pool</th><th>Attempts</th><th>Updated</th></tr></thead><tbody>{filtered.map(j => <tr key={j.job_id} className={selected?.job_id === j.job_id ? 'ops-selected-row' : ''}><td><a href={runHash('job', j.job_id)}>{j.name}</a><small className="id-text">{j.job_id.slice(0, 8)}</small><button className="text-button" onClick={() => setSelected(j)}>Inline details</button></td><td><span className={`state state-${j.status}`}>{j.status}</span>{j.desired_action === 'cancel' && j.status !== 'cancelled' && <small className="id-text">Cancellation requested</small>}</td><td>{j.pool}</td><td>{j.attempt_count} / {j.max_attempts || 'default'}</td><td>{new Date(j.updated_at).toLocaleString()}</td></tr>)}</tbody></table></div>}
        {next && <button disabled={loading} onClick={() => void loadMore()}>Load more jobs</button>}
      </div>
    </section>
    {selected && <aside className="panel ops-inspector"><div className="panel-title"><div><span className="eyebrow">Selected job</span><h2>{selected.name}</h2></div><button className="icon-button" aria-label="Close job details" onClick={() => setSelected(null)}><X size={17} aria-hidden="true" /></button></div><div className="panel-body">
      <span className={`state state-${selected.status}`}>{selected.status}</span><small className="id-text">{selected.job_id}</small>
      {selected.desired_action === 'cancel' && selected.status !== 'cancelled' && <div className="notice">Cancellation requested. Waiting for the recorded worker outcome; stop time is unknown.</div>}
      <dl className="ops-facts"><div><dt>Observed state</dt><dd>{selected.status}</dd></div><div><dt>Desired action</dt><dd>{selected.desired_action || 'None'}</dd></div><div><dt>Priority</dt><dd>{selected.priority}</dd></div><div><dt>Pool</dt><dd>{pools.find(p => p.id === selected.pool)?.name || selected.pool}</dd></div><div><dt>Attempts</dt><dd>{selected.attempt_count} / {selected.max_attempts || 'default'}</dd></div><div><dt>Created</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd></div></dl>
      <div className="ops-inspector-actions"><a className="ops-link-button" href={runHash('job', selected.job_id)}>Open run <ArrowUpRight size={15} aria-hidden="true" /></a>{['queued', 'running'].includes(selected.status) && selected.desired_action !== 'cancel' && <button disabled={busy} onClick={() => void cancelJob(selected)}>Request cancellation</button>}</div>
      <h3>Loaded worker attempts</h3><p className="muted">Attempts from the loaded history page; this may not be the full history.</p><ResourceState error={attemptError} />
      {attempts.length ? <EventTimeline events={[...attempts].sort((a, b) => Date.parse(a.started_at) - Date.parse(b.started_at)).map(a => ({ label: `Worker ${a.worker_id}`, status: a.status, detail: `Started ${new Date(a.started_at).toLocaleString()} · ${Math.round(a.progress * 100)}% recorded progress${a.error ? ` · ${a.error}` : ''}` }))} /> : <p className="muted">No attempts in this page.</p>}
      <details><summary>Payload and resource requirements</summary><pre>{JSON.stringify({ payload: selected.payload, requirements: selected.requirements }, null, 2)}</pre></details>
      <p className="muted">Progress, worker evidence and recovery blockers are available in the linked run view.</p>
    </div></aside>}
    </div>
  </div>;
}
