import React from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import { BarChart, ChartPanel, EventTimeline } from '../components/Charts';
import { Database, Download, ExternalLink, Search, ShieldCheck } from 'lucide-react';
import './data-workspace.css';

interface DatasetBankPageProps { token?: string; refreshKey?: number; onImportSuccess?: () => void }
interface BankSource {
  id: string; name: string; category: string; source_kind: string; description: string;
  source_url: string; modalities: string[]; use_cases: string[]; license: string;
  eligibility: string; download_enabled: boolean; acquisition_available: boolean;
  acquisition_status: string; acquisition_blocked_reason: string; pinned_revision: string;
  acquisition_record_limit?: number;
  size_bytes: number | null; is_size_measured: boolean;
}
interface BudgetPolicy { policy_id: string; name: string; unit: string; currency: string; enabled: boolean }
interface Acquisition {
  snapshot_id: string; source_id: string; state: string; verified_records: number; planned_records: number;
  transferred_bytes: number; planned_bytes: number; row_count: number | null; revision_id: string | null;
  revision_no: number | null; manifest_digest: string; failures: unknown[]; job: { status: string; desired_action: string } | null;
}

export function DatasetBankPage({ token, onImportSuccess, refreshKey = 0 }: DatasetBankPageProps) {
  const [error, setError] = React.useState<string | null>(null);
  const [sources, setSources] = React.useState<BankSource[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [query, setQuery] = React.useState('');
  const [selectedModality, setSelectedModality] = React.useState('all');
  const [selectedId, setSelectedId] = React.useState('');
  const [importingId, setImportingId] = React.useState<string | null>(null);
  const [importStatus, setImportStatus] = React.useState<Record<string, { success: boolean; message: string }>>({});
  const [acquisitions, setAcquisitions] = React.useState<Record<string, Acquisition>>({});
  const [budgetPolicies, setBudgetPolicies] = React.useState<BudgetPolicy[]>([]);
  const [budgetLoading, setBudgetLoading] = React.useState(true);
  const [budgetError, setBudgetError] = React.useState<string | null>(null);
  const [budgetRetry, setBudgetRetry] = React.useState(0);
  const [budgetPolicyId, setBudgetPolicyId] = React.useState('');
  const [estimatedAmount, setEstimatedAmount] = React.useState('');
  const selectedBudget = budgetPolicies.find(policy => policy.policy_id === budgetPolicyId);
  const validEstimate = /^\d{1,18}(?:\.\d{1,6})?$/.test(estimatedAmount.trim()) && Number(estimatedAmount) > 0;
  const budgetReady = !budgetLoading && !budgetError && (!budgetPolicies.length || (selectedBudget?.unit === 'bank_acquisition_records' && validEstimate));
  const budgetBody = budgetPolicies.length ? { budget_policy_id: budgetPolicyId, estimated_amount: estimatedAmount.trim() } : {};
  const acquisitionRequest = React.useRef<AbortController | null>(null);
  const currentToken = React.useRef(token);
  currentToken.current = token;

  React.useEffect(() => {
    setAcquisitions({}); setImportStatus({}); setImportingId(null); setBudgetPolicyId(''); setEstimatedAmount('');
    return () => { acquisitionRequest.current?.abort(); acquisitionRequest.current = null; };
  }, [token]);
  React.useEffect(() => {
    const controller = new AbortController();
    setSources([]); setError(null);
    if (!token?.trim()) { setLoading(false); setError('Enter an API key to load the catalog.'); return; }
    setLoading(true);
    apiRequest<{ sources: BankSource[] }>('/api/v1/dataset-bank/sources/', token, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setSources(data.sources); })
      .catch(err => { if (!controller.signal.aborted) setError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refreshKey]);

  React.useEffect(() => {
    const controller = new AbortController();
    setBudgetLoading(true); setBudgetError(null); setBudgetPolicies([]);
    allResources<BudgetPolicy>('/api/v1/budget-policies/', token || '', controller.signal)
      .then(policies => { if (!controller.signal.aborted) {
        const enabled = policies.filter(policy => policy.enabled);
        setBudgetPolicies(enabled);
        setBudgetPolicyId(current => enabled.some(policy => policy.policy_id === current) ? current : '');
      } })
      .catch(err => { if (!controller.signal.aborted) setBudgetError(errorMessage(err)); })
      .finally(() => { if (!controller.signal.aborted) setBudgetLoading(false); });
    return () => controller.abort();
  }, [token, refreshKey, budgetRetry]);

  async function handleImport(source: BankSource) {
    if (!token?.trim() || acquisitionRequest.current || !budgetReady || !source.acquisition_available || !source.download_enabled || source.eligibility !== 'eligible') return;
    const requestToken = token;
    const controller = new AbortController();
    acquisitionRequest.current = controller;
    const isCurrent = () => !controller.signal.aborted && acquisitionRequest.current === controller && currentToken.current === requestToken;
    setImportingId(source.id);
    try {
      await apiRequest(`/api/v1/dataset-bank/sources/${source.id}/preflight/`, token, { method: 'POST', body: '{}', signal: controller.signal });
      if (!isCurrent()) return;
      const data = await apiRequest<Acquisition>(`/api/v1/dataset-bank/sources/${source.id}/acquisitions/`, token, { method: 'POST', body: JSON.stringify(budgetBody), signal: controller.signal });
      if (!isCurrent()) return;
      setAcquisitions(previous => ({ ...previous, [source.id]: data }));
      setImportStatus(prev => ({ ...prev, [source.id]: { success: true, message: data.revision_id ? `Published revision ${data.revision_no} · ${data.row_count?.toLocaleString()} canonical samples` : 'Acquisition queued. A registered worker will download, verify, and publish the samples.' } }));
      if (data.revision_id) onImportSuccess?.();
    } catch (err) {
      if (isCurrent()) setImportStatus(prev => ({ ...prev, [source.id]: { success: false, message: errorMessage(err) } }));
    } finally { if (isCurrent()) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  async function updateAcquisition(source: BankSource, action?: 'cancel' | 'resume') {
    const acquisition = acquisitions[source.id];
    if (!acquisition || !token?.trim() || acquisitionRequest.current || (action === 'resume' && !budgetReady)) return;
    const requestToken = token;
    const controller = new AbortController();
    acquisitionRequest.current = controller;
    const isCurrent = () => !controller.signal.aborted && acquisitionRequest.current === controller && currentToken.current === requestToken;
    setImportingId(source.id);
    try {
      const data = await apiRequest<Acquisition>(`/api/v1/dataset-bank/acquisitions/${acquisition.snapshot_id}/${action ? `${action}/` : ''}`, token, action ? { method: 'POST', body: JSON.stringify(action === 'resume' ? budgetBody : {}), signal: controller.signal } : { signal: controller.signal });
      if (!isCurrent()) return;
      setAcquisitions(previous => ({ ...previous, [source.id]: data }));
      setImportStatus(previous => ({ ...previous, [source.id]: { success: data.state !== 'failed', message: data.revision_id ? `Published revision ${data.revision_no} · ${data.row_count?.toLocaleString()} canonical samples` : `Acquisition ${data.state.replaceAll('_', ' ')} · ${data.verified_records}/${data.planned_records} records verified` } }));
      if (data.revision_id && !acquisition.revision_id) onImportSuccess?.();
    } catch (err) {
      if (isCurrent()) setImportStatus(previous => ({ ...previous, [source.id]: { success: false, message: errorMessage(err) } }));
    } finally { if (isCurrent()) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  const modalities = [...new Set(sources.flatMap(source => source.modalities || []))].sort();
  const filtered = sources.filter(source => [source.name, source.description, source.license].some(value => value.toLowerCase().includes(query.toLowerCase()))
    && (selectedModality === 'all' || source.modalities?.includes(selectedModality)));
  const selected = filtered.find(source => source.id === selectedId) || filtered[0];
  const status = selected ? importStatus[selected.id] : undefined;
  const acquisition = selected ? acquisitions[selected.id] : undefined;

  return <div className="data-workspace dataset-bank-page">
    <ResourceState loading={loading} error={error} />
    <section className="panel data-filter-panel"><div className="data-filter-row"><label className="data-search"><Search size={17} aria-hidden="true" /><input type="search" aria-label="Search dataset sources" placeholder="Search sources, descriptions, or licenses…" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>Modality<select value={selectedModality} onChange={e => setSelectedModality(e.target.value)}><option value="all">All modalities</option>{modalities.map(modality => <option key={modality} value={modality}>{modality}</option>)}</select></label>
      <button onClick={() => { setQuery(''); setSelectedModality('all'); }} disabled={!query && selectedModality === 'all'}>Clear filters</button></div></section>
    <div className="data-inspector-layout">
      <div className="data-catalog-column"><section className="panel"><div className="panel-title"><div><h2>Source catalog</h2><p>Curated open data for training and evaluation.</p></div><span className="badge">{filtered.length} / {sources.length} SOURCES</span></div>
        <div className="table-scroll" tabIndex={0}><table className="resource-table data-source-table"><thead><tr><th>Source</th><th>Modality</th><th>License</th><th>Eligibility</th><th>Inspect</th></tr></thead><tbody>{filtered.map(source => <tr key={source.id} className={selected?.id === source.id ? 'data-selected-row' : ''}>
          <td><div className="data-source-name"><span className="data-source-icon"><Database size={18} aria-hidden="true" /></span><div><strong>{source.name}</strong><small>{source.description}</small></div></div></td>
          <td><div className="data-tags">{source.modalities?.map(modality => <span className="badge" key={modality}>{modality}</span>)}</div></td><td>{source.license || 'Not provided'}</td>
          <td><span className={`state state-${source.eligibility === 'eligible' ? 'ready' : 'pending'}`}>{source.eligibility.replaceAll('_', ' ')}</span></td>
          <td><button aria-pressed={selected?.id === source.id} aria-label={`Inspect ${source.name}`} onClick={() => setSelectedId(source.id)}>Inspect</button></td></tr>)}
          {!loading && !filtered.length && <tr><td colSpan={5}><div className="empty-state"><h3>{error ? 'Catalog unavailable' : 'No matching sources'}</h3><p>{error ? 'Check your connection and refresh the catalog.' : 'Try another search or clear your filters.'}</p></div></td></tr>}</tbody></table></div></section>
        <div className="visualization-grid equal"><ChartPanel title="Catalog composition" description="Source counts in the loaded catalog. A source can have multiple modalities."><BarChart data={modalities.map(modality => ({ label: modality, value: sources.filter(source => source.modalities?.includes(modality)).length }))} unit="Sources" emptyMessage="Connect to load the curated catalog." /></ChartPanel>
          <ChartPanel title="Import eligibility" description="Catalog policy status; sample counts are available after import."><BarChart data={[...new Set(sources.map(source => source.eligibility))].map(eligibility => ({ label: eligibility.replaceAll('_', ' '), value: sources.filter(source => source.eligibility === eligibility).length }))} unit="Sources" emptyMessage="Eligibility will appear when the catalog is loaded." /></ChartPanel></div>
      </div>
      <section className="panel data-source-inspector"><div className="panel-title"><h2>Source details</h2><ShieldCheck size={19} aria-hidden="true" /></div><div className="panel-body">{selected ? <><span className="data-source-icon large"><Database size={24} aria-hidden="true" /></span><h3>{selected.name}</h3><p className="muted">{selected.description}</p><dl className="data-facts"><div><dt>License</dt><dd>{selected.license || 'Not provided'}</dd></div><div><dt>Category</dt><dd>{selected.category}</dd></div><div><dt>Source kind</dt><dd>{selected.source_kind.replaceAll('_', ' ')}</dd></div><div><dt>Modalities</dt><dd>{selected.modalities?.join(', ') || 'Not provided'}</dd></div><div><dt>Eligibility</dt><dd>{selected.eligibility.replaceAll('_', ' ')}</dd></div><div><dt>Acquisition</dt><dd>{selected.acquisition_available ? 'Qualified' : 'Unavailable'}</dd></div><div><dt>Pinned revision</dt><dd><code>{selected.pinned_revision || 'Not qualified'}</code></dd></div><div><dt>Source size</dt><dd>{selected.is_size_measured && selected.size_bytes !== null ? `${selected.size_bytes.toLocaleString()} measured bytes` : 'Not measured'}</dd></div></dl>
        {!!selected.use_cases?.length && <div className="data-inspector-section"><h4>Use cases</h4><div className="data-tags">{selected.use_cases.map(useCase => <span className="badge" key={useCase}>{useCase.replaceAll('_', ' ')}</span>)}</div></div>}
        <div className="data-inspector-section"><h4>Provenance</h4><a href={selected.source_url} target="_blank" rel="noopener noreferrer" className="data-source-link">View original source <ExternalLink size={14} aria-hidden="true" /></a><p className="muted">Source sample lengths and token distributions are not reported by the catalog.</p></div>
        <div className="data-inspector-section"><h4>Preparation stages</h4><EventTimeline events={[{ label: 'Catalog metadata loaded', detail: 'License, modality, and policy status available.', status: 'ready' }, { label: acquisition?.revision_id ? 'Canonical revision published' : 'Acquire canonical samples', detail: acquisition?.revision_id ? `Revision ${acquisition.revision_no} · ${acquisition.row_count?.toLocaleString()} samples` : acquisition ? `${acquisition.verified_records}/${acquisition.planned_records} records verified · ${acquisition.job?.status || acquisition.state}` : 'A qualified source is downloaded and verified by a worker.', status: acquisition?.revision_id ? 'completed' : acquisition?.state || 'pending' }]} /></div>
        {status && <div className={`notice ${status.success ? 'success' : 'error'}`} role={status.success ? 'status' : 'alert'}>{status.message}</div>}
        {(selected.acquisition_available || acquisition) && <div className="data-inspector-section"><h4>Acquisition budget</h4>{budgetLoading ? <p className="muted" role="status">Checking enabled budget policies…</p> : budgetError ? <div><p className="notice error" role="alert">Budget policies could not be checked: {budgetError}</p><button disabled={importingId !== null} onClick={() => setBudgetRetry(value => value + 1)}>Retry budget policies</button></div> : budgetPolicies.length ? <><p className="muted">{budgetPolicies.some(policy => policy.unit === 'bank_acquisition_records') ? `Planned scope: ${selected.acquisition_record_limit ?? 'check source preflight'} records.` : 'No compatible policy is enabled. Ask an administrator to configure a bank_acquisition_records budget policy.'}</p><label>Enabled budget policy<select disabled={importingId !== null} value={budgetPolicyId} onChange={event => { setBudgetPolicyId(event.target.value); setEstimatedAmount(''); }}><option value="">Choose a budget policy</option>{budgetPolicies.filter(policy => policy.unit === 'bank_acquisition_records').map(policy => <option value={policy.policy_id} key={policy.policy_id}>{policy.name} · {policy.unit}{policy.currency ? ` · ${policy.currency}` : ''}</option>)}</select></label><label style={{ marginTop: 12 }}>Estimated reservation{selectedBudget ? ` (${selectedBudget.unit}${selectedBudget.currency ? ` · ${selectedBudget.currency}` : ''})` : ''}<input disabled={importingId !== null} type="number" min="0.000001" step="0.000001" inputMode="decimal" value={estimatedAmount} onChange={event => setEstimatedAmount(event.target.value)} aria-invalid={!!estimatedAmount && !validEstimate} placeholder="Positive amount to reserve" /></label><p className="muted">Use a bank_acquisition_records policy and reserve at least the planned record count. Resuming reserves only records still to transfer. The backend checks the remaining limit.</p></> : <p className="muted">No enabled tenant budget policies. This acquisition does not require a reservation.</p>}</div>}
        {acquisition ? <div className="data-acquisition"><dl className="data-facts"><div><dt>Transfer state</dt><dd>{acquisition.state.replaceAll('_', ' ')}</dd></div><div><dt>Job</dt><dd>{acquisition.job?.status || 'Not recorded'}</dd></div>{acquisition.job?.desired_action && <div><dt>Requested action</dt><dd>{acquisition.job.desired_action.replaceAll('_', ' ')}</dd></div>}<div><dt>Verified records</dt><dd>{acquisition.verified_records} / {acquisition.planned_records}</dd></div><div><dt>Verified bytes</dt><dd>{acquisition.transferred_bytes.toLocaleString()} / {acquisition.planned_bytes.toLocaleString()}</dd></div></dl><progress value={acquisition.verified_records} max={acquisition.planned_records || 1} aria-label="Verified acquisition records" /><div className="actions"><button disabled={importingId !== null} onClick={() => void updateAcquisition(selected)}>Refresh transfer</button>{!acquisition.revision_id && acquisition.state === 'ingesting' && <button disabled={importingId !== null || acquisition.job?.desired_action === 'cancel'} onClick={() => void updateAcquisition(selected, 'cancel')}>{acquisition.job?.desired_action === 'cancel' ? 'Cancellation requested' : 'Cancel transfer'}</button>}{['failed', 'cancelled'].includes(acquisition.state) && <button disabled={importingId !== null || !budgetReady} onClick={() => void updateAcquisition(selected, 'resume')}>Resume transfer</button>}</div>{!!acquisition.failures?.length && <details><summary>Recorded transfer failures</summary><pre>{JSON.stringify(acquisition.failures, null, 2)}</pre></details>}{acquisition.revision_id && <a href="#datasets" className="data-source-link">Inspect published dataset</a>}</div> : <button className="primary data-import-button" onClick={() => void handleImport(selected)} disabled={!token?.trim() || importingId !== null || !budgetReady || !selected.download_enabled || !selected.acquisition_available || selected.eligibility !== 'eligible'}><Download size={16} aria-hidden="true" />{importingId === selected.id ? 'Checking & queueing…' : 'Acquire to workspace'}</button>}
        {!selected.acquisition_available && <p className="muted">{selected.acquisition_blocked_reason || 'This source has no qualified acquisition connector.'}</p>}
      </> : <div className="empty-state"><Database size={28} aria-hidden="true" /><h3>Select a catalog source</h3><p>Inspect its license, provenance, and import eligibility.</p></div>}</div></section>
    </div>
  </div>;
}
