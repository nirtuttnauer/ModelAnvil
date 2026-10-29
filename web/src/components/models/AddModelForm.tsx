import { Fragment, useEffect, useRef, useState } from 'react';
import { Button, Checkbox, FileInput, KeyValueList, SegmentedControl, Select, TextControl } from '../ui';
import { useDraft, DraftIndicator } from '../Draft';
import { Identifier } from '../Identifier';
import { ModelHardwareFit } from '../ModelHardwareFit';
import { useHardwareInventory } from '../useHardwareInventory';
import { savedModelFiles, validateModelFiles, type ModelFileRef } from '../../api/model-files';
import { workerHardware, type ModelMemory } from '../../api/model-hardware';
import { apiRequest, errorMessage, getActiveProjectId } from '../../api/client';

interface HubModel { repo_id: string; revision: string; task: string; license: string; gated: boolean; architecture: string }
interface Plan extends HubModel { format: string; byte_size: number; parameters_count: number | null; files: Record<string, unknown>; training_supported: boolean; memory_requirements?: ModelMemory }
interface Imported { candidate_id: string | null }

const COMMIT = /^[a-f0-9]{40}$/;

/** The "Add a model" form: search the Hub or upload local files, then import a verified snapshot. */
export function AddModelForm({ token, onImported }: { token: string; onImported(message: string): void }) {
  const hardware = useHardwareInventory(token);
  const workers = hardware.workers.filter(worker => worker.connection_state === 'connected' && worker.capabilities.model_import && ['available', 'busy'].includes(worker.status));
  const pools = [...new Map(workers.map(worker => [worker.pool, worker])).values()];
  const draft = useDraft('model-import', { mode: 'local' as 'hub' | 'local', query: 'SmolLM2', repo: '', revision: '', format: 'safetensors', filename: '', name: '', license: '', pool: '', importKey: '', uploadedJSON: '{}' });
  const actionRequest = useRef<AbortController | null>(null);
  const [uploadedJSON, setUploadedJSON] = draft.field('uploadedJSON');
  const uploaded = savedModelFiles(uploadedJSON);
  const setUploaded = (refs: Record<string, ModelFileRef>) => setUploadedJSON(JSON.stringify(refs));
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
  const localSizes = new Map([...Object.entries(uploaded).map(([file, ref]) => [file, ref.byte_size] as const), ...files.map(file => [file.name, file.size] as const)]);
  const localWeightBytes = [...localSizes].filter(([file]) => file.endsWith('.safetensors') || file.endsWith('.gguf')).reduce((sum, [, size]) => sum + size, 0);
  const [pool, setPool] = draft.field('pool');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState('');
  const [importKey, setImportKey] = draft.field('importKey');
  useEffect(() => () => actionRequest.current?.abort(), []);
  function changed() { setPlan(null); setAccepted(false); setImportKey(''); }
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
    const controller = new AbortController(); actionRequest.current = controller; const project = getActiveProjectId();
    const key = importKey || crypto.randomUUID(); setImportKey(key);
    try {
      const refs: Record<string, ModelFileRef> = { ...uploaded };
      if (mode === 'local') {
        validateModelFiles(files.filter(file => !refs[file.name]), refs);
        if (files.some(file => refs[file.name])) throw new Error('A selected file already has a verified reference. Remove the reference to replace it, or clear the file picker to continue that exact verified snapshot.');
        for (const file of files) {
          if (controller.signal.aborted || getActiveProjectId() !== project) return;
          setProgress(`Verifying ${file.name}…`);
          const form = new FormData(); form.append('file', file);
          const ref = await apiRequest<ModelFileRef>('/api/v1/model-imports/upload-file/', token, { method: 'POST', body: form, signal: controller.signal });
          if (controller.signal.aborted) return;
          // The import accepts exactly the three immutable artifact reference fields.
          refs[file.name] = { artifact_id: ref.artifact_id, sha256: ref.sha256, byte_size: ref.byte_size };
          setUploaded({ ...refs });
        }
      }
      if (controller.signal.aborted || getActiveProjectId() !== project) return;
      const imported = await apiRequest<Imported>('/api/v1/model-imports/', token, { method: 'POST', signal: controller.signal, body: JSON.stringify({ name, accepted_license: license, idempotency_key: key,
        ...(mode === 'local' ? { files: refs, ...(format === 'mlx' ? { format } : {}) } : { repo_id: repo, revision, format, pool: Number(pool), ...(format === 'gguf' ? { filename } : {}) }) }) });
      if (controller.signal.aborted) return;
      draft.discard(); setFiles([]);
      onImported(imported.candidate_id ? 'Model imported. Open Chat to try it.' : 'Download queued. Follow its progress under Imports.');
    } catch (e) { if (!controller.signal.aborted) setError(errorMessage(e)); }
    finally { if (!controller.signal.aborted) { setBusy(false); setProgress(''); } if (actionRequest.current === controller) actionRequest.current = null; }
  }
  const canImport = accepted && !!token.trim() && (mode === 'hub' ? !!plan && !!pool : files.length > 0 || Object.keys(uploaded).length > 0);
  return <div data-ui="form">
    <DraftIndicator draft={draft} disabled={busy} />
    <SegmentedControl label="Source" value={mode} onChange={value => { setMode(value); changed(); }} options={[{ value: 'hub', label: 'Hugging Face' }, { value: 'local', label: 'Local files' }]} />
    {error && <p className="error-text" role="alert">{error}</p>}
    {hardware.error && <p className="muted" role="status">Hardware inventory unavailable: {hardware.error}</p>}
    {mode === 'hub' && <>
      <form className="models-search-form" onSubmit={search}>
        <TextControl label="Search the Hub" value={query} maxLength={120} onChange={event => setQuery(event.target.value)} required />
        <Button disabled={busy || !token.trim()}>Search</Button>
      </form>
      {results.length > 0 && <ul className="models-results">{results.map(item => <li key={item.repo_id}>
        <Button type="button" size="sm" disabled={busy} onClick={() => { changed(); setRepo(item.repo_id); setRevision(item.revision || ''); setName(item.repo_id.split('/')[1]); }}>{item.repo_id}</Button>
        <span>{item.architecture || item.task || 'Check for compatibility'} · {item.license || 'License not listed'}{item.gated ? ' · Access required' : ''}</span>
      </li>)}</ul>}
    </>}
    <form data-ui="form" onSubmit={acquire}>
      <div data-ui="field-grid">
        <TextControl label="Model name" value={name} maxLength={180} onChange={event => { setName(event.target.value); setImportKey(''); }} required disabled={busy} />
        {mode === 'hub' ? <Fragment key="hub">
          <TextControl label="Repository" value={repo} onChange={event => { setRepo(event.target.value); changed(); }} placeholder="owner/model" required disabled={busy} />
          <TextControl label="Commit revision" hint="The 40-character commit hash." value={revision} onChange={event => { setRevision(event.target.value); changed(); }} pattern="[a-f0-9]{40}" minLength={40} maxLength={40} required disabled={busy} />
          <Select label="Format" value={format} onChange={event => { setFormat(event.target.value); changed(); }} disabled={busy}
            options={[{ value: 'safetensors', label: 'Safetensors' }, { value: 'gguf', label: 'GGUF' }, { value: 'mlx', label: 'MLX' }]} />
          {format === 'gguf' && <TextControl label="GGUF filename" value={filename} onChange={event => { setFilename(event.target.value); changed(); }} required disabled={busy} />}
          <Select label="Download worker pool" value={pool} onChange={event => { setPool(event.target.value); setImportKey(''); }} required disabled={busy}>
            <option value="">Select a pool</option>{pools.map(worker => <option key={worker.pool} value={worker.pool}>{worker.pool_name}</option>)}
          </Select>
        </Fragment> : <Fragment key="local">
          <Select label="Local runtime" value={format === 'mlx' ? 'mlx' : 'safetensors'} onChange={event => { setFormat(event.target.value); changed(); }} disabled={busy}
            options={[{ value: 'safetensors', label: 'Safetensors / GGUF (automatic)' }, { value: 'mlx', label: 'MLX' }]} />
          <TextControl label="Model license" value={license} maxLength={200} onChange={event => { setLicense(event.target.value); setAccepted(false); setImportKey(''); }} required disabled={busy} placeholder="apache-2.0" />
          <div data-span="full"><FileInput label="Model files" buttonLabel="Choose files" emptyLabel="No files selected" hint="Up to 64 files, 8 GiB each. Verified files are kept in this tab for retry." multiple accept=".safetensors,.gguf,.json,.model,.txt" disabled={busy}
            onChange={event => { setFiles(Array.from(event.target.files || [])); changed(); }} required={!Object.keys(uploaded).length} /></div>
        </Fragment>}
      </div>
      {mode === 'hub' && <div data-ui="actions">
        <Button type="button" disabled={busy || !repo || !COMMIT.test(revision)} onClick={() => void inspect()}>Check repository</Button>
        {workers.length === 0 && <span className="muted">Connect a model acquisition worker in <a href="#infrastructure">Infrastructure</a> before Hub downloads can run.</span>}
      </div>}
      {mode === 'hub' && plan && <>
        <KeyValueList columns={2} items={[
          { label: 'Architecture', value: plan.architecture || plan.task || plan.format },
          { label: 'Size', value: `${(plan.byte_size / 1024 ** 2).toFixed(1)} MiB · ${Object.keys(plan.files).length} files` },
          { label: 'Parameters', value: plan.parameters_count ? plan.parameters_count.toLocaleString() : 'Not reported' },
          { label: 'License', value: `${plan.license}${plan.gated ? ' · Requires project Hub access' : ''}` },
          { label: 'Training', value: plan.training_supported ? 'Compatible with the current training recipe' : 'Inference compatibility is checked when loaded' },
        ]} />
        <ModelHardwareFit headingLevel={3} memory={plan.memory_requirements} targets={hardware.workers.map(worker => workerHardware(worker, hardware.reportedAt))} />
      </>}
      {mode === 'local' && Object.keys(uploaded).length > 0 && <ul className="models-verified">{Object.entries(uploaded).map(([file, ref]) => <li key={file}>
        <strong>{file}</strong><span>{ref.byte_size.toLocaleString()} verified bytes</span><Identifier value={ref.sha256} label={`SHA-256 for ${file}`} />
        <Button type="button" size="sm" variant="quiet" disabled={busy} aria-label={`Remove saved reference for ${file}`} onClick={() => { const refs = { ...uploaded }; delete refs[file]; setUploaded(refs); setImportKey(''); }}>Remove</Button>
      </li>)}</ul>}
      {mode === 'local' && !!localSizes.size && <ModelHardwareFit headingLevel={3} memory={{ weights_bytes: localWeightBytes || null, training: null }} />}
      <Checkbox label="I have reviewed and accept the model’s license and access terms." checked={accepted} onChange={event => setAccepted(event.target.checked)} disabled={busy || (mode === 'hub' && !plan)} required />
      <div data-ui="actions">
        <Button variant="primary" disabled={busy || !canImport}>{busy ? 'Importing…' : 'Import model'}</Button>
        {progress && <span role="status">{progress}</span>}
      </div>
    </form>
  </div>;
}
