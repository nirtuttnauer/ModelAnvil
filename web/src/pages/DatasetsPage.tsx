import { Button, Checkbox, Disclosure, Field, FileInput, LinkButton, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { apiRequest, apiPage, nextPagePath, errorMessage } from '../api/client';
import { resourceHash } from '../api/resource-routes';
import { useDraft, DraftIndicator } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
import { SegmentBar } from '../components/Charts';
import { DatasetVersionInspector } from '../components/datasets/DatasetVersionInspector';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { DatasetClientError, loadDatasetFirstPages, prepareUploadedDataset } from '../api/datasets';
import type { PrepareUploadedDatasetOptions, Dataset, DatasetFirstPages, DatasetRevision, PreparedDataset, DatasetSourceFormat } from '../api/datasets';
import './datasets.css';

export interface DatasetsPageProps {
  token: string;
  refreshKey?: number;
}

function safeMessage(error: unknown): string {
  return error instanceof DatasetClientError ? error.message : 'The operation failed. No automatic retry.';
}

const SAMPLE = [
  { schema_version: '1.0', sample_id: 'a0000000-0000-0000-0000-000000000001', source_group_id: 'sample-group-1', blocks: [{ block_id: 'prompt', type: 'text', text: 'Generate a vector search icon in clean SVG format.' }], provenance: { source_snapshot_ref: 'snap-1', source_record_key: 'rec-1', content_sha256: 'd9423de59862f0cabd8a79165d2cf9dab32ab2b7c3928b21c99f827cdf26ac28' } },
  { schema_version: '1.0', sample_id: 'a0000000-0000-0000-0000-000000000002', source_group_id: 'sample-group-1', blocks: [{ block_id: 'response', type: 'text', text: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>' }], provenance: { source_snapshot_ref: 'snap-1', source_record_key: 'rec-2', content_sha256: '4797c843099942d81df4c5ad0e73b1e5799a97581a56bcaa499fe92a726e71c6' } },
];

export function DatasetsPage({ token, refreshKey }: DatasetsPageProps) {
  const formId = useId();
  const draft = useDraft('dataset-import', { name: '', sourceFormat: 'training' as DatasetSourceFormat, textField: 'text', groupField: '', chunkCharacters: '', splitSeed: '0', validationPercent: '10', testPercent: '10', detect: false as boolean, dedup: false as boolean, uploadProgress: '', query: '' });
  const [name, setName] = draft.field('name');
  const [detect, setDetect] = draft.field('detect'), [dedup, setDedup] = draft.field('dedup');
  const [uploadProgress, setUploadProgress] = draft.field('uploadProgress'), [query, setQuery] = draft.field('query');
  const [preview, setPreview] = useState<{ split_counts: Record<string, number>; source_group_count: number; recipe_digest: string; [key: string]: unknown } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false), [stage, setStage] = useState('');
  const previewRequest = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceFormat, setSourceFormat] = draft.field('sourceFormat');
  const [textField, setTextField] = draft.field('textField');
  const [groupField, setGroupField] = draft.field('groupField');
  const [chunkCharacters, setChunkCharacters] = draft.field('chunkCharacters');
  const [splitSeed, setSplitSeed] = draft.field('splitSeed');
  const [validationPercent, setValidationPercent] = draft.field('validationPercent');
  const [testPercent, setTestPercent] = draft.field('testPercent');
  const [pages, setPages] = useState<DatasetFirstPages | null>(null);
  const [listingLoading, setListingLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [prepared, setPrepared] = useState<PreparedDataset | null>(null);
  const [selectedRevision, setSelectedRevision] = useState<DatasetRevision | null>(null);
  const tokenRef = useRef(token);
  const listToken = useRef<string | null>(null);
  const preparedToken = useRef<string | null>(null);
  const mounted = useRef(false);
  const listRequest = useRef(0);
  const uploadLocked = useRef(false);
  const lastRefreshKey = useRef<number | undefined>(undefined);
  tokenRef.current = token;

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  const refresh = useCallback(async () => {
    const requestNumber = ++listRequest.current;
    const requestToken = tokenRef.current;
    if (!requestToken?.trim()) { setListingLoading(false); setPages(null); setSelectedRevision(null); listToken.current = null; return; }
    setListingLoading(true); setListError(null); setPages(null); setSelectedRevision(null); listToken.current = null;
    try {
      const result = await loadDatasetFirstPages({ token: requestToken });
      if (!mounted.current || requestNumber !== listRequest.current) return;
      if (tokenRef.current !== requestToken) { setListError('Credentials changed during loading. Refresh explicitly with the current token.'); return; }
      listToken.current = requestToken;
      setPages(result);
    } catch (error) {
      if (mounted.current && requestNumber === listRequest.current) setListError(safeMessage(error));
    } finally {
      if (mounted.current && requestNumber === listRequest.current) setListingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (refreshKey !== undefined && refreshKey !== lastRefreshKey.current) { lastRefreshKey.current = refreshKey; void refresh(); }
  }, [refreshKey, refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (uploadLocked.current || listingLoading) return;
    setPrepared(null); preparedToken.current = null; setUploadError(null);
    if (!file) { setUploadError('Select a nonempty source file.'); return; }
    if (!preview) { setUploadError('Preview the parsed source before publication.'); return; }
    if (!validationPercent.trim() || !testPercent.trim()) { setUploadError('Both split percentages are required.'); return; }
    const requestToken = tokenRef.current;
    uploadLocked.current = true; setUploadLoading(true);
    try {
      const result = await prepareUploadedDataset({
        file, name, token: requestToken, splitSeed, sourceFormat, detect, dedup,
        ...(uploadProgress ? { resume: JSON.parse(uploadProgress) as PrepareUploadedDatasetOptions['resume'] } : {}),
        onProgress: (state, message) => { setUploadProgress(JSON.stringify(state)); if (mounted.current) setStage(message); },
        textField: sourceFormat === 'csv' || sourceFormat === 'json' ? textField : 'text',
        groupField: sourceFormat === 'csv' || sourceFormat === 'json' ? groupField : '',
        chunkCharacters: chunkCharacters ? Number(chunkCharacters) : undefined,
        validationPercent: Number(validationPercent), testPercent: Number(testPercent),
      });
      if (!mounted.current) return;
      if (tokenRef.current !== requestToken) { setUploadError('Credentials changed during preparation. Server resources may remain; refresh explicitly.'); return; }
      preparedToken.current = requestToken;
      setUploadProgress(''); setStage(''); setPrepared(result);
      void refresh();
    } catch (error) {
      if (mounted.current) {
        const partial = error instanceof DatasetClientError && error.step !== 'Input validation';
        setUploadError(safeMessage(error) + (partial ? ' Earlier steps may have left server resources; inspect before submitting again.' : ''));
      }
    } finally {
      uploadLocked.current = false;
      if (mounted.current) setUploadLoading(false);
    }
  }

  function useExampleFile() {
    setSourceFormat('jsonl');
    setFile(new File([SAMPLE.map(row => JSON.stringify(row)).join('\n') + '\n'], 'sample-envelopes.jsonl', { type: 'application/x-ndjson' }));
    setName(`Interactive SVG Sample (${Date.now().toString().slice(-4)})`);
  }

  const preparationOptions = () => ({ split_seed: splitSeed, source_format: sourceFormat,
    text_field: sourceFormat === 'csv' || sourceFormat === 'json' ? textField : 'text',
    group_field: sourceFormat === 'csv' || sourceFormat === 'json' ? groupField || null : null,
    chunk_characters: chunkCharacters ? Number(chunkCharacters) : null,
    validation_percent: Number(validationPercent), test_percent: Number(testPercent), detect, dedup });
  useEffect(() => { previewRequest.current?.abort(); setPreview(null); setPreviewLoading(false); return () => previewRequest.current?.abort(); }, [file, sourceFormat, textField, groupField, chunkCharacters, splitSeed, validationPercent, testPercent, detect, dedup]);
  async function previewSource() {
    if (!file) { setUploadError('Select a source file to preview.'); return; }
    const c = new AbortController(); previewRequest.current?.abort(); previewRequest.current = c;
    setPreviewLoading(true); setUploadError(null);
    const form = new FormData(); form.append('file', file); form.append('configuration', JSON.stringify(preparationOptions()));
    try { const result = await apiRequest<NonNullable<typeof preview>>('/api/v1/datasets/preview/', token, { method: 'POST', body: form, signal: c.signal }); if (!c.signal.aborted) setPreview(result); }
    catch (e) { if (!c.signal.aborted) setUploadError(errorMessage(e)); } finally { if (!c.signal.aborted) setPreviewLoading(false); }
  }
  async function more(kind: 'datasets' | 'revisions') {
    if (!pages?.[kind].next) return;
    setListingLoading(true); setListError(null);
    const path = kind === 'datasets' ? '/api/v1/datasets/' : '/api/v1/dataset-revisions/';
    try {
      const page = await apiPage<Dataset | DatasetRevision>(nextPagePath(pages[kind].next!, path), token);
      setPages(current => current ? { ...current, [kind]: { ...page, results: [...current[kind].results, ...page.results] } } : current);
    } catch (e) { setListError(errorMessage(e)); } finally { setListingLoading(false); }
  }
  const visiblePages = listToken.current === token ? pages : null;
  const visiblePrepared = preparedToken.current === token ? prepared : null;
  const visibleRevision = visiblePages ? selectedRevision : null;
  const busy = listingLoading || uploadLoading;
  const validation = Number(validationPercent), test = Number(testPercent);
  const validSplits = validationPercent.trim() !== '' && testPercent.trim() !== '' && Number.isInteger(validation) && Number.isInteger(test) && validation >= 0 && test >= 0 && validation + test < 100;
  const structured = sourceFormat === 'csv' || sourceFormat === 'json';
  const needle = query.trim().toLowerCase();
  const datasets = visiblePages?.datasets.results.filter(item => `${item.name} ${item.dataset_id}`.toLowerCase().includes(needle)) ?? [];
  const revisions = visiblePages?.revisions.results.filter(item => `${item.revision_id} ${item.dataset} ${item.revision_no}`.toLowerCase().includes(needle)) ?? [];
  const emptyMessage = listingLoading ? 'Loading…' : listError ? 'Could not load. Refresh to try again.' : 'Nothing loaded yet.';

  return <div className="datasets-page">
    <Section title="Upload and prepare a dataset" description="Verified bytes become an immutable dataset version you can train on.">
      {!token.trim() && <p className="muted">Connect a workspace before uploading.</p>}
      <form onSubmit={event => void submit(event)} aria-busy={uploadLoading} className="datasets-form">
        <fieldset disabled={uploadLoading} className="datasets-fieldset">
          <div className="datasets-grid">
            <TextControl label="Dataset name" id={`${formId}-name`} name="dataset-name" value={name} onChange={event => setName(event.target.value)} required autoComplete="off" />
            <Select label="Source format" id={`${formId}-format`} value={sourceFormat} onChange={event => setSourceFormat(event.target.value as DatasetSourceFormat)}>
              <option value="training">Chat, prompt/response or text records</option><option value="jsonl">Sample-envelope JSONL</option><option value="csv">CSV records</option>
              <option value="json">JSON record array</option><option value="docx">DOCX body text</option><option value="pdf">PDF page text</option>
            </Select>
            {structured && <>
              <TextControl label="Text field" id={`${formId}-text-field`} value={textField} onChange={event => setTextField(event.target.value)} required maxLength={128} />
              <TextControl label="Group field" hint="Optional. Keeps related rows in the same split." id={`${formId}-group-field`} value={groupField} onChange={event => setGroupField(event.target.value)} maxLength={128} />
            </>}
            <FileInput className="datasets-wide" label="Source file" id={`${formId}-file`} name="dataset-file" accept={sourceFormat === 'training' ? '.jsonl,.json,.csv' : `.${sourceFormat}`}
              hint="Up to 16 MiB and 10,000 examples." onChange={event => setFile(event.target.files?.[0] ?? null)} />
          </div>
          <Disclosure summary="Split and cleanup options">
            <div className="datasets-grid">
              <TextControl label="Validation percentage" id={`${formId}-validation`} name="validation-percent" type="number" min="0" max="99" step="1" required value={validationPercent} onChange={event => setValidationPercent(event.target.value)} />
              <TextControl label="Test percentage" id={`${formId}-test`} name="test-percent" type="number" min="0" max="99" step="1" required value={testPercent} onChange={event => setTestPercent(event.target.value)} />
              <TextControl label="Split seed" id={`${formId}-seed`} name="split-seed" value={splitSeed} onChange={event => setSplitSeed(event.target.value)} autoComplete="off" />
              <Select label="Text chunk size" hint="Plain text only. Source spans and groups are kept." id={`${formId}-chunk`} value={chunkCharacters} onChange={event => setChunkCharacters(event.target.value)}>
                <option value="">Keep source rows</option>{[128, 256, 512, 1024, 2048, 4096].map(size => <option key={size} value={size}>{size} characters</option>)}
              </Select>
              <Checkbox label="Detect privacy and low-quality text" checked={detect} onChange={e => setDetect(e.target.checked)} />
              <Checkbox label="Remove exact and near duplicates" checked={dedup} onChange={e => setDedup(e.target.checked)} />
            </div>
            {validSplits ? <SegmentBar data={[{ label: 'Train', value: 100 - validation - test }, { label: 'Validation', value: validation }, { label: 'Test', value: test }]} unit="percent" /> : <p className="datasets-error" role="status">Enter whole percentages with a combined total below 100.</p>}
            <p className="muted">Targets only: source groups stay together, so recorded counts can differ.</p>
          </Disclosure>
          <Disclosure summary="Supported upload formats" variant="quiet">
            <ul className="muted datasets-formats">
              <li>Chat <code>messages</code>, <code>prompt</code>/<code>response</code> pairs or a <code>text</code> column in JSONL, JSON or CSV.</li>
              <li>Sample-envelope JSONL with provenance.</li>
              <li>DOCX body paragraphs and table text; headers, images and embedded objects are skipped.</li>
              <li>Text PDFs up to 100 pages and 8 MiB; scanned pages need OCR first.</li>
            </ul>
          </Disclosure>
          <div className="datasets-actions">
            <DraftIndicator draft={draft} disabled={uploadLoading} />
            <div data-ui="actions">
              <Button type="button" variant="quiet" onClick={useExampleFile}>Use an example file</Button>
              <Button type="button" disabled={!file || previewLoading || uploadLoading} onClick={() => void previewSource()}>{previewLoading ? 'Parsing…' : 'Preview examples'}</Button>
              {uploadProgress && <Button type="button" onClick={() => { setUploadProgress(''); setStage(''); }}>Start a new import</Button>}
              <Button variant="primary" type="submit" disabled={!token.trim() || !preview}>{uploadLoading ? 'Preparing…' : uploadProgress ? 'Retry verified import' : 'Prepare dataset'}</Button>
            </div>
          </div>
        </fieldset>
      </form>
      {stage && <p role="status" className="muted">{stage}</p>}
      {uploadError && <Notice tone="error" role="alert">{uploadError}</Notice>}
      {preview && <div className="datasets-preview">
        <p><strong>{preview.source_group_count} source groups</strong> · {Object.entries(preview.split_counts).map(([key, value]) => `${key} ${value}`).join(' · ')}</p>
        {((Number(validationPercent) > 0 && !preview.split_counts.validation) || (Number(testPercent) > 0 && !preview.split_counts.test)) && <Notice tone="caution" role="alert">The requested held-out split has no examples. Add independent source groups or lower the percentages before training.</Notice>}
        <Disclosure summary="Raw preview" variant="quiet"><DataInspector value={preview} /></Disclosure>
      </div>}
      {visiblePrepared && <Notice tone="success" role="status">
        <span><strong>Dataset version {visiblePrepared.revision.revision_no} published</strong> · {visiblePrepared.revision.row_count?.toLocaleString() ?? 'unknown'} examples · {visiblePrepared.dataset.name}</span>
        <span data-ui="actions"><LinkButton variant="primary" href={`#training?dataset_revision=${encodeURIComponent(visiblePrepared.revision.revision_id)}`}>Fine-tune with this dataset</LinkButton><LinkButton href={resourceHash('dataset-revision', visiblePrepared.revision.revision_id)}>Open version</LinkButton></span>
      </Notice>}
    </Section>

    <Section title="Datasets" aria-busy={listingLoading} actions={<Button type="button" variant="quiet" onClick={() => void refresh()} disabled={busy || !token.trim()}>{listingLoading ? 'Loading…' : 'Refresh'}</Button>}>
      <label className="datasets-search">Search datasets and versions<Field value={query} onChange={e => setQuery(e.target.value)} /></label>
      {listError && <Notice tone="error" role="alert">{listError}</Notice>}
      <div className="table-scroll" role="region" aria-label="Datasets table" tabIndex={0}>
        <RecordTable>
          <caption>{visiblePages ? `${datasets.length} of ${visiblePages.datasets.results.length} loaded datasets` : 'Datasets'}</caption>
          <thead><tr><th scope="col">Dataset</th><th scope="col">Current version</th><th scope="col">Created</th></tr></thead>
          <tbody>{datasets.map(item => <tr key={item.dataset_id}>
            <td><strong>{item.name}</strong>{item.description && <small className="muted">{item.description}</small>}</td>
            <td>{item.current_revision ? `Version ${item.current_revision}` : 'None'}</td><td>{new Date(item.created_at).toLocaleString()}</td>
          </tr>)}{!datasets.length && <tr><td colSpan={3} className="muted">{visiblePages ? 'No datasets match.' : emptyMessage}</td></tr>}</tbody>
        </RecordTable>
      </div>
      {visiblePages?.datasets.next && <div data-ui="actions"><Button disabled={listingLoading} onClick={() => void more('datasets')}>Load more datasets</Button></div>}
      <Section title="Dataset versions" level={3} description="Immutable versions with their verified manifest.">
        <div className={`datasets-split${visibleRevision ? ' datasets-split-open' : ''}`}>
          <div className="table-scroll" role="region" aria-label="Dataset versions table" tabIndex={0}>
            <RecordTable>
              <caption>{visiblePages ? `${revisions.length} of ${visiblePages.revisions.results.length} loaded versions` : 'Dataset versions'}</caption>
              <thead><tr><th scope="col">Version</th><th scope="col">Dataset</th><th scope="col">Examples</th><th scope="col">Status</th><th scope="col">Published</th><th scope="col">Inspect</th></tr></thead>
              <tbody>{revisions.map(item => <tr key={item.revision_id} className={visibleRevision?.revision_id === item.revision_id ? 'datasets-selected-row' : undefined}>
                <td>Version {item.revision_no}</td><td>#{item.dataset}</td><td>{item.row_count ?? 'Not prepared'}</td><td><StatusBadge status={item.state} /></td>
                <td>{item.published_at ? new Date(item.published_at).toLocaleString() : 'Not published'}</td>
                <td><Button type="button" size="sm" onClick={() => setSelectedRevision(item)} aria-label={`Inspect version ${item.revision_no}`}>Inspect</Button></td>
              </tr>)}{!revisions.length && <tr><td colSpan={6} className="muted">{visiblePages ? 'No versions match.' : emptyMessage}</td></tr>}</tbody>
            </RecordTable>
          </div>
          {visibleRevision && <DatasetVersionInspector key={visibleRevision.revision_id} revision={visibleRevision} onClose={() => setSelectedRevision(null)} />}
        </div>
        {visiblePages?.revisions.next && <div data-ui="actions"><Button disabled={listingLoading} onClick={() => void more('revisions')}>Load more versions</Button></div>}
      </Section>
    </Section>
  </div>;
}

export default DatasetsPage;
