import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field, Notice, RecordTable } from '../components/ui';
import { Feedback } from '../components/Feedback';
import { useDraft, DraftStatus } from '../components/Draft';
import { resourceHash } from '../api/resource-routes';
import { runHash } from '../api/runs';
import { DataInspector } from '../components/DataInspector';
import React from 'react';
import { apiRequest, errorMessage, saveArtifact } from '../api/client';
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
  full_acquisition_available?: boolean;
  full_acquisition?: { pinned_revision: string; measured_selected_bytes: number; record_limit: number };
  size_bytes: number | null; is_size_measured: boolean;
}
interface BudgetPolicy { policy_id: string; name: string; unit: string; currency: string; enabled: boolean }
interface Acquisition {
  source_revision: string; snapshot_id: string; source_id: string; state: string; verified_records: number; planned_records: number;
  transferred_bytes: number; planned_bytes: number; row_count: number | null; revision_id: string | null;
  download_scope?: string; source_files?: { path: string; artifact_id: string; size: number; sha256: string }[]; manifest_artifact_id?: string;
  revision_no: number | null; manifest_digest: string; failures: unknown[]; job: { job_id?: string; status: string; desired_action: string } | null;
}

export function DatasetBankPage({ token, onImportSuccess, refreshKey = 0 }: DatasetBankPageProps) {
  const [error, setError] = React.useState<string | null>(null);
  const [sources, setSources] = React.useState<BankSource[]>([]);
  const [loading, setLoading] = React.useState(true);
  const draft = useDraft('dataset-bank', { query: '', selectedModality: 'all', catalogView: 'available', selectedId: '', budgetPolicyId: '', estimatedAmount: '', shareAlikeSourceId: '', downloadScope: 'sample', storageQuota: '', recordLimit: '' });
  const [recordLimit, setRecordLimit] = draft.field('recordLimit');
  const [history, setHistory] = React.useState<Acquisition[]>([]);
  const [historyError, setHistoryError] = React.useState('');
  const [review, setReview] = React.useState<{ source: BankSource; key: string; body: Record<string, unknown>; preview: unknown; preflight: unknown } | null>(null);
  const [query, setQuery] = draft.field('query');
  const [selectedModality, setSelectedModality] = draft.field('selectedModality');
  const [catalogView, setCatalogView] = draft.field('catalogView');
  const [selectedId, setSelectedId] = draft.field('selectedId');
  const sourceInspector = React.useRef<HTMLElement>(null);
  const [importingId, setImportingId] = React.useState<string | null>(null);
  const [importStatus, setImportStatus] = React.useState<Record<string, { success: boolean; message: string }>>({});
  const [acquisitions, setAcquisitions] = React.useState<Record<string, Acquisition>>({});
  const [budgetPolicies, setBudgetPolicies] = React.useState<BudgetPolicy[]>([]);
  const [budgetLoading, setBudgetLoading] = React.useState(true);
  const [budgetError, setBudgetError] = React.useState<string | null>(null);
  const [budgetRetry, setBudgetRetry] = React.useState(0);
  const [budgetPolicyId, setBudgetPolicyId] = draft.field('budgetPolicyId');
  const [estimatedAmount, setEstimatedAmount] = draft.field('estimatedAmount');
  const [shareAlikeSourceId, setShareAlikeSourceId] = draft.field('shareAlikeSourceId');
  const [downloadScope, setDownloadScope] = draft.field('downloadScope');
  const [storageQuota, setStorageQuota] = draft.field('storageQuota');
  const acquisitionKey = (source: BankSource) => source.id + (downloadScope === 'full' ? ':full' : '');
  const available = (source: BankSource) => downloadScope === 'full' ? source.full_acquisition_available : source.acquisition_available;
  const acquirable = (source: BankSource) => source.acquisition_available || !!source.full_acquisition_available;
  const qualifiedBytes = (source: BankSource) => downloadScope === 'full' ? source.full_acquisition?.measured_selected_bytes : source.size_bytes;
  const qualifiedCount = (source: BankSource) => acquisitions[acquisitionKey(source)]?.planned_records ?? (downloadScope === 'full' ? source.full_acquisition?.record_limit : recordLimit ? Number(recordLimit) : source.acquisition_record_limit);
  const storageBytes = (source: BankSource) => storageQuota ? Number(storageQuota) : 2 * (qualifiedBytes(source) || 0);
  const storageReady = (source: BankSource) => downloadScope !== 'full' || Number.isSafeInteger(storageBytes(source)) && storageBytes(source) >= 2 * (qualifiedBytes(source) || 0);
  const selectedBudget = budgetPolicies.find(policy => policy.policy_id === budgetPolicyId);
  const validEstimate = /^\d{1,18}(?:\.\d{1,6})?$/.test(estimatedAmount.trim()) && Number(estimatedAmount) > 0;
  const budgetReady = !budgetLoading && !budgetError && (!budgetPolicies.length || (selectedBudget?.unit === 'bank_acquisition_records' && validEstimate));
  const budgetBody = budgetPolicies.length ? { budget_policy_id: budgetPolicyId, estimated_amount: estimatedAmount.trim() } : {};
  const licenseReady = (source: BankSource) => source.eligibility === 'eligible' || (source.eligibility === 'opt_in_required' && shareAlikeSourceId === source.id);
  const scopeBody = (source: BankSource) => ({ ...(downloadScope === 'full' ? { download_scope: 'full' } : {}),
    ...(source.eligibility === 'opt_in_required' || downloadScope === 'full' ? { project_policy: {
      ...(source.eligibility === 'opt_in_required' ? { allow_share_alike: true } : {}),
      ...(downloadScope === 'full' ? { max_storage_quota_bytes: storageBytes(source) } : {}),
    } } : {}) });
  const acquisitionBody = (source: BankSource) => ({ ...budgetBody, ...scopeBody(source), source_revision: downloadScope === 'full' ? source.full_acquisition?.pinned_revision : source.pinned_revision, ...(recordLimit && downloadScope !== 'full' ? { record_limit: Number(recordLimit) } : {}) });
  const acquisitionRequest = React.useRef<AbortController | null>(null);
  const currentToken = React.useRef(token);
  currentToken.current = token;

  React.useEffect(() => {
    setAcquisitions({}); setImportStatus({}); setImportingId(null);
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

  React.useEffect(() => {
    const c = new AbortController(); setHistoryError('');
    allResources<Acquisition>('/api/v1/dataset-bank/acquisitions/', token || '', c.signal)
      .then(rows => { if (!c.signal.aborted) { setHistory(rows); const latest: Record<string, Acquisition> = {}; for (const row of rows) { const key = row.source_id + (row.download_scope === 'full' ? ':full' : ''); if (!latest[key]) latest[key] = row; } setAcquisitions(latest); } })
      .catch(e => { if (!c.signal.aborted) setHistoryError(errorMessage(e)); });
    return () => c.abort();
  }, [token, refreshKey]);

  async function reviewAcquisition(source: BankSource) {
    if (!token?.trim() || acquisitionRequest.current || !budgetReady || !available(source) || !storageReady(source) || !source.download_enabled || !licenseReady(source)) return;
    const c = new AbortController(); acquisitionRequest.current = c; setImportingId(source.id); setReview(null);
    const body = acquisitionBody(source);
    try {
      const [card, preview, preflight] = await Promise.all([
        apiRequest(`/api/v1/dataset-bank/sources/${source.id}/`, token, { signal: c.signal }),
        apiRequest(`/api/v1/dataset-bank/sources/${source.id}/preview/?limit=3`, token, { signal: c.signal }),
        apiRequest(`/api/v1/dataset-bank/sources/${source.id}/preflight/`, token, { method: 'POST', body: JSON.stringify(body), signal: c.signal }),
      ]);
      if (!c.signal.aborted) setReview({ source, key: acquisitionKey(source), body, preview: { card, samples: preview }, preflight });
    } catch (e) { if (!c.signal.aborted) setImportStatus(prior => ({ ...prior, [acquisitionKey(source)]: { success: false, message: errorMessage(e) } })); }
    finally { if (acquisitionRequest.current === c) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  async function handleImport(source: BankSource, body: Record<string, unknown> = acquisitionBody(source), key = acquisitionKey(source)) {
    if (!token?.trim() || acquisitionRequest.current || !budgetReady || !available(source) || !storageReady(source) || !source.download_enabled || !licenseReady(source)) return;
    const requestToken = token;
    const controller = new AbortController();
    acquisitionRequest.current = controller;
    const isCurrent = () => !controller.signal.aborted && acquisitionRequest.current === controller && currentToken.current === requestToken;
    setImportingId(source.id);
    try {
      await apiRequest(`/api/v1/dataset-bank/sources/${source.id}/preflight/`, token, { method: 'POST', body: JSON.stringify(body), signal: controller.signal });
      if (!isCurrent()) return;
      const data = await apiRequest<Acquisition>(`/api/v1/dataset-bank/sources/${source.id}/acquisitions/`, token, { method: 'POST', body: JSON.stringify(body), signal: controller.signal });
      if (!isCurrent()) return;
      setReview(null); setAcquisitions(previous => ({ ...previous, [key]: data }));
      setImportStatus(prev => ({ ...prev, [key]: { success: true, message: data.revision_id ? `Published revision ${data.revision_no} · ${data.row_count?.toLocaleString()} canonical samples` : downloadScope === 'full' ? 'Full download queued. A worker will verify every release file.' : 'Acquisition queued. A registered worker will download, verify, and publish the samples.' } }));
      if (data.revision_id) onImportSuccess?.();
    } catch (err) {
      if (isCurrent()) setImportStatus(prev => ({ ...prev, [key]: { success: false, message: errorMessage(err) } }));
    } finally { if (isCurrent()) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  async function updateAcquisition(source: BankSource, action?: 'cancel' | 'resume') {
    const acquisition = acquisitions[acquisitionKey(source)];
    if (!acquisition || !token?.trim() || acquisitionRequest.current || (action === 'resume' && !budgetReady)) return;
    const requestToken = token;
    const controller = new AbortController();
    acquisitionRequest.current = controller;
    const isCurrent = () => !controller.signal.aborted && acquisitionRequest.current === controller && currentToken.current === requestToken;
    setImportingId(source.id);
    try {
      const data = await apiRequest<Acquisition>(`/api/v1/dataset-bank/acquisitions/${acquisition.snapshot_id}/${action ? `${action}/` : ''}`, token, action ? { method: 'POST', body: JSON.stringify(action === 'resume' ? budgetBody : {}), signal: controller.signal } : { signal: controller.signal });
      if (!isCurrent()) return;
      setAcquisitions(previous => ({ ...previous, [acquisitionKey(source)]: data }));
      setImportStatus(previous => ({ ...previous, [acquisitionKey(source)]: { success: data.state !== 'failed', message: data.revision_id ? `Published revision ${data.revision_no} · ${data.row_count?.toLocaleString()} canonical samples` : `Acquisition ${data.state.replaceAll('_', ' ')} · ${data.verified_records}/${data.planned_records} ${data.download_scope === 'full' ? 'files' : 'records'} verified` } }));
      if (data.revision_id && !acquisition.revision_id) onImportSuccess?.();
    } catch (err) {
      if (isCurrent()) setImportStatus(previous => ({ ...previous, [acquisitionKey(source)]: { success: false, message: errorMessage(err) } }));
    } finally { if (isCurrent()) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  async function downloadFile(artifactId: string, name: string) {
    if (!token || acquisitionRequest.current) return;
    const controller = new AbortController();
    acquisitionRequest.current = controller;
    setImportingId(selected.id);
    try { await saveArtifact(artifactId, name, token, controller.signal); }
    catch (err) { if (!controller.signal.aborted) setImportStatus(previous => ({ ...previous, [acquisitionKey(selected)]: { success: false, message: errorMessage(err) } })); }
    finally { if (acquisitionRequest.current === controller) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  const modalities = [...new Set(sources.flatMap(source => source.modalities || []))].sort();
  const filtered = sources.filter(source => (catalogView === 'all' || (catalogView === 'unavailable' ? !acquirable(source) : acquirable(source)))
    && [source.name, source.description, source.license].some(value => value.toLowerCase().includes(query.toLowerCase()))
    && (selectedModality === 'all' || source.modalities?.includes(selectedModality)));
  const selected = filtered.find(source => source.id === selectedId) || filtered[0];
  const status = selected ? importStatus[acquisitionKey(selected)] : undefined;
  const acquisition = selected ? acquisitions[acquisitionKey(selected)] : undefined;

  return <div className="data-workspace dataset-bank-page">
    <ResourceState loading={loading} error={error} />
    <Card className="panel data-filter-panel"><div className="data-filter-row"><label className="data-search"><Search size={17} aria-hidden="true" /><Field type="search" aria-label="Search dataset sources" placeholder="Search sources, descriptions, or licenses…" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>Modality<select value={selectedModality} onChange={e => setSelectedModality(e.target.value)}><option value="all">All modalities</option>{modalities.map(modality => <option key={modality} value={modality}>{modality}</option>)}</select></label>
      <label>Availability<select aria-label="Catalog availability" value={catalogView} onChange={e => setCatalogView(e.target.value)}><option value="available">Ready to acquire</option><option value="unavailable">Not available yet</option><option value="all">All sources</option></select></label>
      <Button onClick={() => { setQuery(''); setSelectedModality('all'); setCatalogView('available'); }} disabled={!query && selectedModality === 'all' && catalogView === 'available'}>Clear filters</Button></div></Card>
    <div className="data-inspector-layout">
      <div className="data-catalog-column"><Card className="panel"><div className="panel-title"><div><h2>Source catalog</h2><p>Curated open data for training and evaluation.</p></div><Badge className="badge">{filtered.length} / {sources.length} SOURCES</Badge></div>
        <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table data-source-table"><thead><tr><th>Source</th><th>Modality</th><th>License</th><th>Eligibility</th><th>Inspect</th></tr></thead><tbody>{filtered.map(source => <tr key={source.id} className={selected?.id === source.id ? 'data-selected-row' : ''}>
          <td><div className="data-source-name"><span className="data-source-icon"><Database size={18} aria-hidden="true" /></span><div><strong>{source.name}</strong><small>{source.description}</small></div></div></td>
          <td><div className="data-tags">{source.modalities?.map(modality => <Badge className="badge" key={modality}>{modality}</Badge>)}</div></td><td>{source.license || 'Not provided'}</td>
          <td><Badge className={`state state-${source.eligibility === 'eligible' ? 'ready' : 'pending'}`}>{source.eligibility.replaceAll('_', ' ')}</Badge></td>
          <td><Button aria-pressed={selected?.id === source.id} aria-label={`Inspect ${source.name}`} disabled={importingId !== null} onClick={() => { setSelectedId(source.id); setReview(null); requestAnimationFrame(() => sourceInspector.current?.focus()); }}>Inspect</Button></td></tr>)}
          {!loading && !filtered.length && <tr><td colSpan={5}><Feedback state="empty" title={error ? 'Catalog unavailable' : 'No matching sources'} description={error ? 'Check your connection and refresh the catalog.' : catalogView === 'available' ? 'No sources in this installation can be acquired yet. Open Not available yet to see the reason for each remaining source.' : 'Try another search or clear your filters.'} /></td></tr>}</tbody></RecordTable></div></Card>
        <details className="workspace-details"><summary>Catalog statistics</summary><div className="visualization-grid equal"><ChartPanel title="Catalog composition" description="Source counts in the loaded catalog. A source can have multiple modalities."><BarChart data={modalities.map(modality => ({ label: modality, value: sources.filter(source => source.modalities?.includes(modality)).length }))} unit="Sources" emptyMessage="Connect to load the curated catalog." /></ChartPanel>
          <ChartPanel title="Import eligibility" description="Catalog policy status; sample counts are available after import."><BarChart data={[...new Set(sources.map(source => source.eligibility))].map(eligibility => ({ label: eligibility.replaceAll('_', ' '), value: sources.filter(source => source.eligibility === eligibility).length }))} unit="Sources" emptyMessage="Eligibility will appear when the catalog is loaded." /></ChartPanel></div></details>
      </div>
      <Card ref={sourceInspector} tabIndex={-1} aria-label="Source details" className="panel data-source-inspector"><div className="panel-title"><h2>Source details</h2><ShieldCheck size={19} aria-hidden="true" /></div><div className="panel-body">{selected ? <><span className="data-source-icon large"><Database size={24} aria-hidden="true" /></span><h3>{selected.name}</h3><p className="muted">{selected.description}</p><dl className="data-facts"><div><dt>License</dt><dd>{selected.license || 'Not provided'}</dd></div><div><dt>Category</dt><dd>{selected.category}</dd></div><div><dt>Source kind</dt><dd>{selected.source_kind.replaceAll('_', ' ')}</dd></div><div><dt>Modalities</dt><dd>{selected.modalities?.join(', ') || 'Not provided'}</dd></div><div><dt>Eligibility</dt><dd>{selected.eligibility.replaceAll('_', ' ')}</dd></div><div><dt>Acquisition</dt><dd>{available(selected) ? 'Qualified' : 'Unavailable'}</dd></div><div><dt>Qualified scope</dt><dd>{qualifiedCount(selected) ? `${qualifiedCount(selected)} ${downloadScope === 'full' ? 'source files' : 'records'}` : 'Not qualified'}</dd></div><div><dt>Pinned revision</dt><dd>{(downloadScope === 'full' ? selected.full_acquisition?.pinned_revision : selected.pinned_revision) ? <Identifier value={downloadScope === 'full' ? selected.full_acquisition?.pinned_revision : selected.pinned_revision} label="Pinned repository revision" /> : 'Not qualified'}</dd></div><div><dt>Qualified transfer size</dt><dd>{qualifiedBytes(selected) != null ? `${qualifiedBytes(selected)?.toLocaleString()} measured bytes` : 'Not measured'}</dd></div></dl>
        {!!selected.use_cases?.length && <div className="data-inspector-section"><h4>Use cases</h4><div className="data-tags">{selected.use_cases.map(useCase => <Badge className="badge" key={useCase}>{useCase.replaceAll('_', ' ')}</Badge>)}</div></div>}
        <label>Download scope<select value={downloadScope} disabled={importingId !== null} onChange={event => { setDownloadScope(event.target.value); setStorageQuota(''); }}><option value="sample">Qualified samples</option><option value="full" disabled={!selected.full_acquisition_available}>Complete source release</option></select></label>
        {downloadScope === 'full' && <><p className="muted">Download every original release file and split. These files can be saved after verification; training preparation is separate.</p><label>Storage allowance (bytes)<Field type="number" min={2 * (qualifiedBytes(selected) || 0)} step="1" value={storageQuota || String(2 * (qualifiedBytes(selected) || 0))} disabled={importingId !== null} onChange={event => setStorageQuota(event.target.value)} aria-invalid={!storageReady(selected)} /></label><p className="muted">Allow at least {(2 * (qualifiedBytes(selected) || 0)).toLocaleString()} bytes for the completed files and retained resumable parts.</p></>}<div className="data-inspector-section"><h4>Provenance</h4><a href={selected.source_url} target="_blank" rel="noopener noreferrer" className="data-source-link">View original source <ExternalLink size={14} aria-hidden="true" /></a><p className="muted">Source sample lengths and token distributions are not reported by the catalog.</p></div>
        <div className="data-inspector-section"><h4>Preparation stages</h4><EventTimeline events={[{ label: 'Catalog metadata loaded', detail: 'License, modality, and policy status available.', status: 'ready' }, { label: downloadScope === 'full' ? (acquisition?.state === 'ready' ? 'Complete release verified' : 'Download complete release') : acquisition?.revision_id ? 'Canonical revision published' : 'Acquire canonical samples', detail: acquisition?.revision_id ? `Revision ${acquisition.revision_no} · ${acquisition.row_count?.toLocaleString()} samples` : acquisition ? `${acquisition.verified_records}/${acquisition.planned_records} ${downloadScope === 'full' ? 'files' : 'records'} verified · ${acquisition.job?.status || acquisition.state}` : 'A qualified source is downloaded and verified by a worker.', status: acquisition?.revision_id || acquisition?.state === 'ready' ? 'completed' : acquisition?.state || 'pending' }]} /></div>
        {status && <div className={`notice ${status.success ? 'success' : 'error'}`} role={status.success ? 'status' : 'alert'}>{status.message}</div>}
        <DraftStatus draft={draft} disabled={importingId !== null} />
        {historyError && <p role="alert">Acquisition history could not be loaded: {historyError}</p>}
        {history.filter(item => item.source_id === selected.id && (item.download_scope || 'sample') === downloadScope).length > 0 && <label>Saved acquisition<select value={acquisition?.snapshot_id || ''} disabled={importingId !== null} onChange={e => { const saved = history.find(item => item.snapshot_id === e.target.value); if (saved) setAcquisitions(previous => ({ ...previous, [acquisitionKey(selected)]: saved })); }}>{history.filter(item => item.source_id === selected.id && (item.download_scope || 'sample') === downloadScope).map(item => <option key={item.snapshot_id} value={item.snapshot_id}>{item.source_revision} · {item.state} · {item.verified_records}/{item.planned_records}</option>)}</select></label>}
        {acquisition?.job?.job_id && <a href={runHash('job', acquisition.job.job_id)}>Inspect acquisition job and attempts</a>}
        {!acquisition && downloadScope === 'sample' && <label>Records to acquire<Field type="number" min="1" max={selected.acquisition_record_limit} value={recordLimit} disabled={importingId !== null} placeholder={String(selected.acquisition_record_limit || '')} onChange={e => setRecordLimit(e.target.value)} /></label>}
        {review?.source.id === selected.id && <section className="detail-box" aria-label="Acquisition review"><h4>Confirm acquisition scope</h4><p>The request below freezes source revision, destination policy, subset and budget. Preview contains real upstream samples; full releases additionally use the full-scope file preflight.</p><DataInspector value={review.preview} /><DataInspector value={review.preflight} /><DataInspector value={review.body} /><div className="actions"><Button className="primary" disabled={importingId !== null} onClick={() => void handleImport(review.source, review.body, review.key)}>Confirm and acquire</Button><Button disabled={importingId !== null} onClick={() => setReview(null)}>Close acquisition review</Button></div></section>}
        {(available(selected) || acquisition) && <div className="data-inspector-section"><h4>Acquisition budget</h4>{budgetLoading ? <p className="muted" role="status">Checking enabled budget policies…</p> : budgetError ? <div><Notice as="p" tone="error" className="notice error" role="alert">Budget policies could not be checked: {budgetError}</Notice><Button disabled={importingId !== null} onClick={() => setBudgetRetry(value => value + 1)}>Retry budget policies</Button></div> : budgetPolicies.length ? <><p className="muted">{budgetPolicies.some(policy => policy.unit === 'bank_acquisition_records') ? `Planned scope: ${qualifiedCount(selected) ?? 'check source preflight'} ${downloadScope === 'full' ? 'source files' : 'records'}.` : 'No compatible policy is enabled. Ask an administrator to configure a bank_acquisition_records budget policy.'}</p><label>Enabled budget policy<select disabled={importingId !== null} value={budgetPolicyId} onChange={event => { setBudgetPolicyId(event.target.value); setEstimatedAmount(''); }}><option value="">Choose a budget policy</option>{budgetPolicies.filter(policy => policy.unit === 'bank_acquisition_records').map(policy => <option value={policy.policy_id} key={policy.policy_id}>{policy.name} · {policy.unit}{policy.currency ? ` · ${policy.currency}` : ''}</option>)}</select></label><label style={{ marginTop: 12 }}>Estimated reservation{selectedBudget ? ` (${selectedBudget.unit}${selectedBudget.currency ? ` · ${selectedBudget.currency}` : ''})` : ''}<Field disabled={importingId !== null} type="number" min="0.000001" step="0.000001" inputMode="decimal" value={estimatedAmount} onChange={event => setEstimatedAmount(event.target.value)} aria-invalid={!!estimatedAmount && !validEstimate} placeholder="Positive amount to reserve" /></label><p className="muted">Use a bank_acquisition_records policy and reserve at least the planned record count. Full releases count source files. Resuming reserves only items still to transfer. The backend checks the remaining limit.</p></> : <p className="muted">No enabled tenant budget policies. This acquisition does not require a reservation.</p>}</div>}
        {!acquisition && selected.eligibility === 'opt_in_required' && available(selected) && <label className="data-license-consent"><input type="checkbox" checked={shareAlikeSourceId === selected.id} disabled={importingId !== null} onChange={event => setShareAlikeSourceId(event.target.checked ? selected.id : '')} /><span>I allow this source’s share-alike license obligations for this acquisition.</span></label>}
        {acquisition ? <div className="data-acquisition"><dl className="data-facts"><div><dt>Transfer state</dt><dd>{acquisition.state.replaceAll('_', ' ')}</dd></div><div><dt>Job</dt><dd>{acquisition.job?.status || 'Not recorded'}</dd></div>{acquisition.job?.desired_action && <div><dt>Requested action</dt><dd>{acquisition.job.desired_action.replaceAll('_', ' ')}</dd></div>}<div><dt>{downloadScope === 'full' ? 'Verified files' : 'Verified records'}</dt><dd>{acquisition.verified_records} / {acquisition.planned_records}</dd></div><div><dt>Verified bytes</dt><dd>{acquisition.transferred_bytes.toLocaleString()} / {acquisition.planned_bytes.toLocaleString()}</dd></div></dl><progress value={acquisition.transferred_bytes} max={acquisition.planned_bytes || 1} aria-label="Verified acquisition bytes" /><div className="actions"><Button disabled={importingId !== null} onClick={() => void updateAcquisition(selected)}>Refresh transfer</Button>{!acquisition.revision_id && acquisition.state === 'ingesting' && <Button disabled={importingId !== null || acquisition.job?.desired_action === 'cancel'} onClick={() => void updateAcquisition(selected, 'cancel')}>{acquisition.job?.desired_action === 'cancel' ? 'Cancellation requested' : 'Cancel transfer'}</Button>}{['failed', 'cancelled'].includes(acquisition.state) && <Button disabled={importingId !== null || !budgetReady} onClick={() => void updateAcquisition(selected, 'resume')}>Resume transfer</Button>}</div>{!!acquisition.failures?.length && <details><summary>Recorded transfer failures</summary><DataInspector value={acquisition.failures} /></details>}{acquisition.state === 'ready' && acquisition.download_scope === 'full' && <div className="data-inspector-section"><h4>Verified release files</h4>{acquisition.source_files?.map(file => <p key={file.path}><Button disabled={importingId !== null} onClick={() => void downloadFile(file.artifact_id, file.path.split('/').at(-1) || 'dataset')}>Save {file.path}</Button> · {file.size.toLocaleString()} bytes</p>)}{acquisition.manifest_artifact_id && <Button disabled={importingId !== null} onClick={() => void downloadFile(acquisition.manifest_artifact_id!, 'full-release.json')}>Save verification manifest</Button>}</div>}{acquisition.revision_id && <a href={resourceHash('dataset-revision', acquisition.revision_id)} className="data-source-link">Inspect published dataset</a>}</div> : <Button className="primary data-import-button" onClick={() => void reviewAcquisition(selected)} disabled={!token?.trim() || importingId !== null || !budgetReady || !selected.download_enabled || !available(selected) || !storageReady(selected) || !licenseReady(selected)}><Download size={16} aria-hidden="true" />{importingId === selected.id ? 'Checking & queueing…' : 'Review acquisition'}</Button>}
        {!available(selected) && <p className="muted">{selected.acquisition_blocked_reason || 'This source has no qualified acquisition connector.'}</p>}
      </> : <div className="empty-state"><Database size={28} aria-hidden="true" /><h3>Select a catalog source</h3><p>Inspect its license, provenance, and import eligibility.</p></div>}</div></Card>
    </div>
  </div>;
}
