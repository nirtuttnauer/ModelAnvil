import { Button, Card, Field, Notice } from './ui';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle, Cpu, LoaderCircle } from 'lucide-react';
import { apiRequest, errorMessage } from '../api/client';
import { prepareUploadedDataset, type PrepareUploadedDatasetOptions } from '../api/datasets';
import { readGuidedValue, type GuidedInputs, type GuidedOptions, type GuidedPreview, type GuidedRevision } from '../api/guided-training';
import { useDraft } from './Draft';
import type { TrainingConfiguration } from '../api/training-workspace';
import { ModelHardwareFit } from './ModelHardwareFit';
import { DatasetValidationWarnings, PreparedDatasetPreview, TrainingSourcePreview, TrainingSampleRows } from './TrainingDatasetPreview';
import { columnMappingError, type TrainingColumnMapping, type TrainingDatasetValidation, type TrainingSourceInspection } from '../api/training-dataset';
import { memoryBytes, type HardwareTarget } from '../api/model-hardware';
import './guided-training.css';

const stages = ['Model', 'Dataset', 'Review'];

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
  return <Card className="guided-training panel" aria-labelledby="guided-title">
    <header className="guided-header"><div><span className="eyebrow">YOUR FIRST FINE-TUNE</span><h2 id="guided-title">Choose your model and data</h2><p>Choose a model, add your examples, and review your training plan.</p></div><Cpu aria-hidden="true" size={28} /></header>
    <ol className="guided-stages" aria-label="Fine-tuning progress">{stages.map((label, index) => <li key={label} aria-current={stage === index ? 'step' : undefined}><span>{index < stage ? <CheckCircle size={18} aria-hidden="true" /> : index + 1}</span>{label}</li>)}</ol>
    <div className="guided-body" aria-busy={busy}>
      <h3 ref={heading} tabIndex={-1}>{['Choose your pretrained model', 'Add your training examples', 'Model and dataset selected'][stage]}</h3>
      {error && <Notice tone="error" className="notice error" role="alert">{error}<Button type="button" disabled={busy} onClick={() => { setError(''); if (stage === 1 && file && !inspection) setInspectionRetry(value => value + 1); else setRetry(v => v + 1); }}>Try again</Button></Notice>}
      {busy && <p role="status"><LoaderCircle size={16} aria-hidden="true" /> {progress || 'Working…'}</p>}
      {stage === 0 && <>
        {options ? <><div className="guided-model"><strong>{options.model.name}</strong><span className="guided-tag">Recommended for this computer</span><p>{options.model.description}</p><p>{options.model.parameters >= 1000000000 ? '1.7 billion' : '135 million'} parameters · {options.model.license} · up to {options.model.max_tokens} tokens per example</p><a href="https://www.apache.org/licenses/LICENSE-2.0" target="_blank" rel="noreferrer">Model license</a></div><p role="status">{options.compute.message}</p><p>The matching tokenizer, training settings and local compute are configured automatically.</p><Button type="button" className="primary" onClick={() => void prepareModel()} disabled={busy || !options.compute.available}>Use this model <ArrowRight size={16} aria-hidden="true" /></Button><details><summary>Computer requirements</summary><ModelHardwareFit memory={options.model.memory_requirements} targets={target ? [target] : []} /></details></> : <p role="status">Checking this computer…</p>}
      </>}
      {stage === 1 && <>
        {options && !options.compute.available && <Notice tone="error" role="alert">{options.compute.message}</Notice>}
        <p>Upload JSONL, JSON or CSV. Use chat <code>messages</code>, <code>prompt</code>/<code>response</code> pairs, or a <code>text</code> column. Up to 1,000 examples, 16 MiB total.</p>
        <p>Include different ways people ask each question, paired with the exact answers you want. Repeated copies add less information than varied examples.</p>
        <div className="guided-form"><label>Dataset name<Field value={name} onChange={e => { setName(e.target.value); setResumeJson(''); setError(''); }} maxLength={200} required disabled={busy} /></label><label>Training file<input type="file" aria-describedby={inspection ? "training-dataset-validation" : undefined} aria-invalid={validation && !validation.can_prepare ? true : undefined} accept=".jsonl,.json,.csv" onChange={e => changeFile(e.target.files?.[0] ?? null)} disabled={busy || !options?.compute.available} /></label></div>
        {inspection && <TrainingSourcePreview inspection={inspection} mapping={mapping} disabled={busy} onChange={value => { setMappingJson(JSON.stringify(value)); setError(''); }} />}
        {inspection && <DatasetValidationWarnings report={validation} checking={checkingValidation} />}
        <details><summary>See the expected file format</summary><p>One JSON object per line, or a CSV with prompt and response columns. Optional <code>group_id</code> keeps related examples together.</p><pre>{'{"messages":[{"role":"user","content":"How do I reset my password?"},{"role":"assistant","content":"Open Settings, then choose Reset password."}]}'}</pre><p>Chat examples train on assistant responses only. Plain text trains on all text tokens. Examples exceeding 128 model tokens are refused with a repair message.</p></details>
        <div className="guided-actions"><Button type="button" disabled={busy} onClick={() => setStage(0)}>Back</Button><Button type="button" onClick={() => void inspectFile()} disabled={busy || !options?.compute.available || !file || !name.trim() || !inspection || !!mappingProblem || checkingValidation || !validation?.can_prepare}>Preview dataset</Button></div>
        {preview && <div className="guided-preview"><h4>{preview.row_count} examples ready</h4><p>{preview.dropped_count} duplicate examples removed. Training learns {preview.objectives.join(' and ')}.</p><SplitCounts splits={preview.split_counts} /><p>Repeated prompts and related examples stay in the same split.</p>{preview.warnings.map(w => <Notice as="p" className="notice" key={w}>{w}</Notice>)}<TrainingSampleRows rows={preview.sample_rows || preview.examples.map(blocks => ({ blocks }))} caption="First validated examples, with the exact input and target text used for training." /><Button type="button" className="primary" onClick={() => void publish()} disabled={busy}>Use this dataset <ArrowRight size={16} aria-hidden="true" /></Button></div>}
      </>}
      {stage === 2 && <>
        <dl className="guided-review"><div><dt>Starting model</dt><dd>{modelLabel || 'Choose a model'}</dd></div><div><dt>Your dataset</dt><dd>{datasetLabel || 'Choose a dataset'}</dd></div></dl>
        {datasetRevisionId && <details><summary>Review prepared examples</summary><PreparedDatasetPreview revisionId={datasetRevisionId} token={token} /></details>}
        <p>Review the training plan and run summary below. Advanced settings edit this same configuration.</p>
        <div className="guided-actions"><Button type="button" disabled={busy} onClick={() => setStage(0)}>Change model</Button><Button type="button" disabled={busy} onClick={() => { setStage(1); setPreview(null); }}>Change dataset</Button></div>
      </>}

    </div>
  </Card>;
}

function SplitCounts({ splits }: { splits: Record<string, number> }) { return <dl className="guided-splits">{[['train', 'Training'], ['validation', 'Validation'], ['test', 'Test']].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{splits[key] ?? 0}</dd></div>)}</dl>; }
