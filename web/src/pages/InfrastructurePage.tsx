import { ExternalCompute } from '../components/ExternalCompute';
import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, FactList, Field, MetricSummary, Notice, RecordTable } from '../components/ui';
import { Feedback } from '../components/Feedback';
import { InspectorPanel } from '../components/InspectorPanel';
import { DataInspector } from '../components/DataInspector';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { ComputeSetup } from '../components/ComputeSetup';
import { computeReadiness } from '../api/compute';
import { allResources } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import { ChartPanel, ChartEmpty, BarChart } from '../components/Charts';
import { ArrowRight, Server, Cpu, Layers } from 'lucide-react';
import './operations.css';
interface Pool { id: number; name: string; status: string; queue_name: string; result_egress: string }
interface Worker { id: number; name: string; pool: number; pool_name: string; status: string; slots: number; capabilities: { setup_profile?: string; training_runtime?: string; memory_bytes?: number }; capacity?: { configured_slots: number; allocated_slots: number; free_slots: number | null; active_jobs: number; drain_requested: boolean; drain_acknowledged_at: string | null; ownership_unresolved: boolean; reason: string; observed_at: string }; connection_state?: string; last_heartbeat_at: string | null }
interface Runner { manifest_id: string; name: string; version: string; enabled: boolean; compatibility: unknown }
export function InfrastructurePage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [pools, setPools] = useState<Pool[]>([]); const [workers, setWorkers] = useState<Worker[]>([]); const [runners, setRunners] = useState<Runner[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [retry, setRetry] = useState(0);
  const [poolFilter, setPoolFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selectedWorker, setSelectedWorker] = useState<Worker | null>(null);
  const [canAdmin, setCanAdmin] = useState(false);
  const [actionError, setActionError] = useState('');
  const [queue, setQueue] = useState<{ job_id: string; name: string; queue_age_seconds: number; reason: string; requirements: unknown }[]>([]);
  const [queueError, setQueueError] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  async function revoke(worker: Worker) {
    setActionBusy(true); setActionError('');
    try { await apiRequest(`/api/v1/workers/${worker.id}/credential/revoke/`, token, { method: 'POST', body: '{}' }); setRetry(v => v + 1); }
    catch(e) { setActionError(errorMessage(e)); } finally { setActionBusy(false); }
  }
  useEffect(() => { const c = new AbortController(); setLoading(true); setError(null); setPools([]); setWorkers([]); setRunners([]); Promise.all([allResources<Pool>('/api/v1/worker-pools/', token, c.signal), allResources<Worker>('/api/v1/worker-inventory/', token, c.signal), allResources<Runner>('/api/v1/runner-manifests/', token, c.signal)]).then(([p, w, r]) => { if (!c.signal.aborted) { setPools(p); setWorkers(w); setRunners(r); setSelectedWorker(current => current ? w.find(worker => worker.id === current.id) || null : null); } }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); }); return () => c.abort(); }, [token, refreshKey, retry]);
  useEffect(() => { const c = new AbortController(); apiRequest<{ rows: typeof queue }>('/api/v1/worker-inventory/queue-diagnosis/', token, { signal: c.signal }).then(result => { if (!c.signal.aborted) { setQueue(result.rows); setQueueError(''); } }).catch(e => { if (!c.signal.aborted) setQueueError(errorMessage(e)); }); return () => c.abort(); }, [token, refreshKey, retry]);
  useEffect(() => { const timer = setInterval(() => { if (document.visibilityState === 'visible') setRetry(v => v+1); }, 15000); return () => clearInterval(timer); }, []);
  async function drain(type: 'worker-inventory' | 'worker-pools', id: number, draining: boolean) {
    setActionBusy(true); setActionError('');
    try { await apiRequest(`/api/v1/${type}/${id}/drain/`, token, { method: 'POST', body: JSON.stringify({ draining }) }); setRetry(v => v+1); }
    catch (e) { setActionError(errorMessage(e)); } finally { setActionBusy(false); }
  }
  async function changeEgress(pool: Pool, result_egress: string) {
    setActionBusy(true); setActionError('');
    try { await apiRequest(`/api/v1/worker-pools/${pool.id}/result-policy/`, token, { method: 'POST', body: JSON.stringify({ result_egress }) }); setRetry(v => v+1); }
    catch (e) { setActionError(errorMessage(e)); } finally { setActionBusy(false); }
  }
  const filtered = workers.filter(w => (poolFilter === 'all' || String(w.pool) === poolFilter) && `${w.name} ${w.pool_name} ${w.status}`.toLowerCase().includes(query.toLowerCase()));
  const slotInventory = pools.map(p => ({ label: p.name, value: workers.filter(w => w.pool === p.id).reduce((total, w) => total + (w.capacity?.configured_slots ?? w.slots), 0), detail: `${workers.filter(w => w.pool === p.id).length} registered workers · inspect per-worker allocation and freshness`, color: 0 }));
  return <div className="resource-view operations-page">
    <div className="page-actions"><a className="ops-link-button" href="#workflows">Submit a job <ArrowRight size={16} aria-hidden="true" /></a></div>
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
    <ExternalCompute key={token} token={token} refreshKey={refreshKey} onChange={() => setRetry(value => value + 1)} />
    <details className="workspace-details"><summary>Set up or connect compute</summary><ComputeSetup token={token} onPermission={setCanAdmin} onRegistered={() => setRetry(v => v + 1)} /></details>
    {actionError && <Notice tone="error" role="alert">{actionError}</Notice>}
    <div className="cards"><MetricSummary as="article" label="Registered pools" value={loading || error ? '—' : pools.length} icon={<Server size={18} aria-hidden="true" />} /><MetricSummary as="article" label="Registered workers" value={loading || error ? '—' : workers.length} icon={<Cpu size={18} aria-hidden="true" />} /><MetricSummary as="article" label="Configured slots" value={loading || error ? '—' : workers.reduce((sum, w) => sum + (w.capacity?.configured_slots ?? w.slots), 0)} icon={<Layers size={18} aria-hidden="true" />} /></div>
    <details className="workspace-details"><summary>Pool topology and capacity</summary><div className="ops-chart-grid">
      <ChartPanel title="Registered pool topology" description="Registered queues and worker memberships. Connections show configuration.">
        {pools.length ? <div className="ops-topology"><div className="ops-topology-origin"><Server size={20} aria-hidden="true" /><strong>Worker inventory</strong><small>{workers.length} registered workers</small></div><div className="ops-pool-nodes">{pools.map(p => <Button key={p.id} className={`ops-pool-node ${poolFilter === String(p.id) ? 'active' : ''}`} aria-pressed={poolFilter === String(p.id)} onClick={() => setPoolFilter(current => current === String(p.id) ? 'all' : String(p.id))}><ArrowRight size={16} aria-hidden="true" /><div><strong>{p.name}</strong><small>{workers.filter(w => w.pool === p.id).length} workers</small><small>Queue: {p.queue_name || 'Default'}</small></div><Badge className={`state state-${p.status}`}>{p.status}</Badge></Button>)}</div></div> : <ChartEmpty message="Register a worker pool through the API to see its configured topology." />}
      </ChartPanel>
      <ChartPanel title="Configured slot inventory" description="Sum of registered worker slots by pool. Configured capacity is shown here; per-worker rows distinguish allocated and observed free slots."><BarChart data={slotInventory} unit="configured slots" emptyMessage="No pool registrations are available." /></ChartPanel>
    </div>
    </details>
    <div className={`ops-workspace ${selectedWorker ? 'with-inspector' : ''}`}>
      <Card className="panel"><div className="panel-title"><div><h2>Workers</h2><p>Registration state and last reported heartbeat.</p></div><Badge className="badge">Inventory</Badge></div><div className="panel-body">
        <div className="toolbar"><Field aria-label="Search workers" placeholder="Search worker, pool or state" value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="Filter worker pool" value={poolFilter} onChange={e => setPoolFilter(e.target.value)}><option value="all">All pools</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><small className="muted">{filtered.length} of {workers.length} workers</small></div>
        <p className="ops-scope">Registration status is reported by the backend. Check the heartbeat timestamp before assuming a worker is healthy.</p>
        {!loading && !error && !filtered.length && <Feedback state="empty" title={workers.length ? 'No matching workers' : 'No workers registered'} description={workers.length ? 'Adjust the search or select a different pool.' : 'Worker registrations will appear here when added through the API.'} />}
        {!!filtered.length && <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table"><thead><tr><th>Worker</th><th>Pool</th><th>Registration state</th><th>Configured slots</th><th>Last heartbeat</th><th>Capabilities</th></tr></thead><tbody>{filtered.map(w => <tr key={w.id} className={selectedWorker?.id === w.id ? 'ops-selected-row' : ''}><td><Button className="text-button" onClick={() => setSelectedWorker(w)}>{w.name}</Button><Identifier value={w.id} label="Worker record ID" /></td><td>{w.pool_name || 'Worker pool'}<Identifier value={w.pool} label="Pool record ID" /></td><td><Badge className={`state state-${w.status}`}>{w.status}</Badge></td><td>{w.capacity?.configured_slots ?? w.slots} configured · {w.capacity?.allocated_slots ?? 'unknown'} allocated · {w.capacity?.free_slots ?? 'unknown'} free</td><td>{w.last_heartbeat_at ? new Date(w.last_heartbeat_at).toLocaleString() : 'Not reported'}</td><td><details><summary>Inspect</summary><DataInspector value={w.capabilities} /></details></td></tr>)}</tbody></RecordTable></div>}
      </div></Card>
      {selectedWorker && <InspectorPanel eyebrow="Worker registration" title={selectedWorker.name} closeLabel="Close worker details" onClose={() => setSelectedWorker(null)}><p role="status">{computeReadiness(selectedWorker)}</p>{canAdmin && <Button disabled={actionBusy} onClick={() => void revoke(selectedWorker)}>{actionBusy ? 'Revoking…' : 'Revoke worker credential'}</Button>}<FactList><div><dt>Pool</dt><dd>{selectedWorker.pool_name}</dd></div><div><dt>Registration state</dt><dd>{selectedWorker.status}</dd></div><div><dt>Configured slots</dt><dd>{selectedWorker.capacity?.configured_slots ?? selectedWorker.slots}</dd></div><div><dt>Last heartbeat</dt><dd>{selectedWorker.last_heartbeat_at ? new Date(selectedWorker.last_heartbeat_at).toLocaleString() : 'Not reported'}</dd></div><div><dt>Result egress</dt><dd>{pools.find(p => p.id === selectedWorker.pool)?.result_egress || 'Not reported'}</dd></div></FactList>{selectedWorker.capacity && <><h3>Observed capacity</h3><DataInspector value={selectedWorker.capacity} /><p role="status">{selectedWorker.capacity.drain_requested ? selectedWorker.capacity.drain_acknowledged_at ? 'Worker claim loop acknowledged drain. Active jobs finish under their existing leases.' : 'Drain requested; new claims are blocked. Waiting for the worker claim loop to acknowledge.' : 'New claims are enabled for this worker when connected and its pool is active.'}</p>{canAdmin && <Button disabled={actionBusy} onClick={() => void drain('worker-inventory', selectedWorker.id, !selectedWorker.capacity?.drain_requested)}>{selectedWorker.capacity.drain_requested ? 'Enable new worker claims' : 'Drain worker'}</Button>}</>}<h3>Capabilities</h3><DataInspector value={selectedWorker.capabilities} /><p className="ops-scope">Slot counts describe configured inventory. Available slots come from fresh worker connection and current allocations. Stale or drained capacity stays unknown.</p></InspectorPanel>}
    </div>
    <Card className="panel"><div className="panel-title"><div><h2>Pool configuration</h2><p>Queue and result egress configuration returned by the backend.</p></div></div><div className="panel-body">{!!pools.length && <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table"><thead><tr><th>Pool ID</th><th>Name</th><th>State</th><th>Queue</th><th>Result egress</th></tr></thead><tbody>{pools.map(p => <tr key={p.id}><td><Identifier value={p.id} label="Pool record ID" /></td><td>{p.name}</td><td><Badge className={`state state-${p.status}`}>{p.status}</Badge></td><td>{p.queue_name || 'Default'}</td><td>{p.result_egress}{canAdmin && <><Button disabled={actionBusy} onClick={() => void drain('worker-pools', p.id, p.status === 'active')}>{p.status === 'active' ? 'Drain pool' : 'Enable pool claims'}</Button><label>Result policy<select disabled={actionBusy} value={p.result_egress} onChange={e => void changeEgress(p, e.target.value)}><option value="envelope">Envelope</option><option value="metadata_only">Metadata only</option></select></label></>}</td></tr>)}</tbody></RecordTable></div>}{!loading && !error && !pools.length && <p className="muted">No pools registered.</p>}</div></Card>
    <Card className="panel"><div className="panel-title"><h2>Queued job diagnosis</h2></div><div className="panel-body">{queueError && <p role="alert">{queueError}</p>}{queue.length ? queue.map(job => <div className="detail-box" key={job.job_id}><a href={`#runs/job/${job.job_id}`}>{job.name}</a><p>{job.queue_age_seconds} seconds queued · {job.reason}</p><DataInspector value={job.requirements} /></div>) : !queueError && <p>No accessible queued work in this snapshot.</p>}</div></Card>
    <Card className="panel"><div className="panel-title"><div><h2>Runner manifests</h2><p>Recorded versions and compatibility declarations.</p></div><Badge className="badge">{runners.length} registered</Badge></div><div className="panel-body ops-runner-list">{!loading && !error && !runners.length && <p className="muted">No runner manifests registered.</p>}{runners.map(r => <details key={r.manifest_id}><summary>{r.name} · {r.version} · {r.enabled ? 'Enabled' : 'Disabled'}</summary><DataInspector value={r.compatibility} /></details>)}</div></Card>
  </div>;
}
