import { Badge, Button, Disclosure, FileInput, KeyValueList, Notice, StatusBadge, TextControl } from './ui';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, LoaderCircle } from 'lucide-react';
import { apiRequest, errorMessage } from '../api/client';
import { prepareUploadedDataset, type PrepareUploadedDatasetOptions } from '../api/datasets';
import { readGuidedValue, type GuidedInputs, type GuidedOptions, type GuidedPreview, type GuidedRevision } from '../api/guided-training';
import { useDraft } from './Draft';
import type { TrainingConfiguration } from '../api/training-workspace';
import { ModelHardwareFit } from './ModelHardwareFit';
import { DatasetValidationWarnings, PreparedDatasetPreview, TrainingSourcePreview, TrainingSampleRows } from './TrainingDatasetPreview';
import { columnMappingError, type TrainingColumnMapping, type TrainingDatasetValidation, type TrainingSourceInspection } from '../api/training-dataset';
import { memoryBytes, type HardwareTarget } from '../api/model-hardware';
import { classificationStarterCsv } from '../api/classification-starter';
import './guided-training.css';

const titles = ['Choose your pretrained model', 'Add your training examples', 'Model and dataset selected'];

/** The three Prepare steps: model, examples, review. Edits the same draft as the advanced form. */
export function GuidedFineTune({ token, draft, modelLabel, datasetLabel, datasetRevisionId, onModelPrepared, onDatasetPrepared, onBusyChange }: {
  token: string; draft: ReturnType<typeof useDraft<TrainingConfiguration>>; modelLabel: string; datasetLabel: string;
  datasetRevisionId?: string;
  onModelPrepared: (inputs: GuidedInputs, name: string) => void;
  onDatasetPrepared: (revision: GuidedRevision) => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const [stage, setStage] = draft.field('guidedStage');
  const [name, setName] = draft.field('name');
  const [resumeJson, setResumeJson] = draft.field('resumeJson');
  const [selectedDataset] = draft.field('selectedDataset');
  const [mappingJson, setMappingJson] = draft.field('columnMappingJson');
  const mapping = readGuidedValue<TrainingColumnMapping>(mappingJson) || { mode: 'auto' as const };
  const [inspection, setInspection] = useState<TrainingSourceInspection | null>(null);
  const [validation, setValidation] = useState<TrainingDatasetValidation | null>(null);
  const [checkingValidation, setCheckingValidation] = useState(false);
  const [inspectionRetry, setInspectionRetry] = useState(0);
  const mappingProblem = inspection ? columnMappingError(mapping, inspection.columns) : null;
  const [options, setOptions] = useState<GuidedOptions | null>(null); const [retry, setRetry] = useState(0);
  const [file, setFile] = useState<File | null>(null); const [preview, setPreview] = useState<GuidedPreview | null>(null);
  const [busy, setBusy] = useState(false); const [progress, setProgress] = useState('');
  const [error, setError] = useState(''); const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { onBusyChange(busy || checkingValidation); }, [busy, checkingValidation, onBusyChange]);
  useEffect(() => { heading.current?.focus(); }, [stage]);
  useEffect(() => { setPreview(null); setResumeJson(''); }, [mappingJson]);
  useEffect(() => {
    const controller = new AbortController(); setInspection(null); setPreview(null);
    if (!file) return () => controller.abort();
    setBusy(true); setError(''); setProgress('Inspecting source rows and columns…');
    const body = new FormData(); body.append('file', file);
    void apiRequest<TrainingSourceInspection>('/api/v1/fine-tuning/inspect-source/', token, { method: 'POST', body, signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) { setInspection(value); setMappingJson(JSON.stringify(value.recommended_mapping)); } })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) { setBusy(false); setProgress(''); } });
    return () => controller.abort();
  }, [file, token, inspectionRetry]);
  useEffect(() => {
    const controller = new AbortController();
    setValidation(null); setCheckingValidation(false);
    if (!file || !inspection || mappingProblem) return () => controller.abort();
    if (JSON.stringify(inspection.validation?.mapping) === mappingJson) {
      setValidation(inspection.validation ?? null); return () => controller.abort();
    }
    setCheckingValidation(true);
    const timer = setTimeout(() => {
      const body = new FormData(); body.append('file', file); body.append('source_mapping', mappingJson);
      void apiRequest<TrainingSourceInspection>('/api/v1/fine-tuning/inspect-source/', token, { method: 'POST', body, signal: controller.signal })
        .then(value => { if (!controller.signal.aborted) { setValidation(value.validation ?? null); setError(''); } })
        .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
        .finally(() => { if (!controller.signal.aborted) setCheckingValidation(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [file, inspection, mappingJson, token, retry]);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try { const value = await apiRequest<GuidedOptions>('/api/v1/fine-tuning/options/', token, { signal: controller.signal }); if (!controller.signal.aborted) setOptions(value); }
      catch (e) { if (!controller.signal.aborted) setError(errorMessage(e)); }
    }
    void load(); const timer = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [token, retry]);
  async function prepareModel() {
    setBusy(true); setError(''); setProgress('Preparing pretrained weights and matching training resources…');
    try { const result = await apiRequest<{ inputs: GuidedInputs }>('/api/v1/fine-tuning/setup/', token,
      { method: 'POST', body: JSON.stringify({ model: options?.model.id }) }); onModelPrepared(result.inputs, options?.model.name || 'SmolLM2 Instruct'); setStage(selectedDataset ? 2 : 1); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); setProgress(''); }
  }
  async function inspectFile() {
    if (!file || !inspection || mappingProblem || checkingValidation || !validation?.can_prepare) return; setBusy(true); setError(''); setPreview(null);
    try { const body = new FormData(); body.append('file', file); body.append('source_mapping', JSON.stringify(mapping)); setPreview(await apiRequest<GuidedPreview>('/api/v1/fine-tuning/preview/', token, { method: 'POST', body })); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function publish() {
    if (!file || !preview) return; setBusy(true); setError('');
    try { const result = await prepareUploadedDataset({ file, name: name.trim(), token, sourceFormat: 'training', sourceMapping: mapping,
      dedup: { exact: true, near: false }, resume: readGuidedValue<PrepareUploadedDatasetOptions['resume']>(resumeJson) ?? undefined,
      onProgress: (value, message) => { setResumeJson(JSON.stringify(value)); setProgress(message); } });
      if (result.revision.recipe_digest !== preview.recipe_digest) throw new Error('The published recipe differs from your preview. Review the dataset again before training.');
      const value = await apiRequest<GuidedRevision>(`/api/v1/dataset-revisions/${result.revision.revision_id}/`, token);
      onDatasetPrepared(value); setStage(2);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); setProgress(''); }
  }
  function changeFile(value: File | null) { setFile(value); setPreview(null); setError(''); setResumeJson(''); if (value && !name.trim()) setName(value.name.replace(/\.[^.]+$/, '')); }
  const target: HardwareTarget | null = options ? { id: 'managed-local', name: 'This computer',
    hostBytes: memoryBytes(options.compute.memory_bytes), acceleratorBytes: null,
    backend: options.compute.device?.split(':')[0] || '', runtimeContract: options.model.memory_requirements?.training?.runtime_contract || '',
    connected: options.compute.available, busy: options.compute.busy,
    observedAt: Date.parse(options.compute.memory_observed_at || ''), maxAgeSeconds: 15 } : null;
  return <section className="guided-training" aria-label="Guided fine-tuning" aria-busy={busy}>
    <h2 ref={heading} tabIndex={-1}>{titles[stage]}</h2>
    {error && <Notice tone="error" role="alert">{error}<Button type="button" disabled={busy} onClick={() => { setError(''); if (stage === 1 && file && !inspection) setInspectionRetry(value => value + 1); else setRetry(v => v + 1); }}>Try again</Button></Notice>}
    {busy && <p role="status" className="guided-progress"><LoaderCircle size={16} aria-hidden="true" /> {progress || 'Working…'}</p>}
    {stage === 0 && (options ? <>
      <div className="guided-model">
        <div><strong>{options.model.name}</strong> <Badge tone="info">Recommended for this computer</Badge></div>
        <p>{options.model.description}</p>
        <p className="muted">{options.model.parameters >= 1000000000 ? '1.7 billion' : '135 million'} parameters · {options.model.license} · up to {options.model.max_tokens} tokens per example · <a href="https://www.apache.org/licenses/LICENSE-2.0" target="_blank" rel="noreferrer">Model license</a></p>
      </div>
      <p role="status" className="guided-compute"><StatusBadge status={options.compute.available ? 'ready' : 'blocked'} label={options.compute.available ? 'Ready' : 'Not available'} /><span>{options.compute.message} Tokenizer, settings and compute are set up for you.</span></p>
      <div data-ui="actions"><Button type="button" variant="primary" size="lg" onClick={() => void prepareModel()} disabled={busy || !options.compute.available}>Use this model <ArrowRight size={16} aria-hidden="true" /></Button></div>
      <Disclosure summary="Computer requirements"><ModelHardwareFit memory={options.model.memory_requirements} targets={target ? [target] : []} headingLevel={3} /></Disclosure>
    </> : <p role="status" className="muted">Checking this computer…</p>)}
    {stage === 1 && <>
      <p className="muted">JSONL, JSON or CSV · up to 1,000 examples, 16 MiB. Use chat <code>messages</code>, <code>prompt</code>/<code>response</code> pairs or a <code>text</code> column.</p>
      <div className="guided-form">
        <TextControl label="Dataset name" value={name} onChange={e => { setName(e.target.value); setResumeJson(''); setError(''); }} maxLength={200} required disabled={busy} />
        <FileInput label="Training file" accept=".jsonl,.json,.csv" aria-describedby={inspection ? 'training-dataset-validation' : undefined} aria-invalid={validation && !validation.can_prepare ? true : undefined} onChange={e => changeFile(e.target.files?.[0] ?? null)} disabled={busy} hint="Varied examples teach more than repeated copies." />
      </div>
      {inspection && <TrainingSourcePreview inspection={inspection} mapping={mapping} disabled={busy} onChange={value => { setMappingJson(JSON.stringify(value)); setError(''); }} />}
      {inspection && <DatasetValidationWarnings report={validation} checking={checkingValidation} />}
      <Disclosure summary="Format help" variant="quiet"><p className="muted">One JSON object per line, or a CSV with prompt and response columns. An optional <code>group_id</code> keeps related examples in the same split.</p><pre>{'{"messages":[{"role":"user","content":"How do I reset my password?"},{"role":"assistant","content":"Open Settings, then choose Reset password."}]}'}</pre><p className="muted">Chat examples train on assistant responses only. Examples over 128 model tokens are refused with a repair message.</p></Disclosure>
      <div className="guided-actions" data-ui="actions"><Button type="button" disabled={busy} onClick={() => setStage(0)}>Back</Button><Button type="button" onClick={() => void inspectFile()} disabled={busy || !file || !name.trim() || !inspection || !!mappingProblem || checkingValidation || !validation?.can_prepare}>Preview dataset</Button><Button type="button" variant="quiet" disabled={busy} onClick={() => { setName('Support request classification'); changeFile(new File([classificationStarterCsv()], 'support-classification.csv', { type: 'text/csv' })); }}>Use classification starter</Button></div>
      {preview && <div className="guided-preview"><h3>{preview.row_count} examples ready</h3><p className="muted">{preview.dropped_count} duplicate examples removed. Training learns {preview.objectives.join(' and ')}. Related examples stay in the same split.</p><SplitCounts splits={preview.split_counts} />{preview.warnings.map(w => <Notice tone="caution" as="p" key={w}>{w}</Notice>)}<TrainingSampleRows rows={preview.sample_rows || preview.examples.map(blocks => ({ blocks }))} caption="First validated examples, with the exact input and target text used for training." /><div data-ui="actions"><Button type="button" variant="primary" size="lg" onClick={() => void publish()} disabled={busy}>Use this dataset <ArrowRight size={16} aria-hidden="true" /></Button></div></div>}
    </>}
    {stage === 2 && <>
      <KeyValueList items={[{ label: 'Model', value: modelLabel || 'Choose a model' }, { label: 'Dataset', value: datasetLabel || 'Choose a dataset' }]} />
      {datasetRevisionId && <Disclosure summary="Review prepared examples" variant="quiet"><PreparedDatasetPreview revisionId={datasetRevisionId} token={token} /></Disclosure>}
      <div className="guided-actions" data-ui="actions"><Button type="button" disabled={busy} onClick={() => setStage(0)}>Change model</Button><Button type="button" disabled={busy} onClick={() => { setStage(1); setPreview(null); }}>Change dataset</Button></div>
    </>}
  </section>;
}

function SplitCounts({ splits }: { splits: Record<string, number> }) { return <dl className="guided-splits">{[['train', 'Training'], ['validation', 'Validation'], ['test', 'Test']].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{splits[key] ?? 0}</dd></div>)}</dl>; }
