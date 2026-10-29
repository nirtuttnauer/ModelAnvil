import { useEffect, useRef, useState } from 'react';
import { ApiRequestError, apiRequest, errorMessage } from '../api/client';
import { allResources } from '../api/resources';
import { Button, Disclosure, MultilineControl, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from './ui';
import { EmptyState, Feedback } from './Feedback';

interface Plugin { id: string; kind: 'compute' | 'task'; name: string; digest: string; can_manage: boolean; can_submit: boolean; configuration_schema: { properties?: Record<string, unknown> } }
interface Allocation { allocation_id: string; request_id: string; plugin_id: string; pool: number; worker_id: number; state: string; provider_status: string; worker_connected: boolean; expires_at: string; error_code: string }
interface Pool { id: number; name: string; status: string }
interface Policy { policy_id: string; name: string; enabled: boolean; unit: string }
interface GPU { id: string; name?: string; memory?: number; availability?: string; price?: { secure?: number; community?: number }; dataCenters?: { id: string; name?: string }[] }

export function ExternalCompute({ token, refreshKey, onChange }: { token: string; refreshKey: number; onChange: () => void }) {
  const [plugins, setPlugins] = useState<Plugin[]>([]), [allocations, setAllocations] = useState<Allocation[]>([]);
  const [pools, setPools] = useState<Pool[]>([]), [policies, setPolicies] = useState<Policy[]>([]);
  const [selected, setSelected] = useState(''), [pool, setPool] = useState(''), [policy, setPolicy] = useState('');
  const [catalog, setCatalog] = useState<GPU[]>([]), [gpu, setGPU] = useState(''), [dataCenter, setDataCenter] = useState('');
  const [cloud, setCloud] = useState('SECURE'), [count, setCount] = useState(1), [disk, setDisk] = useState(50);
  const [minutes, setMinutes] = useState(60), [configuration, setConfiguration] = useState('{}');
  const [estimate, setEstimate] = useState(1);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [catalogLoading, setCatalogLoading] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [retry, setRetry] = useState(0);
  const submission = useRef<{ body: string; key: string } | null>(null);
  const plugin = plugins.find(row => row.id === selected);
  const runpodFields = plugin?.kind === 'compute' && !!plugin.configuration_schema.properties?.gpu_id;
  const canManage = plugins.some(row => row.can_manage);
  const selectedGPU = catalog.find(row => row.id === gpu);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    Promise.all([
      apiRequest<{ results: Plugin[] }>('/api/v1/compute-plugins/', token, { signal: controller.signal }, 'organization'),
      allResources<Allocation>('/api/v1/compute-allocations/', token, controller.signal, 'organization'),
      allResources<Pool>('/api/v1/worker-pools/', token, controller.signal, 'organization'),
      allResources<Policy>('/api/v1/budget-policies/', token, controller.signal, 'organization'),
    ]).then(([p, a, poolRows, policyRows]) => {
      if (controller.signal.aborted) return;
      setPlugins(p.results); setAllocations(a); setPools(poolRows.filter(row => row.status === 'active'));
      setPolicies(policyRows.filter(row => row.enabled));
      const recovered = a.find(row => row.request_id === submission.current?.key);
      if (recovered) { submission.current = null; setNotice(`Previous allocation recovered: ${recovered.state}.`); }
    }).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refreshKey, retry]);

  useEffect(() => {
    const controller = new AbortController(); setCatalog([]); setGPU(''); setDataCenter(''); setPolicy('');
    if (plugin?.kind !== 'compute') return () => controller.abort();
    setCatalogLoading(true);
    apiRequest<{ results: GPU[] }>(`/api/v1/compute-plugins/${encodeURIComponent(plugin.id)}/catalog/`, token, { signal: controller.signal }, 'organization')
      .then(data => { if (!controller.signal.aborted) setCatalog(data.results); })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setCatalogLoading(false); });
    return () => controller.abort();
  }, [selected, token]);

  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!plugin) return; setBusy(true); setError(''); setNotice('');
    try {
      const config = runpodFields ? { gpu_id: gpu, gpu_count: count, disk_gb: disk, cloud, data_center_ids: [dataCenter] } : JSON.parse(configuration);
      const body = plugin.kind === 'compute'
        ? { plugin_id: plugin.id, pool: Number(pool), policy_id: policy, spec: config, lifetime_seconds: minutes * 60 }
        : { name: plugin.name, pool: Number(pool), requirements: { task_plugin: plugin.id, task_plugin_digest: plugin.digest }, payload: { configuration: config }, budget_policy_id: policy, estimated_amount: estimate };
      const serialized = JSON.stringify(body);
      if (submission.current && submission.current.body !== serialized) throw new Error('A previous request is unresolved. Retry it unchanged or inspect its status before changing the configuration.');
      submission.current ??= { body: serialized, key: crypto.randomUUID() };
      const { key } = submission.current;
      if (plugin.kind === 'compute') {
        const result = await apiRequest<Allocation>('/api/v1/compute-allocations/', token, { method: 'POST', body: JSON.stringify({ ...body, request_id: key }) }, 'organization');
        setNotice(`Allocation ${result.state}${result.error_code ? `: ${result.error_code}` : ''}. Use Refresh status to reconcile; a running pod may still be connecting.`);
      } else {
        await apiRequest('/api/v1/jobs/', token, { method: 'POST', headers: { 'Idempotency-Key': key }, body: serialized });
        setNotice('Plugin job submitted. Follow its result in Jobs.');
      }
      submission.current = null; setRetry(value => value + 1); onChange();
    } catch (e) {
      if (e instanceof ApiRequestError && e.status < 500 && e.status !== 409) submission.current = null;
      setError(errorMessage(e));
    } finally { setBusy(false); }
  }

  async function update(allocation: Allocation, action: 'refresh' | 'release') {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await apiRequest<Allocation>(`/api/v1/compute-allocations/${allocation.allocation_id}/${action}/`, token, { method: 'POST', body: '{}' }, 'organization');
      setAllocations(rows => rows.map(row => row.allocation_id === result.allocation_id ? result : row));
      setNotice(`Allocation ${result.state}${result.error_code ? `: ${result.error_code}` : ''}.`); onChange();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  const budgetUnit = policies.find(row => row.policy_id === policy)?.unit;
  return <Section title="External compute and plugins" description="Rent GPU capacity or run an installed custom task." actions={<Button type="button" disabled={busy || loading} onClick={() => setRetry(value => value + 1)}>Refresh</Button>}>
    {loading && <Feedback state="loading" title="Loading providers…" />}
    {error && <Notice tone="error" role="alert">{error}</Notice>}{notice && <Notice tone="success" role="status">{notice}</Notice>}
    {!loading && !plugins.length && !error && <EmptyState title="No providers or task plugins are configured for this organization" description="Ask an administrator to install and configure one." />}
    {!!plugins.length && <form data-ui="form" onSubmit={submit}>
      <div data-ui="field-grid">
        <Select label="Provider or task" value={selected} required disabled={busy} onChange={e => { setSelected(e.target.value); setConfiguration('{}'); setError(''); }}><option value="">Choose a provider or task</option>{plugins.map(row => <option key={row.id} value={row.id}>{row.name} ({row.kind})</option>)}</Select>
        <Select label="Worker pool" value={pool} required disabled={busy} onChange={e => setPool(e.target.value)}><option value="">Choose a pool</option>{pools.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</Select>
        <Select label="Budget" value={policy} required disabled={busy} onChange={e => setPolicy(e.target.value)}><option value="">Choose a budget</option>{policies.filter(row => plugin?.kind !== 'compute' || row.unit === 'allocation_seconds').map(row => <option key={row.policy_id} value={row.policy_id}>{row.name} ({row.unit})</option>)}</Select>
        {plugin && (runpodFields ? <>
          <Select label="GPU" required value={gpu} disabled={busy || catalogLoading} onChange={e => { setGPU(e.target.value); setDataCenter(''); }}><option value="">{catalogLoading ? 'Loading GPUs…' : 'Choose a GPU'}</option>{catalog.map(row => <option key={row.id} value={row.id}>{row.name || row.id}{row.memory ? ` · ${row.memory} GB` : ''}</option>)}</Select>
          <Select label="Data center" required value={dataCenter} disabled={busy} onChange={e => setDataCenter(e.target.value)}><option value="">Choose a data center</option>{selectedGPU?.dataCenters?.map(row => <option key={row.id} value={row.id}>{row.name || row.id}</option>)}</Select>
          <Select label="Cloud tier" value={cloud} disabled={busy} onChange={e => setCloud(e.target.value)} options={[{ value: 'SECURE', label: 'Secure' }, { value: 'COMMUNITY', label: 'Community' }]} />
          <TextControl label="GPU count" type="number" min={1} max={8} required value={count} disabled={busy} onChange={e => setCount(Number(e.target.value))} />
          <TextControl label="Disk (GB)" type="number" min={1} max={1000} required value={disk} disabled={busy} onChange={e => setDisk(Number(e.target.value))} />
        </> : <div data-span="full" data-ui="form">
          <MultilineControl label="Task or provider configuration (JSON)" value={configuration} disabled={busy} rows={5} required onChange={e => setConfiguration(e.target.value)} />
          <Disclosure summary="Configuration fields" variant="quiet"><pre>{JSON.stringify(plugin.configuration_schema, null, 2)}</pre></Disclosure>
        </div>)}
        {plugin && (plugin.kind === 'compute'
          ? <TextControl label="Maximum rental time (minutes)" required type="number" min={1} max={1440} value={minutes} disabled={busy} onChange={e => setMinutes(Number(e.target.value))} />
          : <TextControl label={`Budget estimate (${budgetUnit || 'choose a budget'})`} required type="number" min={0.000001} step="any" value={estimate} disabled={busy} onChange={e => setEstimate(Number(e.target.value))} />)}
      </div>
      {plugin && <>
        <div data-ui="actions"><Button type="submit" variant="primary" disabled={busy || loading || (plugin.kind === 'compute' ? !plugin.can_manage : !plugin.can_submit)}>{busy ? 'Submitting…' : plugin.kind === 'compute' ? 'Rent GPU' : 'Run task plugin'}</Button></div>
        {plugin.kind === 'compute' && <p className="muted">Rental charges begin when the provider allocates capacity. Storage and transfers may cost extra. Automatic expiry release requires the compute reconciler to be running.</p>}
        {plugin.kind === 'compute' && !plugin.can_manage && <Notice tone="caution">Renting and releasing capacity requires an organization administrator key.</Notice>}
      </>}
    </form>}
    {!!allocations.length && <div className="table-scroll" tabIndex={0}><RecordTable><caption>External allocations</caption>
      <thead><tr><th>Provider / worker</th><th>Allocation</th><th>Provider</th><th>Worker</th><th>Expires</th><th>Actions</th></tr></thead>
      <tbody>{allocations.map(row => <tr key={row.allocation_id}>
        <td>{row.plugin_id} · #{row.worker_id}</td>
        <td><StatusBadge status={row.state} />{row.error_code && <small>{row.error_code}</small>}</td>
        <td>{row.provider_status || 'Unknown'}</td>
        <td>{row.worker_connected ? 'Recent heartbeat' : 'No recent heartbeat'}</td>
        <td>{new Date(row.expires_at).toLocaleString()}</td>
        <td>{canManage && !['released', 'failed'].includes(row.state) && <div data-ui="actions"><Button type="button" size="sm" disabled={busy} onClick={() => void update(row, 'refresh')}>Refresh status</Button><Button type="button" size="sm" disabled={busy} onClick={() => void update(row, 'release')}>Release capacity</Button></div>}</td>
      </tr>)}</tbody>
    </RecordTable></div>}
  </Section>;
}
