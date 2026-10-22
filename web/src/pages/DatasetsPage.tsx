import { Identifier } from '../components/Identifier';
import { Button, Field, RecordTable } from '../components/ui';
import { apiRequest, apiPage, nextPagePath, errorMessage } from '../api/client';
import { resourceHash } from '../api/resource-routes';
import { useDraft, DraftStatus } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import {
  DatasetClientError, loadDatasetFirstPages, prepareUploadedDataset,
} from '../api/datasets';
import type { PrepareUploadedDatasetOptions, Dataset, DatasetFirstPages, DatasetRevision, PreparedDataset, DatasetSourceFormat } from '../api/datasets';
import { BarChart, ChartEmpty, ChartPanel, EventTimeline, SegmentBar } from '../components/Charts';
import { numericEntries } from '../components/chart-data';
import './datasets.css';
import './data-workspace.css';

export interface DatasetsPageProps {
  token: string;
  refreshKey?: number;
}

function safeMessage(error: unknown): string {
  return error instanceof DatasetClientError ? error.message : 'The operation failed. No automatic retry.';
}

function RevisionDetails({ revision }: { revision: DatasetRevision }) {
  const splits = numericEntries(revision.metadata.split_counts).filter(item => Number.isInteger(item.value) && item.value >= 0);
  const report = revision.metadata.drop_report;
  const reasons = numericEntries(report && typeof report === 'object' ? (report as Record<string, unknown>).drop_reason_counts : undefined);
  return <div className="datasets-revision-details">
    <dl className="datasets-facts">
      <div><dt>Revision UUID</dt><dd><Identifier value={revision.revision_id} label="Revision ID" /></dd></div>
      <div><dt>Revision number</dt><dd>{revision.revision_no}</dd></div>
      <div><dt>State</dt><dd>{revision.state}</dd></div>
      <div><dt>Rows</dt><dd>{revision.row_count ?? 'Not prepared'}</dd></div>
      <div><dt>Schema version</dt><dd>{revision.schema_version}</dd></div>
      <div><dt>Dataset record</dt><dd><Identifier value={revision.dataset} label="Dataset record ID" /></dd></div>
      <div><dt>Manifest artifact record</dt><dd>{revision.manifest_artifact ? <Identifier value={revision.manifest_artifact} label="Manifest artifact ID" /> : 'None'}</dd></div>
      <div><dt>Published at</dt><dd>{revision.published_at ?? 'Not published'}</dd></div>
      <div className="datasets-wide"><dt>Manifest digest</dt><dd><Identifier value={revision.manifest_digest} label="Manifest SHA-256" /></dd></div>
      <div className="datasets-wide"><dt>Recipe digest</dt><dd><Identifier value={revision.recipe_digest} label="Recipe SHA-256" /></dd></div>
    </dl>
    <div className="visualization-grid equal">
      <ChartPanel title="Recorded split allocation" description="Actual sample counts from this revision's published metadata.">{splits.length ? <SegmentBar data={splits} unit="samples" /> : <ChartEmpty message="This revision does not report split counts. Allocation is not inferred from configured percentages." />}</ChartPanel>
      <ChartPanel title="Preparation evidence" description="Immutable artifact and source references for this revision."><EventTimeline events={[{ label: 'Source references', detail: `${revision.source_snapshots.length} snapshot references recorded`, status: 'ready' }, { label: 'Recipe pinned', detail: revision.recipe_digest ? 'SHA-256 recorded' : 'Recipe digest not recorded', status: revision.recipe_digest ? 'ready' : 'pending' }, { label: 'Revision publication', detail: revision.published_at ? new Date(revision.published_at).toLocaleString() : 'Not published', status: revision.state }]} /></ChartPanel>
    </div>
    {reasons.length > 0 && <ChartPanel title="Recorded exclusions" description="Counts by detection reason. A sample may have multiple reasons."><BarChart data={reasons} unit="Reason occurrences" /></ChartPanel>}
    <details><summary>Source snapshot references</summary><DataInspector value={revision.source_snapshots} /></details>
    <a href={resourceHash('dataset-revision', revision.revision_id)}>Open exact revision, records and lineage</a><details><summary>Revision metadata</summary><DataInspector value={revision.metadata} /></details>
  </div>;
}

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

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const refresh = useCallback(async () => {
    const requestNumber = ++listRequest.current;
    const requestToken = tokenRef.current;
    if (!requestToken?.trim()) {
      setListingLoading(false);
      setPages(null);
      setSelectedRevision(null);
      listToken.current = null;
      return;
    }
    setListingLoading(true);
    setListError(null);
    setPages(null);
    setSelectedRevision(null);
    listToken.current = null;
    try {
      const result = await loadDatasetFirstPages({ token: requestToken });
      if (!mounted.current || requestNumber !== listRequest.current) return;
      if (tokenRef.current !== requestToken) {
        setListError('Credentials changed during loading. Refresh explicitly with the current token.');
        return;
      }
      listToken.current = requestToken;
      setPages(result);
    } catch (error) {
      if (mounted.current && requestNumber === listRequest.current) setListError(safeMessage(error));
    } finally {
      if (mounted.current && requestNumber === listRequest.current) setListingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (refreshKey !== undefined && refreshKey !== lastRefreshKey.current) {
      lastRefreshKey.current = refreshKey;
      void refresh();
    }
  }, [refreshKey, refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (uploadLocked.current || listingLoading) return;
    setPrepared(null);
    preparedToken.current = null;
    setUploadError(null);
    if (!file) { setUploadError('Select a nonempty source file.'); return; }
    if (!preview) { setUploadError('Preview and review the parsed source before publication.'); return; }
    if (!validationPercent.trim() || !testPercent.trim()) {
      setUploadError('Both split percentages are required.');
      return;
    }
    const requestToken = tokenRef.current;
    uploadLocked.current = true;
    setUploadLoading(true);
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
      if (tokenRef.current !== requestToken) {
        setUploadError('Credentials changed during preparation. Server resources may remain; refresh explicitly.');
        return;
      }
      preparedToken.current = requestToken;
      setUploadProgress(''); setStage('Publication confirmed.'); setPrepared(result);
      void refresh();
    } catch (error) {
      if (mounted.current) {
        const partial = error instanceof DatasetClientError && error.step !== 'Input validation';
        setUploadError(safeMessage(error) + (partial
          ? ' Earlier steps may have left server resources. Nothing was automatically deleted; inspect before submitting again.' : ''));
      }
    } finally {
      uploadLocked.current = false;
      if (mounted.current) setUploadLoading(false);
    }
  }

  function handleAutoFillSample() {
    setSourceFormat('jsonl');
    const sample = [
      JSON.stringify({
        schema_version: '1.0',
        sample_id: 'a0000000-0000-0000-0000-000000000001',
        source_group_id: 'sample-group-1',
        blocks: [{ block_id: 'prompt', type: 'text', text: 'Generate a vector search icon in clean SVG format.' }],
        provenance: {
          source_snapshot_ref: 'snap-1',
          source_record_key: 'rec-1',
          content_sha256: 'd9423de59862f0cabd8a79165d2cf9dab32ab2b7c3928b21c99f827cdf26ac28',
        },
      }),
      JSON.stringify({
        schema_version: '1.0',
        sample_id: 'a0000000-0000-0000-0000-000000000002',
        source_group_id: 'sample-group-1',
        blocks: [{ block_id: 'response', type: 'text', text: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>' }],
        provenance: {
          source_snapshot_ref: 'snap-1',
          source_record_key: 'rec-2',
          content_sha256: '4797c843099942d81df4c5ad0e73b1e5799a97581a56bcaa499fe92a726e71c6',
        },
      }),
    ].join('\n') + '\n';
    const sampleFile = new File([sample], 'sample-envelopes.jsonl', { type: 'application/x-ndjson' });
    setFile(sampleFile);
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
  const emptyMessage = listingLoading ? 'Loading first page…' : listError
    ? 'This first page could not be loaded. Refresh explicitly to try again.'
    : 'Not loaded. Choose Refresh lists to fetch the first page.';

  return <div className="datasets-page">
    <details className="workspace-details"><summary>Upload and prepare a dataset</summary>
    <section className="datasets-capability" aria-labelledby={`${formId}-capability`}>
      <h2 id={`${formId}-capability`}>Supported upload formats</h2>
      <p>Upload chat or prompt/response JSONL, JSON or CSV, canonical envelopes, DOCX main-body text or a text PDF to prepare a dataset version.
        Files are stored locally and verified before publication.</p>
    </section>

    <div className="datasets-preparation-grid">
    <section className="datasets-panel" aria-labelledby={`${formId}-upload-heading`}>
      <div className="datasets-panel-heading"><div>
        <h2 id={`${formId}-upload-heading`}>Upload and prepare</h2>
        <p>Create one dataset and publish a revision after the uploaded bytes are verified.</p>
      </div><span className="datasets-badge">LOCAL / {sourceFormat.toUpperCase()}</span></div>
      {!token.trim() && <p className="datasets-hint">Open Connection and enter an API key before uploading or loading datasets.</p>}
      <form onSubmit={event => void submit(event)} aria-describedby={`${formId}-file-help`} aria-busy={uploadLoading}><DraftStatus draft={draft} disabled={uploadLoading} /><p className="muted">File contents are not stored in drafts. Reattach the source file after navigation or reload.</p>
        <fieldset disabled={busy} className="datasets-form-fields">
          <legend>Source file & split configuration</legend>

          <div className="datasets-field datasets-wide" style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.25rem' }}>
            <Button
              type="button"
              onClick={handleAutoFillSample}
              className="datasets-example"
            >
              Use an example file
            </Button>
          </div>

          <div className="datasets-field datasets-wide">
            <label htmlFor={`${formId}-name`}>Dataset name</label>
            <Field id={`${formId}-name`} name="dataset-name" value={name} onChange={event => setName(event.target.value)} required autoComplete="off" />
          </div>
          <div className="datasets-field datasets-wide">
            <label htmlFor={`${formId}-format`}>Source format</label>
            <select id={`${formId}-format`} value={sourceFormat} onChange={event => setSourceFormat(event.target.value as DatasetSourceFormat)}>
              <option value="training">Chat, prompt/response or text records</option><option value="jsonl">Canonical sample-envelope JSONL</option><option value="csv">CSV records</option>
              <option value="json">JSON record array</option><option value="docx">DOCX main-body text</option><option value="pdf">PDF page text</option>
            </select>
          </div>
          {(sourceFormat === 'csv' || sourceFormat === 'json') && <>
            <div className="datasets-field"><label htmlFor={`${formId}-text-field`}>Text field</label>
              <Field id={`${formId}-text-field`} value={textField} onChange={event => setTextField(event.target.value)} required maxLength={128} /></div>
            <div className="datasets-field"><label htmlFor={`${formId}-group-field`}>Source group field (optional)</label>
              <Field id={`${formId}-group-field`} value={groupField} onChange={event => setGroupField(event.target.value)} maxLength={128} /></div>
          </>}
          <div className="datasets-field datasets-wide">
            <label htmlFor={`${formId}-file`}>Source file</label>
            <input id={`${formId}-file`} name="dataset-file" type="file" accept={sourceFormat === 'training' ? '.jsonl,.json,.csv' : `.${sourceFormat}`}
              aria-describedby={`${formId}-file-help`} onChange={event => setFile(event.target.files?.[0] ?? null)} />
            <p id={`${formId}-file-help`} className="datasets-hint">Maximum 16 MiB and 10,000 samples. CSV and JSON text fields must contain nonempty strings.
              Without a source group field, the entire file stays in one split. DOCX imports body paragraphs and table text; headers, images and embedded objects are excluded.
              PDF requires the optional document dependencies and supports up to 100 text pages, 1 MiB decoded content per page and 8 MiB total. Encrypted or scanned pages are refused; run OCR separately first.</p>
            {file && <p className="datasets-hint">Selected: {file.name} · {file.size.toLocaleString()} bytes</p>}
          </div>
          <div className="datasets-field">
            <label htmlFor={`${formId}-seed`}>Split seed</label>
            <Field id={`${formId}-seed`} name="split-seed" value={splitSeed} onChange={event => setSplitSeed(event.target.value)} autoComplete="off" />
          </div>
          <div className="datasets-field"><label htmlFor={`${formId}-chunk`}>Text chunk size</label>
            <select id={`${formId}-chunk`} value={chunkCharacters} onChange={event => setChunkCharacters(event.target.value)}>
              <option value="">Keep source rows</option>{[128, 256, 512, 1024, 2048, 4096].map(size => <option key={size} value={size}>{size} characters</option>)}
            </select><p className="datasets-hint">Plain text only. Exact source spans and split groups are retained. Training preflight separately checks tokenizer length.</p></div>
          <div className="datasets-field">
            <label htmlFor={`${formId}-validation`}>Validation percentage</label>
            <Field id={`${formId}-validation`} name="validation-percent" type="number" min="0" max="99" step="1" required
              value={validationPercent} onChange={event => setValidationPercent(event.target.value)} aria-describedby={`${formId}-split-help`} />
          </div>
          <div className="datasets-field">
            <label htmlFor={`${formId}-test`}>Test percentage</label>
            <Field id={`${formId}-test`} name="test-percent" type="number" min="0" max="99" step="1" required
              value={testPercent} onChange={event => setTestPercent(event.target.value)} aria-describedby={`${formId}-split-help`} />
          </div>
          <p id={`${formId}-split-help`} className="datasets-hint datasets-wide">Percentages must be nonnegative integers with a combined total below 100.
            Remaining rows belong to the training split; creating that split does not run training.</p>
          <label><input type="checkbox" checked={detect} onChange={e => setDetect(e.target.checked)} />Detect privacy and low quality text</label>
          <label><input type="checkbox" checked={dedup} onChange={e => setDedup(e.target.checked)} />Remove exact and near duplicates</label>
          <p className="datasets-hint datasets-wide">Single uploads support at most 16 MiB. Partial file uploads restart; a fully verified upload and dataset record are retained for explicit retry. Reattach the same file after reload. Publication repeats the previewed recipe.</p>
          <div className="datasets-form-actions datasets-wide"><Button type="button" disabled={!file || previewLoading || uploadLoading} onClick={() => void previewSource()}>{previewLoading ? 'Parsing source…' : 'Preview parsed source'}</Button>
            {uploadProgress && <Button type="button" onClick={() => { setUploadProgress(''); setStage(''); }}>Start a new import</Button>}
            <Button className="datasets-primary" type="submit" disabled={!token.trim() || !preview}>{uploadLoading ? 'Uploading and preparing…' : uploadProgress ? 'Retry verified import' : 'Upload and prepare dataset'}</Button>
            <span className="datasets-hint">File integrity is verified before publication.</span>
          </div>
        </fieldset>
      </form>
      {stage && <p role="status">{stage}</p>}{uploadLoading && <p className="datasets-notice" role="status">Uploading and preparing. A successful published revision must be confirmed before completion.</p>}
      {uploadError && <p className="datasets-error" role="alert">{uploadError}</p>}
      {visiblePrepared && <section className="datasets-success" aria-labelledby={`${formId}-prepared-heading`}>
        <h3 id={`${formId}-prepared-heading`}>Published revision confirmed</h3><a href={resourceHash('dataset-revision', visiblePrepared.revision.revision_id)}>Inspect this exact published revision</a>
        <p role="status">Preparation succeeded for {visiblePrepared.dataset.name}. Use Refresh lists to update the first-page tables.</p>
        <dl className="datasets-facts">
          <div><dt>Dataset UUID</dt><dd><Identifier value={visiblePrepared.dataset.dataset_id} label="Dataset ID" /></dd></div>
          <div><dt>Input artifact UUID</dt><dd><Identifier value={visiblePrepared.artifact.artifact_id} label="Input artifact ID" /></dd></div>
          <div><dt>Uploaded bytes</dt><dd>{visiblePrepared.artifact.byte_size}</dd></div>
          <div><dt>Upload state</dt><dd>{visiblePrepared.artifact.state}</dd></div>
          <div className="datasets-wide"><dt>Verified input SHA-256</dt><dd><Identifier value={visiblePrepared.artifact.sha256} label="Verified input SHA-256" /></dd></div>
        </dl>
        <RevisionDetails revision={visiblePrepared.revision} />
      </section>}
    </section>

    <aside className="datasets-preview-column" aria-label="Dataset preparation preview">
      {preview && <section className="datasets-panel"><h3>Parsed source and preparation review</h3><p>{preview.source_group_count} independent source groups · {Object.entries(preview.split_counts).map(([key, value]) => `${key}: ${value}`).join(' · ')}</p>
        {((Number(validationPercent) > 0 && !preview.split_counts.validation) || (Number(testPercent) > 0 && !preview.split_counts.test)) && <p role="alert">Requested held-out allocation has no samples. Add independent source groups or revise the split recipe before training.</p>}
        <DataInspector value={preview} /></section>}
      <ChartPanel title="Split configuration" description="Preview of requested percentages, before preparation.">{validSplits ? <SegmentBar data={[{ label: 'Train', value: 100 - validation - test }, { label: 'Validation', value: validation }, { label: 'Test', value: test }]} unit="percent" /> : <p className="datasets-error">Enter whole percentages with a combined total below 100.</p>}<p className="datasets-hint">These are configuration targets. Source groups stay together, so actual sample counts can differ. Inspect the published revision for recorded allocation.</p></ChartPanel>
      {visiblePrepared && <a className="button" href={`#training?dataset_revision=${encodeURIComponent(visiblePrepared.revision.revision_id)}`}>Fine-tune with this dataset</a>}
      <ChartPanel title="Publication flow" description="Verified input becomes an immutable dataset revision."><EventTimeline events={[{ label: 'Select source file', detail: file ? `${file.name} · ${file.size.toLocaleString()} bytes` : `${sourceFormat.toUpperCase()} source · up to 16 MiB`, status: file ? 'ready' : 'pending' }, { label: 'Verify & prepare', detail: visiblePrepared ? 'Input SHA-256 verified' : 'SHA-256 verification, schema validation, and source-group splits', status: visiblePrepared ? 'completed' : uploadLoading ? 'running' : 'pending' }, { label: 'Publish immutable revision', detail: visiblePrepared ? `Revision ${visiblePrepared.revision.revision_no} · ${visiblePrepared.revision.row_count?.toLocaleString()} samples` : 'Confirmation requires a published server revision.', status: visiblePrepared ? 'published' : 'pending' }]} /></ChartPanel>
    </aside>
    </div>
    </details>
    <section className="datasets-panel" aria-labelledby={`${formId}-lists-heading`} aria-busy={listingLoading}>
      <div className="datasets-panel-heading"><div>
        <h2 id={`${formId}-lists-heading`}>Dataset and revision lists</h2>
        <p>Showing the first page of datasets and immutable revisions.</p>
      </div><Button type="button" onClick={() => void refresh()} disabled={busy || !token.trim()}>{listingLoading ? 'Loading lists…' : 'Refresh lists'}</Button></div>
      {listingLoading && <p className="datasets-notice" role="status">Loading dataset and revision first pages…</p>}
      {listError && <p className="datasets-error" role="alert">{listError}</p>}
      {visiblePages && <details className="workspace-details"><summary>Revision statistics</summary><div className="visualization-grid equal"><ChartPanel title="Revision size" description="Recorded row counts in the loaded first page; revisions can overlap."><BarChart data={visiblePages.revisions.results.filter(item => item.row_count !== null).map(item => ({ label: `Dataset #${item.dataset} · r${item.revision_no}`, value: item.row_count!, color: 0 }))} unit="Samples per revision" emptyMessage="No recorded revision row counts in this page." /></ChartPanel><ChartPanel title="Revision states" description="Counts for the loaded revision first page."><BarChart data={[...new Set(visiblePages.revisions.results.map(item => item.state))].map(state => ({ label: state.replaceAll('_', ' '), value: visiblePages.revisions.results.filter(item => item.state === state).length }))} unit="Revisions" /></ChartPanel></div></details>}
      <label>Search loaded datasets and revisions<Field value={query} onChange={e => setQuery(e.target.value)} /></label><div className="datasets-table-wrap" role="region" aria-label="Dataset first-page table" tabIndex={0}>
        <RecordTable>
          <caption>Datasets · loaded pages{visiblePages ? ` · ${visiblePages.datasets.results.length} rows shown` : ''}</caption>
          <thead><tr><th scope="col">Dataset</th><th scope="col">Current revision record</th><th scope="col">Created at</th></tr></thead>
          <tbody>{visiblePages?.datasets.results.filter(item => `${item.name} ${item.dataset_id}`.toLowerCase().includes(query.toLowerCase())).map(item => <tr key={item.dataset_id}>
            <td><strong>{item.name}</strong><Identifier value={item.dataset_id} label="Dataset ID" />{item.description && <span className="datasets-description">{item.description}</span>}</td>
            <td>{item.current_revision ? `#${item.current_revision}` : 'No revision'}</td><td>{new Date(item.created_at).toLocaleString()}</td>
          </tr>)}{!visiblePages?.datasets.results.length && <tr><td colSpan={3} className="datasets-empty">{visiblePages ? 'No datasets returned on this first page.' : emptyMessage}</td></tr>}</tbody>
        </RecordTable>
      </div>
      {visiblePages?.datasets.next && <Button disabled={listingLoading} onClick={() => void more('datasets')}>Load more datasets</Button>}
      <p className="datasets-hint">Revision records are listed separately. Inspect a revision to see its schema, source references, and verified manifest.</p>
      <div className="datasets-table-wrap" role="region" aria-label="Revision first-page table" tabIndex={0}>
        <RecordTable>
          <caption>Dataset revisions · loaded pages{visiblePages ? ` · ${visiblePages.revisions.results.length} rows shown` : ''}</caption>
          <thead><tr><th scope="col">Revision UUID / number</th><th scope="col">Dataset record</th><th scope="col">Rows</th><th scope="col">State</th><th scope="col">Published at</th><th scope="col">Inspect</th></tr></thead>
          <tbody>{visiblePages?.revisions.results.filter(item => `${item.revision_id} ${item.dataset} ${item.revision_no}`.toLowerCase().includes(query.toLowerCase())).map(item => <tr key={item.revision_id}>
            <td><Identifier value={item.revision_id} label="Revision ID" /><span className="datasets-description">Revision {item.revision_no}</span></td>
            <td>#{item.dataset}</td><td>{item.row_count ?? 'Not prepared'}</td><td><span className="datasets-badge">{item.state}</span></td><td>{item.published_at ? new Date(item.published_at).toLocaleString() : 'Not published'}</td>
            <td><Button type="button" onClick={() => setSelectedRevision(item)} aria-label={`Inspect revision ${item.revision_no}, ${item.revision_id}`}>Inspect</Button></td>
          </tr>)}{!visiblePages?.revisions.results.length && <tr><td colSpan={6} className="datasets-empty">{visiblePages ? 'No revisions returned on this first page.' : emptyMessage}</td></tr>}</tbody>
        </RecordTable>
      </div>
      {visiblePages?.revisions.next && <Button disabled={listingLoading} onClick={() => void more('revisions')}>Load more revisions</Button>}
      {visibleRevision && <section className="datasets-inspection" aria-labelledby={`${formId}-inspect-heading`}>
        <div className="datasets-panel-heading"><h3 id={`${formId}-inspect-heading`}>Revision inspection</h3><Button type="button" onClick={() => setSelectedRevision(null)}>Close inspection</Button></div>
        <RevisionDetails revision={visibleRevision} />
      </section>}
    </section>
  </div>;
}

export default DatasetsPage;
