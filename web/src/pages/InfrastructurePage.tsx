import { Button, Disclosure, Field, KeyValueList, RecordTable, Section, Select, StatusBadge } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { Identifier } from '../components/Identifier';
import { InspectorPanel } from '../components/InspectorPanel';
import { DataInspector } from '../components/DataInspector';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { ComputeSetup } from '../components/ComputeSetup';
import { computeReadiness } from '../api/compute';
import { allResources } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import { statusLabel } from '../api/status';
import { ChartPanel, BarChart } from '../components/Charts';
import './operations.css';

interface Pool { id: number; name: string; status: string; queue_name: string; result_egress: string }
interface Worker { id: number; name: string; pool: number; pool_name: string; status: string; slots: number; capabilities: { setup_profile?: string; training_runtime?: string; memory_bytes?: number }; capacity?: { configured_slots: number; allocated_slots: number; free_slots: number | null; active_jobs: number; drain_requested: boolean; drain_acknowledged_at: string | null; ownership_unresolved: boolean; reason: string; observed_at: string }; connection_state?: string; last_heartbeat_at: string | null }
interface Runner { manifest_id: string; name: string; version: string; enabled: boolean; compatibility: unknown }
interface QueuedJob { job_id: string; name: string; queue_age_seconds: number; reason: string; requirements: unknown }

