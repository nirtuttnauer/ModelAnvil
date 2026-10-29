import { Identifier } from '../components/Identifier';
import { Button, Checkbox, Dialog, Disclosure, FileInput, MultilineControl, Notice, Section, SegmentedControl, Select } from '../components/ui';
import { Feedback } from '../components/Feedback';
import { DataInspector, TextContent } from '../components/DataInspector';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { questionInput, queueSpecialist, uploadOcrImage, type SpecialistCatalog, type SpecialistKind, type SpecialistResult } from '../api/specialists';
import { LayoutRegions, SpecialistJobs } from '../components/SpecialistJobs';
import './ml-pages.css';
import './specialists.css';

export function SpecialistsPage({ token, refreshKey }: { token: string; refreshKey?: number }) {
  const acquireFormId = useId();
  const [catalog, setCatalog] = useState<SpecialistCatalog | null>(null);
  const [pools, setPools] = useState<{ id: number; name: string }[]>([]);
  const [datasets, setDatasets] = useState<{ dataset_id: string; name: string }[]>([]);
  const [pool, setPool] = useState('');
  const [kind, setKind] = useState<SpecialistKind>('ocr');
  const [licenseAccepted, setLicenseAccepted] = useState(false);
  const [acquireOpen, setAcquireOpen] = useState(false);
  const [ocrModel, setOcrModel] = useState('');
  const [layaModel, setLayaModel] = useState('');
  const [device, setDevice] = useState('mps:0');
  const [file, setFile] = useState<File | null>(null);
  const [maxTokens, setMaxTokens] = useState(512);
  const [layoutModel, setLayoutModel] = useState('');
  const [durable, setDurable] = useState(true);
  const [jobPool, setJobPool] = useState('');
  const [budget, setBudget] = useState('');
  const [policies, setPolicies] = useState<{ policy_id: string; name: string }[]>([]);
  const [selectedJob, setSelectedJob] = useState('');
  const [state, setState] = useState('I was charged twice for March. Please refund the duplicate charge.');
  const [questionType, setQuestionType] = useState<'choice' | 'score' | 'noul'>('choice');
  const [instructions, setInstructions] = useState('Which department should handle this ticket?');
  const [options, setOptions] = useState('billing: Invoices, payments and refunds\ntechnical: Bugs, outages and system errors\nsales: Pricing and new contracts');
  const [ocrResult, setOcrResult] = useState<SpecialistResult | null>(null);
  const [layaResult, setLayaResult] = useState<SpecialistResult | null>(null);
  const [dataset, setDataset] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const controller = useRef<AbortController | null>(null);
  const lock = useRef(false);

  useEffect(() => {
    setSelectedJob(''); setOcrResult(null); setLayaResult(null); setReviewed(false);
    setJobPool(''); setBudget('');
  }, [token]);

  useEffect(() => {
    if (!token.trim()) return;
    const c = new AbortController();
    void Promise.all([
      apiRequest<SpecialistCatalog>('/api/v1/specialists/', token, { signal: c.signal }),
      apiPage<{ id: number; name: string }>('/api/v1/worker-pools/', token, c.signal),
      apiPage<{ dataset_id: string; name: string }>('/api/v1/datasets/', token, c.signal),
      apiPage<{ policy_id: string; name: string; unit: string; enabled: boolean; currency: string }>('/api/v1/budget-policies/', token, c.signal),
    ]).then(([models, poolPage, datasetPage, policyPage]) => {
      if (c.signal.aborted) return;
      setCatalog(models); setPools(poolPage.results); setDatasets(datasetPage.results);
      setPolicies(policyPage.results.filter(p => p.enabled && p.unit === 'specialist_attempts' && !p.currency));
      setOcrModel(models.models.find(m => m.kind === 'ocr')?.id || '');
      setLayaModel(models.models.find(m => m.kind === 'laya')?.id || '');
    }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => { c.abort(); controller.current?.abort(); };
  }, [token, refreshKey]);

  async function run(label: string, operation: (signal: AbortSignal) => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const c = new AbortController(); controller.current = c;
    setBusy(label); setError(''); setNotice('');
    try { await operation(c.signal); }
    catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
    finally { if (!c.signal.aborted) setBusy(''); lock.current = false; }
  }

  function acquire(e: FormEvent) {
    e.preventDefault();
    if (!catalog || !licenseAccepted) return;
    void run('Queuing model acquisition', async signal => {
      const r = await apiRequest<{ job_id: string }>('/api/v1/specialists/acquire/', token, { method: 'POST', signal,
        body: JSON.stringify({ kind, name: `${catalog.catalog[kind].name} ${Date.now()}`, pool: Number(pool), accepted_license: catalog.catalog[kind].license, idempotency_key: crypto.randomUUID() }) });
      if (!signal.aborted) { setAcquireOpen(false); setNotice(`Acquisition queued. Follow job ${r.job_id} in Workflows, then refresh to select the model.`); }
    });
  }

  function recognize(e: FormEvent) {
    e.preventDefault();
    if (!file || !ocrModel) return;
    setOcrResult(null); setReviewed(false);
    void run(durable ? 'Queuing document job' : 'Recognizing document', async signal => {
      const uploaded = await uploadOcrImage(token, file, signal);
      const request = { model: ocrModel, image_artifact: uploaded.artifact_id, device: 'mlx:0', max_tokens: maxTokens,
        ...(layoutModel ? { layout_model: layoutModel } : {}) };
      if (durable) {
        const queued = await queueSpecialist(token, 'ocr', request, jobPool, budget, signal);
        if (!signal.aborted) { setSelectedJob(queued.request_id); setNotice(`Document job queued: ${queued.job_id}.`); }
        return;
      }
      const result = await apiRequest<SpecialistResult>('/api/v1/specialists/ocr/', token, {
        method: 'POST', signal, body: JSON.stringify(request),
      });
      if (!signal.aborted) setOcrResult(result);
    });
  }

  function decide(e: FormEvent) {
    e.preventDefault(); setLayaResult(null);
    void run('Evaluating decision', async signal => {
      const question = questionInput(questionType, instructions, options);
      const request = { model: layaModel, device, state, questions: { answer: question } };
      if (durable) {
        const queued = await queueSpecialist(token, 'laya', request, jobPool, budget, signal);
        if (!signal.aborted) { setSelectedJob(queued.request_id); setNotice(`Decision job queued: ${queued.job_id}.`); }
        return;
      }
      const result = await apiRequest<SpecialistResult>('/api/v1/specialists/decisions/', token, {
        method: 'POST', signal, body: JSON.stringify(request),
      });
      if (!signal.aborted) setLayaResult(result);
    });
  }

  const disabled = Boolean(busy) || !token.trim();
  const missingAdmission = durable && (!jobPool || !budget);
  const entry = catalog?.catalog[kind];
  return <div className="ml-page">
    <Section title="Document text and decisions" description="Read image text with GLM-OCR and ask Laya structured questions. Every run records its model, device, input digest and usage." actions={<Button type="button" variant="primary" disabled={disabled || !catalog} onClick={() => setAcquireOpen(true)}>Add specialist model</Button>}>
      {error && <Notice tone="error" role="alert">{error}</Notice>}
      {notice && <Notice tone="success" role="status">{notice}</Notice>}
      {busy && <p role="status" className="muted">{busy}… Local inference allows up to 120 seconds.</p>}
      {!catalog && !error && token.trim() && <Feedback state="loading" title="Loading specialist models…" />}
      <Disclosure summary="Execution" variant="quiet">
        <fieldset disabled={disabled} className="specialist-fields">
          <SegmentedControl label="Execution" value={durable ? 'worker' : 'preview'} onChange={value => setDurable(value === 'worker')} options={[{ value: 'worker', label: 'Durable worker job' }, { value: 'preview', label: 'Synchronous preview' }]} />
          {durable && <div data-ui="field-grid">
            <Select label="Specialist worker pool" value={jobPool} onChange={e => setJobPool(e.target.value)}><option value="">Select a pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
            <Select label="Attempt quota" value={budget} onChange={e => setBudget(e.target.value)}><option value="">Select a specialist attempt quota</option>{policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name}</option>)}</Select>
          </div>}
          {durable && <p className="muted">Three attempts are reserved per job. Create a specialist_attempts policy in Budgets and start a specialist worker for the device.</p>}
        </fieldset>
      </Disclosure>
      <div className="ml-charts">
        <section className="ml-run" aria-label="Document text recognition">
          <h3>Document text recognition</h3>
          <p className="muted">PNG, JPEG or a scanned PDF of up to 5 pages and 8 MiB. Apple Metal is required.</p>
          <form onSubmit={recognize}>
            <fieldset disabled={disabled} className="specialist-fields">
              <Select label="OCR model" required value={ocrModel} onChange={e => { setOcrModel(e.target.value); setOcrResult(null); }}><option value="">Select an acquired model</option>{catalog?.models.filter(m => m.kind === 'ocr').map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</Select>
              <FileInput label="Document source" accept="image/png,image/jpeg,application/pdf" required onChange={e => { setFile(e.target.files?.[0] || null); setOcrResult(null); setReviewed(false); }} />
              <Select label="Layout extraction" value={layoutModel} onChange={e => { setLayoutModel(e.target.value); setOcrResult(null); setReviewed(false); }}><option value="">Whole page text</option>{catalog?.models.filter(m => m.kind === 'layout').map(m => <option key={m.id} value={m.id}>{m.name} · ordered regions</option>)}</Select>
              <Select label="Maximum output tokens per page or region" value={String(maxTokens)} onChange={e => { setMaxTokens(Number(e.target.value)); setOcrResult(null); setReviewed(false); }} options={['256', '512', '1024'].map(value => ({ value, label: value }))} />
              <div data-ui="actions"><Button variant="primary" disabled={disabled || missingAdmission || !file || !ocrModel}>{durable ? 'Queue document job' : 'Recognize text'}</Button></div>
            </fieldset>
          </form>
          {ocrResult && <div className="specialist-result">
            <h4>Extracted text</h4>
            <TextContent text={ocrResult.text} label="Extracted text" />
            <LayoutRegions result={ocrResult} />
            <p className="muted">{ocrResult.elapsed_seconds.toFixed(2)} seconds · {ocrResult.device}</p>
            <Select label="Publish to dataset" disabled={disabled} value={dataset} onChange={e => setDataset(e.target.value)}><option value="">Select an existing dataset</option>{datasets.map(d => <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>)}</Select>
            <Checkbox label="I have reviewed the extracted text." disabled={disabled} checked={reviewed} onChange={e => setReviewed(e.target.checked)} />
            <div data-ui="actions"><Button type="button" disabled={disabled || !reviewed || !dataset} onClick={() => void run('Publishing reviewed OCR text', async signal => {
              const r = await apiRequest<{ revision_id: string; row_count: number }>(`/api/v1/datasets/${dataset}/prepare/`, token, { method: 'POST', signal,
                body: JSON.stringify({ input_artifact_id: ocrResult.output_artifact?.artifact_id,
                  chunk_characters: ocrResult.pages?.some(p => p.regions?.length) ? null : 128, detect: true, dedup: true }) });
              if (!signal.aborted) setNotice(`Published revision ${r.revision_id} with ${r.row_count} rows. Source privacy and deduplication checks completed.`);
            })}>Publish with source checks</Button></div>
            <Disclosure summary="Request, usage and source evidence" variant="quiet"><DataInspector value={ocrResult} /></Disclosure>
          </div>}
        </section>
        <section className="ml-run" aria-label="Laya decisions">
          <h3>Laya decisions</h3>
          <p className="muted">Choice, ordered score or yes/no over English text. Results are suggestions for review.</p>
          <form onSubmit={decide}>
            <fieldset disabled={disabled} className="specialist-fields">
              <Select label="Laya model" required value={layaModel} onChange={e => { setLayaModel(e.target.value); setLayaResult(null); }}><option value="">Select an acquired model</option>{catalog?.models.filter(m => m.kind === 'laya').map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</Select>
              <Select label="Decision device" value={device} onChange={e => { setDevice(e.target.value); setLayaResult(null); }} options={[{ value: 'mps:0', label: 'Apple GPU' }, { value: 'cpu', label: 'CPU' }]} />
              <MultilineControl label="State text" required rows={4} value={state} onChange={e => { setState(e.target.value); setLayaResult(null); }} />
              <Select label="Answer type" value={questionType} onChange={e => { setQuestionType(e.target.value as typeof questionType); setLayaResult(null); }} options={[{ value: 'choice', label: 'Choice' }, { value: 'score', label: 'Ordered score' }, { value: 'noul', label: 'Yes/no probability' }]} />
              <MultilineControl label="Question" required rows={2} value={instructions} onChange={e => { setInstructions(e.target.value); setLayaResult(null); }} />
              {questionType !== 'noul' && <MultilineControl label={questionType === 'score' ? 'Ordered levels, lowest first' : 'Options, label: description'} hint="2–8 options, one per line." required rows={4} value={options} onChange={e => { setOptions(e.target.value); setLayaResult(null); }} />}
              <div data-ui="actions"><Button variant="primary" disabled={disabled || missingAdmission || !layaModel}>{durable ? 'Queue decision job' : 'Evaluate decision'}</Button></div>
            </fieldset>
          </form>
          {layaResult && <div className="specialist-result">
            <h4>Typed answer</h4>
            <DataInspector value={layaResult.answers} />
            <p className="muted">{layaResult.elapsed_seconds.toFixed(2)} seconds · {layaResult.device} · No text generation</p>
            <Disclosure summary="Request, usage and model evidence" variant="quiet"><DataInspector value={layaResult} /></Disclosure>
          </div>}
        </section>
      </div>
      <Disclosure summary="Recent specialist jobs" variant="card" open={!!selectedJob}>
        <SpecialistJobs token={token} selected={selectedJob} onSelect={setSelectedJob} onResult={(result, resultKind) => {
          if (resultKind === 'laya') setLayaResult(result); else { setOcrResult(result); setReviewed(false); }
        }} />
      </Disclosure>
    </Section>
    <Dialog title="Add specialist model" description="Download a pinned specialist through a model-import worker." open={acquireOpen} onClose={() => setAcquireOpen(false)}
      footer={<><Button type="button" disabled={Boolean(busy)} onClick={() => setAcquireOpen(false)}>Cancel</Button><Button form={acquireFormId} type="submit" variant="primary" disabled={disabled || !catalog || !pool || !licenseAccepted}>Download through worker</Button></>}>
      <form id={acquireFormId} data-ui="form" onSubmit={acquire}>
        <div data-ui="field-grid">
          <Select label="Specialist" value={kind} onChange={e => { setKind(e.target.value as SpecialistKind); setLicenseAccepted(false); }} options={[{ value: 'ocr', label: 'GLM-OCR' }, { value: 'laya', label: 'Laya' }, { value: 'layout', label: 'PP-DocLayoutV3' }]} />
          <Select label="Model-import pool" required value={pool} onChange={e => setPool(e.target.value)}><option value="">Select a pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
        </div>
        {entry && <p className="muted">{entry.repo_id} · {(entry.byte_size / 1024**3).toFixed(2)} GiB · {entry.license} · revision <Identifier value={entry.revision} label="Pinned repository revision" display="code" /></p>}
        <Checkbox label="I accept the displayed model license." checked={licenseAccepted} onChange={e => setLicenseAccepted(e.target.checked)} />
      </form>
    </Dialog>
  </div>;
}
