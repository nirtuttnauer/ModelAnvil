import { Identifier } from '../components/Identifier';
import { Badge, Button, Checkbox, Dialog, Disclosure, Field, KeyValueList, LinkButton, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { InspectorPanel } from '../components/InspectorPanel';
import { useDraft, DraftIndicator } from '../components/Draft';
import { resourceHash } from '../api/resource-routes';
import { runHash } from '../api/runs';
import { DataInspector } from '../components/DataInspector';
import React from 'react';
import { apiRequest, errorMessage, saveArtifact } from '../api/client';
import { allResources } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import './ml-pages.css';

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

// Only useState, useRef and useEffect are used here: tests/dataset-bank.test.mjs renders this page with a React stub.
const words = (value: string) => { const text = value.replaceAll('_', ' '); return text ? text[0].toUpperCase() + text.slice(1) : text; };

export function DatasetBankPage({ token, onImportSuccess, refreshKey = 0 }: DatasetBankPageProps) {
  const [error, setError] = React.useState<string | null>(null);
  const [sources, setSources] = React.useState<BankSource[]>([]);
  const [loading, setLoading] = React.useState(true);
  const draft = useDraft('dataset-bank', { query: '', selectedModality: 'all', selectedId: '', budgetPolicyId: '', estimatedAmount: '', shareAlikeSourceId: '', downloadScope: 'sample', storageQuota: '', recordLimit: '' });
  const [recordLimit, setRecordLimit] = draft.field('recordLimit');
  const [history, setHistory] = React.useState<Acquisition[]>([]);
  const [historyError, setHistoryError] = React.useState('');
  const [review, setReview] = React.useState<{ source: BankSource; key: string; body: Record<string, unknown>; preview: unknown; preflight: unknown } | null>(null);
  const [query, setQuery] = draft.field('query');
  const [selectedModality, setSelectedModality] = draft.field('selectedModality');
  const [selectedId, setSelectedId] = draft.field('selectedId');
  const focusInspector = React.useRef(false);
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
  React.useEffect(() => { focusInspector.current = false; });

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
      setImportStatus(previous => ({ ...previous, [acquisitionKey(source)]: { success: data.state !== 'failed', message: data.revision_id ? `Published revision ${data.revision_no} · ${data.row_count?.toLocaleString()} canonical samples` : `Acquisition ${words(data.state)} · ${data.verified_records}/${data.planned_records} ${data.download_scope === 'full' ? 'files' : 'records'} verified` } }));
      if (data.revision_id && !acquisition.revision_id) onImportSuccess?.();
    } catch (err) {
      if (isCurrent()) setImportStatus(previous => ({ ...previous, [acquisitionKey(source)]: { success: false, message: errorMessage(err) } }));
    } finally { if (isCurrent()) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  async function downloadFile(source: BankSource, artifactId: string, name: string) {
    if (!token || acquisitionRequest.current) return;
    const controller = new AbortController();
    acquisitionRequest.current = controller;
    setImportingId(source.id);
    try { await saveArtifact(artifactId, name, token, controller.signal); }
    catch (err) { if (!controller.signal.aborted) setImportStatus(previous => ({ ...previous, [acquisitionKey(source)]: { success: false, message: errorMessage(err) } })); }
    finally { if (acquisitionRequest.current === controller) { acquisitionRequest.current = null; setImportingId(null); } }
  }

  const modalities = [...new Set(sources.flatMap(source => source.modalities || []))].sort();
  const filtered = sources.filter(source => [source.name, source.description, source.license].some(value => value.toLowerCase().includes(query.toLowerCase()))
    && (selectedModality === 'all' || source.modalities?.includes(selectedModality)));
  const selected = filtered.find(source => source.id === selectedId);
  const status = selected ? importStatus[acquisitionKey(selected)] : undefined;
  const acquisition = selected ? acquisitions[acquisitionKey(selected)] : undefined;
  const busy = importingId !== null;
  const sourceHistory = selected ? history.filter(item => item.source_id === selected.id && (item.download_scope || 'sample') === downloadScope) : [];
  const pinnedRevision = selected ? (downloadScope === 'full' ? selected.full_acquisition?.pinned_revision : selected.pinned_revision) : undefined;
  const unitLabel = downloadScope === 'full' ? 'source files' : 'records';

  return <div className="ml-page">
    <Section title="Source catalog" description="Curated open data for training and evaluation." actions={<>
      <Field className="ml-search" aria-label="Search dataset sources" placeholder="Search sources" value={query} onChange={e => setQuery(e.target.value)} />
      <Select aria-label="Modality" value={selectedModality} onChange={e => setSelectedModality(e.target.value)}><option value="all">All modalities</option>{modalities.map(modality => <option key={modality} value={modality}>{modality}</option>)}</Select>
      <Button type="button" variant="quiet" onClick={() => { setQuery(''); setSelectedModality('all'); }} disabled={!query && selectedModality === 'all'}>Clear filters</Button>
    </>}>
      <ResourceState loading={loading} error={error} />
      <div data-ui="split" data-open={selected ? '' : undefined}>
        <div className="ml-list">
          {!loading && !error && <p className="ml-footnote">{filtered.length} of {sources.length} sources</p>}
          {!loading && !error && !filtered.length && <EmptyState title="No matching sources" description="Try another search or clear your filters." />}
          {filtered.length > 0 && <div className="table-scroll" tabIndex={0}><RecordTable>
            <thead><tr><th>Source</th><th>Modality</th><th>License</th><th>Eligibility</th><th>Details</th></tr></thead>
            <tbody>{filtered.map(source => <tr key={source.id} aria-selected={selected?.id === source.id || undefined}>
              <td><strong>{source.name}</strong><small>{source.description}</small></td>
              <td><div data-ui="actions">{source.modalities?.map(modality => <Badge key={modality}>{modality}</Badge>)}</div></td>
              <td>{source.license || 'Not provided'}</td>
              <td><StatusBadge status={source.eligibility} label={words(source.eligibility)} /></td>
              <td><Button type="button" size="sm" aria-pressed={selected?.id === source.id} aria-label={`Inspect ${source.name}`} disabled={busy} onClick={() => { focusInspector.current = true; setSelectedId(source.id); setReview(null); }}>Inspect</Button></td>
            </tr>)}</tbody>
          </RecordTable></div>}
        </div>
        {selected && <InspectorPanel key={selected.id} eyebrow="Source" title={selected.name} closeLabel="Close source details" onClose={() => { setSelectedId(''); setReview(null); }} focusOnOpen={focusInspector.current}>
          <p className="muted">{selected.description}</p>
          <KeyValueList items={[
            { label: 'License', value: selected.license || 'Not provided' },
            { label: 'Category', value: `${selected.category} · ${words(selected.source_kind)}` },
            { label: 'Modalities', value: selected.modalities?.join(', ') || 'Not provided' },
            { label: 'Eligibility', value: <StatusBadge status={selected.eligibility} label={words(selected.eligibility)} /> },
            { label: 'Acquisition', value: available(selected) ? `Qualified · ${qualifiedCount(selected) ? `${qualifiedCount(selected)} ${unitLabel}` : 'scope not qualified'}` : 'Unavailable' },
            { label: 'Pinned revision', value: pinnedRevision ? <Identifier value={pinnedRevision} label="Pinned repository revision" display="code" /> : 'Not qualified' },
            { label: 'Transfer size', value: qualifiedBytes(selected) != null ? `${qualifiedBytes(selected)?.toLocaleString()} measured bytes` : 'Not measured' },
          ]} />
          {!!selected.use_cases?.length && <div data-ui="actions">{selected.use_cases.map(useCase => <Badge key={useCase}>{words(useCase)}</Badge>)}</div>}
          <Select label="Download scope" value={downloadScope} disabled={busy} onChange={event => { setDownloadScope(event.target.value); setStorageQuota(''); }}><option value="sample">Qualified samples</option><option value="full" disabled={!selected.full_acquisition_available}>Complete source release</option></Select>
          {downloadScope === 'full' && <TextControl label="Storage allowance (bytes)" hint={`Allow at least ${(2 * (qualifiedBytes(selected) || 0)).toLocaleString()} bytes for the completed files and retained resumable parts.`} type="number" min={2 * (qualifiedBytes(selected) || 0)} step="1" value={storageQuota || String(2 * (qualifiedBytes(selected) || 0))} disabled={busy} onChange={event => setStorageQuota(event.target.value)} aria-invalid={!storageReady(selected)} />}
          {!acquisition && downloadScope === 'sample' && <TextControl label="Records to acquire" type="number" min="1" max={selected.acquisition_record_limit} value={recordLimit} disabled={busy} placeholder={String(selected.acquisition_record_limit || '')} onChange={e => setRecordLimit(e.target.value)} />}
          {status && <Notice tone={status.success ? 'success' : 'error'} role={status.success ? 'status' : 'alert'}>{status.message}</Notice>}
          {historyError && <p role="alert" className="error-text">Acquisition history could not be loaded: {historyError}</p>}
          {acquisition ? <div data-ui="form">
            <KeyValueList items={[
              { label: 'Transfer state', value: <StatusBadge status={acquisition.state} label={words(acquisition.state)} /> },
              { label: 'Job', value: acquisition.job?.status ? words(acquisition.job.status) : 'Not recorded' },
              ...(acquisition.job?.desired_action ? [{ label: 'Requested action', value: words(acquisition.job.desired_action) }] : []),
              { label: downloadScope === 'full' ? 'Verified files' : 'Verified records', value: `${acquisition.verified_records} / ${acquisition.planned_records}` },
              { label: 'Verified bytes', value: `${acquisition.transferred_bytes.toLocaleString()} / ${acquisition.planned_bytes.toLocaleString()}` },
            ]} />
            <progress value={acquisition.transferred_bytes} max={acquisition.planned_bytes || 1} aria-label="Verified acquisition bytes" />
            <div data-ui="actions">
              <Button type="button" size="sm" disabled={busy} onClick={() => void updateAcquisition(selected)}>Refresh transfer</Button>
              {!acquisition.revision_id && acquisition.state === 'ingesting' && <Button type="button" size="sm" disabled={busy || acquisition.job?.desired_action === 'cancel'} onClick={() => void updateAcquisition(selected, 'cancel')}>{acquisition.job?.desired_action === 'cancel' ? 'Cancellation requested' : 'Cancel transfer'}</Button>}
              {['failed', 'cancelled'].includes(acquisition.state) && <Button type="button" size="sm" disabled={busy || !budgetReady} onClick={() => void updateAcquisition(selected, 'resume')}>Resume transfer</Button>}
              {acquisition.job?.job_id && <LinkButton size="sm" href={runHash('job', acquisition.job.job_id)}>Open acquisition job</LinkButton>}
              {acquisition.revision_id && <LinkButton size="sm" variant="primary" href={resourceHash('dataset-revision', acquisition.revision_id)}>Open dataset version</LinkButton>}
            </div>
            {!!acquisition.failures?.length && <Disclosure summary="Recorded transfer failures" variant="quiet"><DataInspector value={acquisition.failures} /></Disclosure>}
            {acquisition.state === 'ready' && acquisition.download_scope === 'full' && <Disclosure summary="Verified release files" variant="quiet"><div data-ui="actions">{acquisition.source_files?.map(file => <Button key={file.path} type="button" size="sm" disabled={busy} onClick={() => void downloadFile(selected, file.artifact_id, file.path.split('/').at(-1) || 'dataset')}>Save {file.path} · {file.size.toLocaleString()} bytes</Button>)}{acquisition.manifest_artifact_id && <Button type="button" size="sm" disabled={busy} onClick={() => void downloadFile(selected, acquisition.manifest_artifact_id!, 'full-release.json')}>Save verification manifest</Button>}</div></Disclosure>}
          </div> : <div data-ui="actions"><Button type="button" variant="primary" onClick={() => void reviewAcquisition(selected)} disabled={!token?.trim() || busy || !budgetReady || !selected.download_enabled || !available(selected) || !storageReady(selected) || !licenseReady(selected)}>{importingId === selected.id ? 'Checking…' : 'Review acquisition'}</Button></div>}
          {!available(selected) && <p className="muted">{selected.acquisition_blocked_reason || 'This source has no qualified acquisition connector.'}</p>}
          {review?.source.id === selected.id && <Dialog title="Confirm acquisition" description="The request freezes source revision, destination policy, subset and budget." open onClose={() => setReview(null)} size="lg">
            <Disclosure summary="Preview samples" variant="quiet" open><DataInspector value={review.preview} /></Disclosure>
            <Disclosure summary="Preflight" variant="quiet"><DataInspector value={review.preflight} /></Disclosure>
            <Disclosure summary="Request" variant="quiet"><DataInspector value={review.body} /></Disclosure>
            <div data-ui="actions"><Button type="button" variant="primary" disabled={busy} onClick={() => void handleImport(review.source, review.body, review.key)}>Confirm and acquire</Button><Button type="button" disabled={busy} onClick={() => setReview(null)}>Close acquisition review</Button></div>
          </Dialog>}
          {(available(selected) || acquisition) && <Disclosure summary="Budget and consent" variant="quiet" open>
            <div data-ui="form">
              {budgetLoading ? <p className="muted" role="status">Checking enabled budget policies…</p> : budgetError ? <Notice tone="error" role="alert">Budget policies could not be checked: {budgetError} <Button type="button" size="sm" disabled={busy} onClick={() => setBudgetRetry(value => value + 1)}>Retry budget policies</Button></Notice> : budgetPolicies.length ? <>
                <Select label="Enabled budget policy" hint={budgetPolicies.some(policy => policy.unit === 'bank_acquisition_records') ? `Planned scope: ${qualifiedCount(selected) ?? 'check source preflight'} ${unitLabel}.` : 'No compatible policy is enabled. Ask an administrator to configure a bank_acquisition_records budget policy.'} disabled={busy} value={budgetPolicyId} onChange={event => { setBudgetPolicyId(event.target.value); setEstimatedAmount(''); }}><option value="">Choose a budget policy</option>{budgetPolicies.filter(policy => policy.unit === 'bank_acquisition_records').map(policy => <option value={policy.policy_id} key={policy.policy_id}>{policy.name}{policy.currency ? ` · ${policy.currency}` : ''}</option>)}</Select>
                <TextControl label={`Estimated reservation (${selectedBudget?.unit === 'bank_acquisition_records' ? 'records' : selectedBudget?.unit || 'records'}${selectedBudget?.currency ? ` · ${selectedBudget.currency}` : ''})`} hint="Reserve at least the planned record count. Resuming reserves only items still to transfer." disabled={busy} type="number" min="0.000001" step="0.000001" inputMode="decimal" value={estimatedAmount} onChange={event => setEstimatedAmount(event.target.value)} aria-invalid={!!estimatedAmount && !validEstimate} placeholder="Positive amount to reserve" />
              </> : <p className="muted">No enabled budget policies. This acquisition does not require a reservation.</p>}
              {!acquisition && selected.eligibility === 'opt_in_required' && available(selected) && <Checkbox label="I allow this source’s share-alike license obligations for this acquisition." checked={shareAlikeSourceId === selected.id} disabled={busy} onChange={event => setShareAlikeSourceId(event.target.checked ? selected.id : '')} />}
            </div>
          </Disclosure>}
          {sourceHistory.length > 0 && <Disclosure summary="Acquisition history" variant="quiet">
            <Select label="Saved acquisition" value={acquisition?.snapshot_id || ''} disabled={busy} onChange={e => { const saved = history.find(item => item.snapshot_id === e.target.value); if (saved) setAcquisitions(previous => ({ ...previous, [acquisitionKey(selected)]: saved })); }}>{sourceHistory.map(item => <option key={item.snapshot_id} value={item.snapshot_id}>{item.source_revision} · {words(item.state)} · {item.verified_records}/{item.planned_records}</option>)}</Select>
          </Disclosure>}
          <DraftIndicator draft={draft} disabled={busy} />
          <p className="ml-footnote"><a href={selected.source_url} target="_blank" rel="noopener noreferrer">View original source</a></p>
        </InspectorPanel>}
      </div>
    </Section>
  </div>;
}
