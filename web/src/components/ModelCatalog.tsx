import { Identifier } from './Identifier';
import { Button, Card, Field, RecordTable } from './ui';
import { useDraft, DraftStatus } from './Draft';
import { savedModelFiles, validateModelFiles } from '../api/model-files';
import { resourceHash } from '../api/resource-routes';
import { runHash } from '../api/runs';
import { allResources } from '../api/resources';
import { ModelHardwareFit } from './ModelHardwareFit';
import { useHardwareInventory } from './useHardwareInventory';
import { workerHardware, type ModelMemory } from '../api/model-hardware';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage, getActiveProjectId } from '../api/client';
import '../pages/model-workspace.css';

interface HubModel { repo_id: string; revision: string; task: string; license: string; gated: boolean; architecture: string }
interface Plan extends HubModel { format: string; byte_size: number; parameters_count: number | null; files: Record<string, unknown>; training_supported: boolean; memory_requirements?: ModelMemory }
interface Import { job_id?: string | null; import_id: string; name: string; status: string; job_status: string | null; candidate_id: string | null; files: Record<string, unknown>; acquired_files: Record<string, unknown> }
interface FileRef { artifact_id: string; sha256: string; byte_size: number }

export function ModelCatalog({ token, onImported }: { token: string; onImported: () => void }) {
  const hardware = useHardwareInventory(token);
  const workers = hardware.workers.filter(worker => worker.connection_state === 'connected' && worker.capabilities.model_import && ['available', 'busy'].includes(worker.status));
  const draft = useDraft('model-import', { mode: 'local' as 'hub' | 'local', query: 'SmolLM2', repo: '', revision: '', format: 'safetensors', filename: '', name: '', license: '', pool: '', importKey: '', uploadedJSON: '{}' });
  const actionRequest = useRef<AbortController | null>(null);
  const [uploadedJSON, setUploadedJSON] = draft.field('uploadedJSON');
  const uploaded = savedModelFiles(uploadedJSON);
  const setUploaded = (refs: Record<string, FileRef>) => setUploadedJSON(JSON.stringify(refs));
  const [mode, setMode] = draft.field('mode');
  const [query, setQuery] = draft.field('query');
  const [results, setResults] = useState<HubModel[]>([]);
  const [repo, setRepo] = draft.field('repo');
  const [revision, setRevision] = draft.field('revision');
  const [format, setFormat] = draft.field('format');
  const [filename, setFilename] = draft.field('filename');
  const [name, setName] = draft.field('name');
  const [plan, setPlan] = useState<Plan | null>(null);
  const [license, setLicense] = draft.field('license');
  const [accepted, setAccepted] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const localSizes = new Map([...Object.entries(uploaded).map(([name, ref]) => [name, ref.byte_size] as const), ...files.map(file => [file.name, file.size] as const)]);
  const localWeightBytes = [...localSizes].filter(([name]) => name.endsWith('.safetensors') || name.endsWith('.gguf')).reduce((sum, [, size]) => sum + size, 0);
  const [pool, setPool] = draft.field('pool');
  const [imports, setImports] = useState<Import[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [importKey, setImportKey] = draft.field('importKey');
  const reload = useCallback(async (signal?: AbortSignal) => {
    const rows = await allResources<Import>('/api/v1/model-imports/', token, signal).then(results => ({ results }));
    if (!signal?.aborted) setImports(rows.results);
  }, [token]);
  useEffect(() => {
    if (!token.trim()) return;
    const controller = new AbortController();
    void reload(controller.signal).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => { controller.abort(); actionRequest.current?.abort(); };
  }, [token, reload]);
  useEffect(() => {
    if (!imports.some(i => i.job_status === 'queued' || i.job_status === 'running')) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => { void reload(controller.signal).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); }); }, 3000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [imports, reload]);
  function changed() { setPlan(null); setAccepted(false); setImportKey(''); setNotice(''); }
  async function search(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { setResults((await apiRequest<{ results: HubModel[] }>(`/api/v1/model-imports/search/?q=${encodeURIComponent(query)}`, token)).results); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function inspect() {
    setBusy(true); setError(''); setAccepted(false);
    try {
      const result = await apiRequest<Plan>('/api/v1/model-imports/inspect/', token, { method: 'POST', body: JSON.stringify({ repo_id: repo, revision, format, ...(format === 'gguf' ? { filename } : {}) }) });
      setPlan(result); setLicense(result.license); setImportKey(crypto.randomUUID());
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function acquire(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    const c = new AbortController(); actionRequest.current = c; const project = getActiveProjectId();
    const key = importKey || crypto.randomUUID(); setImportKey(key);
    try {
      const refs: Record<string, FileRef> = { ...uploaded };
      if (mode === 'local') {
        validateModelFiles(files.filter(file => !refs[file.name]), refs);
        if (files.some(file => refs[file.name])) throw new Error('A selected file already has a verified reference. Remove the reference to replace it, or clear the file picker to continue that exact verified snapshot.');
        for (const file of files) {
          if (c.signal.aborted || getActiveProjectId() !== project) return;
          setNotice(`Verifying ${file.name}…`);
          const form = new FormData(); form.append('file', file);
          refs[file.name] = await apiRequest<FileRef>('/api/v1/model-imports/upload-file/', token, { method: 'POST', body: form, signal: c.signal });
          if (c.signal.aborted) return;
          // The import accepts exactly the three immutable artifact reference fields.
          refs[file.name] = { artifact_id: refs[file.name].artifact_id, sha256: refs[file.name].sha256, byte_size: refs[file.name].byte_size };
          setUploaded({ ...refs });
        }
      }
      if (c.signal.aborted || getActiveProjectId() !== project) return;
      const imported = await apiRequest<Import>('/api/v1/model-imports/', token, { method: 'POST', signal: c.signal, body: JSON.stringify({ name, accepted_license: license,
        idempotency_key: key, ...(mode === 'local' ? { files: refs, ...(format === 'mlx' ? { format } : {}) } : { repo_id: repo, revision, format, pool: Number(pool), ...(format === 'gguf' ? { filename } : {}) }) }) });
      if (c.signal.aborted) return;
      draft.discard(); setFiles([]);
      setNotice(imported.candidate_id ? 'Verified snapshot imported. Open Chat to run it.' : 'Download queued. Follow its status below.');
      await reload(); onImported();
    } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); } finally { if (!c.signal.aborted) setBusy(false); if (actionRequest.current === c) actionRequest.current = null; }
  }
  async function changeImport(item: Import, action: 'cancel' | 'resume') {
    setBusy(true); setError('');
    try { await apiRequest(`/api/v1/model-imports/${item.import_id}/${action}/`, token, { method: 'POST', body: '{}' }); await reload(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <Card className="panel ml-main-panel">
    <div className="panel-title"><div><h2>Acquire a model</h2><p>Search the Hub or import local model files into this project.</p></div></div>
    <div className="panel-body"><DraftStatus draft={draft} disabled={busy} />
      <div className="actions"><Button type="button" disabled={busy} aria-pressed={mode === 'hub'} onClick={() => { setMode('hub'); changed(); }}>Hugging Face</Button>
        <Button type="button" disabled={busy} aria-pressed={mode === 'local'} onClick={() => { setMode('local'); changed(); }}>Local files</Button></div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {hardware.error && <p className="muted" role="status">Hardware inventory unavailable: {hardware.error}</p>}
      {mode === 'hub' && <>
        <form className="form-grid" onSubmit={search}><label>Search models<Field value={query} maxLength={120} onChange={e => setQuery(e.target.value)} required /></label><Button disabled={busy || !token.trim()}>Search</Button></form>
        {results.length > 0 && <ul className="catalog-results">{results.map(m => <li key={m.repo_id}><Button type="button" disabled={busy} onClick={() => { changed(); setRepo(m.repo_id); setRevision(m.revision || ''); setName(m.repo_id.split('/')[1]); }}>{m.repo_id}</Button><span>{m.architecture || m.task || 'Inspect for compatibility'} · {m.license || 'License not listed'}{m.gated ? ' · Access required' : ''}</span></li>)}</ul>}
      </>}
      <form className="form-grid" onSubmit={acquire}>
        <label>Model name<Field value={name} maxLength={180} onChange={e => { setName(e.target.value); setImportKey(''); }} required disabled={busy} /></label>
        {mode === 'hub' ? <Fragment key="hub">
          <label>Repository<Field value={repo} onChange={e => { setRepo(e.target.value); changed(); }} placeholder="owner/model" required disabled={busy} /></label>
          <label>Commit revision<Field value={revision} onChange={e => { setRevision(e.target.value); changed(); }} pattern="[a-f0-9]{40}" minLength={40} maxLength={40} required disabled={busy} /></label>
          <label>Format<select value={format} onChange={e => { setFormat(e.target.value); changed(); }} disabled={busy}><option value="safetensors">Safetensors</option><option value="gguf">GGUF</option><option value="mlx">MLX</option></select></label>
          {format === 'gguf' && <label>GGUF filename<Field value={filename} onChange={e => { setFilename(e.target.value); changed(); }} required disabled={busy} /></label>}
          <Button type="button" disabled={busy || !repo || !/^[a-f0-9]{40}$/.test(revision)} onClick={() => void inspect()}>Inspect snapshot</Button>
          {plan && <div className="detail-box"><strong>{plan.architecture || plan.task || plan.format}</strong><p>{(plan.byte_size / 1024**2).toFixed(1)} MiB · {Object.keys(plan.files).length} files{plan.parameters_count ? ` · ${plan.parameters_count.toLocaleString()} parameters` : ''}</p><p>License: {plan.license}{plan.gated ? ' · Requires operator-configured project Hub access' : ''}</p><p>{plan.training_supported ? 'Compatible with the current pinned training recipe.' : 'Inference compatibility is checked when loaded.'}</p></div>}
          {plan && <ModelHardwareFit memory={plan.memory_requirements} targets={hardware.workers.map(worker => workerHardware(worker, hardware.reportedAt))} />}
          <label>Download worker pool<select value={pool} onChange={e => { setPool(e.target.value); setImportKey(''); }} required disabled={busy}><option value="">Select an import pool</option>{[...new Map(workers.map(w => [w.pool, w])).values()].map(w => <option key={w.pool} value={w.pool}>{w.pool_name}</option>)}</select></label>
          {workers.length === 0 && <p className="muted">Register and connect a model acquisition worker in <a href="#infrastructure">Infrastructure</a> before Hub downloads can run.</p>}
        </Fragment> : <Fragment key="local">
          <label>Local runtime<select value={format === 'mlx' ? 'mlx' : 'safetensors'} onChange={e => { setFormat(e.target.value); changed(); }} disabled={busy}><option value="safetensors">Safetensors / GGUF (automatic)</option><option value="mlx">MLX</option></select></label>
          <label>Snapshot files<input type="file" multiple accept=".safetensors,.gguf,.json,.model,.txt" disabled={busy} onChange={e => { setFiles(Array.from(e.target.files || [])); changed(); }} required={!Object.keys(uploaded).length} /></label>
          <p className="muted">Up to 64 files, 8 GiB per file. Uploads restart a partial file; completed verified files are retained in this tab for retry. Clear the file picker to use saved references, or select only remaining files. Registration revalidates hashes and loadable files.</p>
          {Object.entries(uploaded).map(([filename, ref]) => <div key={filename}><strong>{filename}</strong> · {ref.byte_size.toLocaleString()} verified bytes · SHA-256 <Identifier value={ref.sha256} label={`SHA-256 for ${filename}`} /><Button type="button" disabled={busy} onClick={() => { const refs = { ...uploaded }; delete refs[filename]; setUploaded(refs); setImportKey(''); }}>Remove saved reference for {filename}</Button></div>)}
          {!!localSizes.size && <ModelHardwareFit memory={{ weights_bytes: localWeightBytes || null, training: null }} />}
          <label>Model license<Field value={license} maxLength={200} onChange={e => { setLicense(e.target.value); setAccepted(false); setImportKey(''); }} required disabled={busy} placeholder="apache-2.0" /></label>
        </Fragment>}
        <label className="checkbox-label"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} disabled={busy || (mode === 'hub' && !plan)} required />I have reviewed and accept the model’s license and access terms.</label>
        <Button className="primary" disabled={busy || !accepted || !token.trim() || (mode === 'hub' ? !plan || !pool : !files.length && !Object.keys(uploaded).length)}>{busy ? 'Acquiring…' : 'Import snapshot'}</Button>
      </form>
      {notice && <p role="status">{notice}</p>}
      {imports.length > 0 && <div className="table-wrap"><RecordTable className="resource-table"><thead><tr><th>Import</th><th>Files verified</th><th>Status and controls</th><th>Model</th></tr></thead><tbody>{imports.map(i => <tr key={i.import_id}><td>{i.name}</td><td>{Object.keys(i.acquired_files).length}/{Object.keys(i.files).length}</td><td>{i.job_status || i.status}{i.job_id && <><a href={runHash('job', i.job_id)}>Inspect import job</a>{['queued', 'running'].includes(i.job_status || '') && <Button disabled={busy} onClick={() => void changeImport(i, 'cancel')}>Request import cancellation</Button>}{['failed', 'interrupted', 'cancelled'].includes(i.job_status || '') && <Button disabled={busy} onClick={() => void changeImport(i, 'resume')}>Resume verified import</Button>}</>}</td><td>{i.candidate_id ? <a href={resourceHash('model-version', i.candidate_id)}>Inspect exact imported version</a> : 'Pending'}</td></tr>)}</tbody></RecordTable></div>}
    </div>
  </Card>;
}