export function InfrastructurePage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [pools, setPools] = useState<Pool[]>([]); const [workers, setWorkers] = useState<Worker[]>([]); const [runners, setRunners] = useState<Runner[]>([]);
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [retry, setRetry] = useState(0);
  const [poolFilter, setPoolFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selectedWorker, setSelectedWorker] = useState<Worker | null>(null);
  const [canAdmin, setCanAdmin] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [actionError, setActionError] = useState('');
  const [queue, setQueue] = useState<QueuedJob[]>([]);
  const [queueError, setQueueError] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  async function revoke(worker: Worker) {
    setActionBusy(true); setActionError('');
    try { await apiRequest(`/api/v1/workers/${worker.id}/credential/revoke/`, token, { method: 'POST', body: '{}' }); setRetry(v => v + 1); }
    catch(e) { setActionError(errorMessage(e)); } finally { setActionBusy(false); }
  }
  useEffect(() => { const c = new AbortController(); setLoading(true); setError(null); setPools([]); setWorkers([]); setRunners([]); Promise.all([allResources<Pool>('/api/v1/worker-pools/', token, c.signal), allResources<Worker>('/api/v1/worker-inventory/', token, c.signal), allResources<Runner>('/api/v1/runner-manifests/', token, c.signal)]).then(([p, w, r]) => { if (!c.signal.aborted) { setPools(p); setWorkers(w); setRunners(r); setSelectedWorker(current => current ? w.find(worker => worker.id === current.id) || null : null); } }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); }); return () => c.abort(); }, [token, refreshKey, retry]);
  useEffect(() => { const c = new AbortController(); apiRequest<{ rows: QueuedJob[] }>('/api/v1/worker-inventory/queue-diagnosis/', token, { signal: c.signal }).then(result => { if (!c.signal.aborted) { setQueue(result.rows); setQueueError(''); } }).catch(e => { if (!c.signal.aborted) setQueueError(errorMessage(e)); }); return () => c.abort(); }, [token, refreshKey, retry]);
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
  const configured = (w: Worker) => w.capacity?.configured_slots ?? w.slots;
  const slotInventory = pools.map(p => ({ label: p.name, value: workers.filter(w => w.pool === p.id).reduce((total, w) => total + configured(w), 0), detail: `${workers.filter(w => w.pool === p.id).length} registered workers`, color: 0 }));
  const workerCounts = pools.map(p => ({ label: p.name, value: workers.filter(w => w.pool === p.id).length, color: 0 }));
  const capacity = selectedWorker?.capacity;
  const drainText = capacity ? capacity.drain_requested ? capacity.drain_acknowledged_at ? 'Drain acknowledged. Active jobs finish under their existing leases.' : 'Drain requested; new claims are blocked until the worker acknowledges.' : 'New claims are enabled while the worker is connected and its pool is active.' : null;

  return <div className="ops-page">
    <Section title="Workers" description="Registration state and last reported heartbeat." actions={<>
      <Field className="ops-search" aria-label="Search workers" placeholder="Search workers" value={query} onChange={e => setQuery(e.target.value)} />
      <Select aria-label="Filter worker pool" value={poolFilter} onChange={e => setPoolFilter(e.target.value)}><option value="all">All pools</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
      {canAdmin && <Button type="button" variant="primary" onClick={() => setSetupOpen(true)}>Register local worker</Button>}
      <Button type="button" variant="quiet" disabled={loading} onClick={() => setRetry(v => v + 1)}>Refresh</Button>
    </>}>
      <ResourceState loading={loading && !workers.length} error={error} onRetry={() => setRetry(v => v + 1)} />
      {actionError && <p role="alert" className="error-text">{actionError}</p>}
      <div data-ui="split" data-open={selectedWorker ? '' : undefined}>
        <div className="ops-main">
          {!loading && !error && <p className="ops-count">{filtered.length} of {workers.length} workers · {pools.length} {pools.length === 1 ? 'pool' : 'pools'}</p>}
          {!loading && !error && !filtered.length && <EmptyState title={workers.length ? 'No matching workers' : 'No workers registered'} description={workers.length ? 'Adjust the search or choose another pool.' : 'Register a local worker to run jobs on this computer.'} />}
          {!!filtered.length && <div className="table-scroll" tabIndex={0}><RecordTable>
            <thead><tr><th>Worker</th><th>Pool</th><th>State</th><th>Slots</th><th>Last heartbeat</th></tr></thead>
            <tbody>{filtered.map(w => <tr key={w.id} aria-selected={selectedWorker?.id === w.id || undefined}>
              <td><Button type="button" variant="quiet" size="sm" onClick={() => setSelectedWorker(w)}>{w.name}</Button></td>
              <td>{w.pool_name || 'Worker pool'}</td>
              <td><StatusBadge status={w.status} /></td>
              <td>{configured(w)} configured<small>{w.capacity?.allocated_slots ?? 'unknown'} allocated · {w.capacity?.free_slots ?? 'unknown'} free</small></td>
              <td>{w.last_heartbeat_at ? new Date(w.last_heartbeat_at).toLocaleString() : 'Not reported'}</td>
            </tr>)}</tbody>
          </RecordTable></div>}
        </div>
        {selectedWorker && <InspectorPanel key={selectedWorker.id} eyebrow="Worker" title={selectedWorker.name} closeLabel="Close worker details" onClose={() => setSelectedWorker(null)}>
          <div data-ui="actions"><StatusBadge status={selectedWorker.status} /><span className="muted">{computeReadiness(selectedWorker)}</span></div>
          <KeyValueList items={[
            { label: 'Pool', value: selectedWorker.pool_name },
            { label: 'Configured slots', value: configured(selectedWorker) },
            { label: 'Allocated', value: capacity?.allocated_slots ?? 'Unknown' },
            { label: 'Free', value: capacity?.free_slots ?? 'Unknown' },
            { label: 'Active jobs', value: capacity?.active_jobs ?? 'Unknown' },
            { label: 'Last heartbeat', value: selectedWorker.last_heartbeat_at ? new Date(selectedWorker.last_heartbeat_at).toLocaleString() : 'Not reported' },
            { label: 'Result egress', value: pools.find(p => p.id === selectedWorker.pool)?.result_egress || 'Not reported' },
            { label: 'Worker ID', value: <Identifier value={selectedWorker.id} label="Worker record ID" display="code" /> },
          ]} />
          {drainText && <p role="status">{drainText}</p>}
          {canAdmin && <div data-ui="actions">
            {capacity && <Button type="button" disabled={actionBusy} onClick={() => void drain('worker-inventory', selectedWorker.id, !capacity.drain_requested)}>{capacity.drain_requested ? 'Enable new worker claims' : 'Drain worker'}</Button>}
            <Button type="button" disabled={actionBusy} onClick={() => void revoke(selectedWorker)}>{actionBusy ? 'Revoking…' : 'Revoke worker credential'}</Button>
          </div>}
          <Disclosure summary="Capabilities" variant="quiet"><DataInspector value={selectedWorker.capabilities} /></Disclosure>
          {capacity && <Disclosure summary="Observed capacity" variant="quiet"><DataInspector value={capacity} /></Disclosure>}
          <p className="ops-footnote">Slot counts describe configured inventory. Free slots need a fresh connection and current allocations.</p>
        </InspectorPanel>}
      </div>
    </Section>
    <Disclosure summary="Pools" variant="card">
      {!loading && !error && !pools.length && <p className="muted">No pools registered.</p>}
      {!!pools.length && <div className="table-scroll" tabIndex={0}><RecordTable>
        <thead><tr><th>Pool</th><th>State</th><th>Queue</th><th>Result egress</th>{canAdmin && <th>Actions</th>}</tr></thead>
        <tbody>{pools.map(p => <tr key={p.id}><td>{p.name}</td><td><StatusBadge status={p.status} /></td><td>{p.queue_name || 'Default'}</td><td>{statusLabel(p.result_egress)}</td>
          {canAdmin && <td><div data-ui="actions">
            <Button type="button" size="sm" disabled={actionBusy} onClick={() => void drain('worker-pools', p.id, p.status === 'active')}>{p.status === 'active' ? 'Drain pool' : 'Enable pool claims'}</Button>
            <Select aria-label={`Result policy for ${p.name}`} disabled={actionBusy} value={p.result_egress} onChange={e => void changeEgress(p, e.target.value)} options={[{ value: 'envelope', label: 'Envelope' }, { value: 'metadata_only', label: 'Metadata only' }]} />
          </div></td>}
        </tr>)}</tbody>
      </RecordTable></div>}
    </Disclosure>
    <Disclosure summary="Queued jobs" variant="card">
      {queueError && <p role="alert" className="error-text">{queueError}</p>}
      {queue.length ? <div className="ops-queue">{queue.map(job => <div key={job.job_id}><a href={`#runs/job/${job.job_id}`}>{job.name}</a><p>{job.queue_age_seconds} seconds queued · {job.reason}</p><Disclosure summary="Requirements" variant="quiet"><DataInspector value={job.requirements} /></Disclosure></div>)}</div>
        : !queueError && <p className="muted">No accessible queued work in this snapshot.</p>}
    </Disclosure>
    <Disclosure summary="Runner manifests" variant="card">
      {!loading && !error && !runners.length && <p className="muted">No runner manifests registered.</p>}
      {runners.map(r => <Disclosure key={r.manifest_id} summary={`${r.name} · ${r.version} · ${r.enabled ? 'Enabled' : 'Disabled'}`} variant="quiet"><DataInspector value={r.compatibility} /></Disclosure>)}
    </Disclosure>
    <Disclosure summary="Insights" variant="card"><div className="ops-charts">
      <ChartPanel title="Workers by pool" description="Registered workers in each pool."><BarChart data={workerCounts} unit="workers" emptyMessage="No pool registrations are available." /></ChartPanel>
      <ChartPanel title="Configured slot inventory" description="Sum of registered worker slots by pool."><BarChart data={slotInventory} unit="configured slots" emptyMessage="No pool registrations are available." /></ChartPanel>
    </div></Disclosure>
    <ComputeSetup token={token} open={setupOpen} onClose={() => setSetupOpen(false)} onPermission={setCanAdmin} onRegistered={() => setRetry(v => v + 1)} />
  </div>;
}
