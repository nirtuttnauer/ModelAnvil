import { useCallback, useEffect, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import '../pages/model-workspace.css';

interface HubModel { repo_id: string; revision: string; task: string; license: string; gated: boolean; architecture: string }
interface Plan extends HubModel { format: string; byte_size: number; parameters_count: number | null; files: Record<string, unknown>; training_supported: boolean }
interface Import { import_id: string; name: string; status: string; job_status: string | null; candidate_id: string | null; files: Record<string, unknown>; acquired_files: Record<string, unknown> }
interface Worker { pool: number; pool_name: string; status: string; capabilities: { model_import?: boolean } }
interface FileRef { artifact_id: string; sha256: string; byte_size: number }

export function ModelCatalog({ token, onImported }: { token: string; onImported: () => void }) {
  const [mode, setMode] = useState<'hub' | 'local'>('hub');
  const [query, setQuery] = useState('SmolLM2');
  const [results, setResults] = useState<HubModel[]>([]);
  const [repo, setRepo] = useState('');
  const [revision, setRevision] = useState('');
  const [format, setFormat] = useState('safetensors');
  const [filename, setFilename] = useState('');
  const [name, setName] = useState('');
  const [plan, setPlan] = useState<Plan | null>(null);
  const [license, setLicense] = useState('');
  const [accepted, setAccepted] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [pool, setPool] = useState('');
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [imports, setImports] = useState<Import[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [importKey, setImportKey] = useState('');
  const [uploaded, setUploaded] = useState<Record<string, FileRef>>({});
  const reload = useCallback(async (signal?: AbortSignal) => {
    const rows = await apiPage<Import>('/api/v1/model-imports/', token, signal);
    if (!signal?.aborted) setImports(rows.results);
  }, [token]);
  useEffect(() => {
    if (!token.trim()) return;
    const controller = new AbortController();
    void reload(controller.signal).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    void apiPage<Worker>('/api/v1/worker-inventory/', token, controller.signal).then(r => {
      if (!controller.signal.aborted) setWorkers(r.results.filter(w => w.capabilities.model_import && ['available', 'busy'].includes(w.status)));
    }).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
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
    const key = importKey || crypto.randomUUID(); setImportKey(key);
    try {
      const refs: Record<string, FileRef> = { ...uploaded };
      if (mode === 'local') {
        if (new Set(files.map(file => file.name)).size !== files.length) throw new Error('Select files with unique filenames.');
        for (const file of files) {
          if (refs[file.name]) continue;
          setNotice(`Verifying ${file.name}…`);
          const form = new FormData(); form.append('file', file);
          refs[file.name] = await apiRequest<FileRef>('/api/v1/model-imports/upload-file/', token, { method: 'POST', body: form });
          // The import accepts exactly the three immutable artifact reference fields.
          refs[file.name] = { artifact_id: refs[file.name].artifact_id, sha256: refs[file.name].sha256, byte_size: refs[file.name].byte_size };
          setUploaded({ ...refs });
        }
      }
      const imported = await apiRequest<Import>('/api/v1/model-imports/', token, { method: 'POST', body: JSON.stringify({ name, accepted_license: license,
        idempotency_key: key, ...(mode === 'local' ? { files: refs, ...(format === 'mlx' ? { format } : {}) } : { repo_id: repo, revision, format, pool: Number(pool), ...(format === 'gguf' ? { filename } : {}) }) }) });
      setNotice(imported.candidate_id ? 'Verified snapshot imported. Open Chat to run it.' : 'Download queued. Follow its status below.');
      await reload(); onImported();
    } catch (e) { setError(errorMessage(e)); setNotice(''); } finally { setBusy(false); }
  }
  return <section className="panel ml-main-panel">
    <div className="panel-title"><div><h2>Acquire a model</h2><p>Search the Hub or import local model files into this project.</p></div></div>
    <div className="panel-body">
      <div className="actions"><button type="button" disabled={busy} aria-pressed={mode === 'hub'} onClick={() => { setMode('hub'); changed(); }}>Hugging Face</button>
        <button type="button" disabled={busy} aria-pressed={mode === 'local'} onClick={() => { setMode('local'); changed(); }}>Local files</button></div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {mode === 'hub' && <>
        <form className="form-grid" onSubmit={search}><label>Search models<input value={query} maxLength={120} onChange={e => setQuery(e.target.value)} required /></label><button disabled={busy || !token.trim()}>Search</button></form>
        {results.length > 0 && <ul className="catalog-results">{results.map(m => <li key={m.repo_id}><button type="button" disabled={busy} onClick={() => { changed(); setRepo(m.repo_id); setRevision(m.revision || ''); setName(m.repo_id.split('/')[1]); }}>{m.repo_id}</button><span>{m.architecture || m.task || 'Inspect for compatibility'} · {m.license || 'License not listed'}{m.gated ? ' · Access required' : ''}</span></li>)}</ul>}
      </>}
      <form className="form-grid" onSubmit={acquire}>
        <label>Model name<input value={name} maxLength={180} onChange={e => { setName(e.target.value); setImportKey(''); }} required disabled={busy} /></label>
        {mode === 'hub' ? <>
          <label>Repository<input value={repo} onChange={e => { setRepo(e.target.value); changed(); }} placeholder="owner/model" required disabled={busy} /></label>
          <label>Commit revision<input value={revision} onChange={e => { setRevision(e.target.value); changed(); }} pattern="[a-f0-9]{40}" minLength={40} maxLength={40} required disabled={busy} /></label>
          <label>Format<select value={format} onChange={e => { setFormat(e.target.value); changed(); }} disabled={busy}><option value="safetensors">Safetensors</option><option value="gguf">GGUF</option><option value="mlx">MLX</option></select></label>
          {format === 'gguf' && <label>GGUF filename<input value={filename} onChange={e => { setFilename(e.target.value); changed(); }} required disabled={busy} /></label>}
          <button type="button" disabled={busy || !repo || !/^[a-f0-9]{40}$/.test(revision)} onClick={() => void inspect()}>Inspect snapshot</button>
          {plan && <div className="detail-box"><strong>{plan.architecture || plan.task || plan.format}</strong><p>{(plan.byte_size / 1024**2).toFixed(1)} MiB · {Object.keys(plan.files).length} files{plan.parameters_count ? ` · ${plan.parameters_count.toLocaleString()} parameters` : ''}</p><p>License: {plan.license}{plan.gated ? ' · Requires operator-configured project Hub access' : ''}</p><p>{plan.training_supported ? 'Compatible with the current pinned training recipe.' : 'Inference compatibility is checked when loaded.'}</p></div>}
          <label>Download worker pool<select value={pool} onChange={e => { setPool(e.target.value); setImportKey(''); }} required disabled={busy}><option value="">Select an import pool</option>{[...new Map(workers.map(w => [w.pool, w])).values()].map(w => <option key={w.pool} value={w.pool}>{w.pool_name}</option>)}</select></label>
          {workers.length === 0 && <p className="muted">An operator must register a worker with model_import enabled before Hub downloads can run.</p>}
        </> : <>
          <label>Local runtime<select value={format === 'mlx' ? 'mlx' : 'safetensors'} onChange={e => { setFormat(e.target.value); changed(); }} disabled={busy}><option value="safetensors">Safetensors / GGUF (automatic)</option><option value="mlx">MLX</option></select></label>
          <label>Snapshot files<input type="file" multiple accept=".safetensors,.gguf,.json,.model,.txt" disabled={busy} onChange={e => { setFiles(Array.from(e.target.files || [])); setUploaded({}); changed(); }} required /></label>
          <p className="muted">Select Safetensors weights, config and tokenizer files, or one GGUF file. Each upload is verified before registration.</p>
          <label>Model license<input value={license} maxLength={200} onChange={e => { setLicense(e.target.value); setAccepted(false); setImportKey(''); }} required disabled={busy} placeholder="apache-2.0" /></label>
        </>}
        <label className="checkbox-label"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} disabled={busy || (mode === 'hub' && !plan)} required />I have reviewed and accept the model’s license and access terms.</label>
        <button className="primary" disabled={busy || !accepted || !token.trim() || (mode === 'hub' ? !plan || !pool : !files.length)}>{busy ? 'Acquiring…' : 'Import snapshot'}</button>
      </form>
      {notice && <p role="status">{notice}</p>}
      {imports.length > 0 && <div className="table-wrap"><table className="resource-table"><thead><tr><th>Import</th><th>Files verified</th><th>Status</th><th>Model</th></tr></thead><tbody>{imports.map(i => <tr key={i.import_id}><td>{i.name}</td><td>{Object.keys(i.acquired_files).length}/{Object.keys(i.files).length}</td><td>{i.job_status || i.status}</td><td>{i.candidate_id ? <a href="#chat">Open Chat</a> : 'Pending'}</td></tr>)}</tbody></table></div>}
    </div>
  </section>;
}
