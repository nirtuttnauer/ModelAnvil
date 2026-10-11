import { useEffect, useRef, useState, type FormEvent } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { questionInput, uploadOcrImage, type SpecialistCatalog, type SpecialistKind, type SpecialistResult } from '../api/specialists';
import './ml-pages.css';
import './specialists.css';

export function SpecialistsPage({ token, refreshKey }: { token: string; refreshKey?: number }) {
  const [catalog, setCatalog] = useState<SpecialistCatalog | null>(null);
  const [pools, setPools] = useState<{ id: number; name: string }[]>([]);
  const [datasets, setDatasets] = useState<{ dataset_id: string; name: string }[]>([]);
  const [pool, setPool] = useState('');
  const [kind, setKind] = useState<SpecialistKind>('ocr');
  const [licenseAccepted, setLicenseAccepted] = useState(false);
  const [ocrModel, setOcrModel] = useState('');
  const [layaModel, setLayaModel] = useState('');
  const [device, setDevice] = useState('mps:0');
  const [file, setFile] = useState<File | null>(null);
  const [maxTokens, setMaxTokens] = useState(512);
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
    if (!token.trim()) return;
    const c = new AbortController();
    void Promise.all([
      apiRequest<SpecialistCatalog>('/api/v1/specialists/', token, { signal: c.signal }),
      apiPage<{ id: number; name: string }>('/api/v1/worker-pools/', token, c.signal),
      apiPage<{ dataset_id: string; name: string }>('/api/v1/datasets/', token, c.signal),
    ]).then(([models, poolPage, datasetPage]) => {
      if (c.signal.aborted) return;
      setCatalog(models); setPools(poolPage.results); setDatasets(datasetPage.results);
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

  function recognize(e: FormEvent) {
    e.preventDefault();
    if (!file || !ocrModel) return;
    setOcrResult(null); setReviewed(false);
    void run('Recognizing image', async signal => {
      const uploaded = await uploadOcrImage(token, file, signal);
      const result = await apiRequest<SpecialistResult>('/api/v1/specialists/ocr/', token, {
        method: 'POST', signal, body: JSON.stringify({ model: ocrModel, image_artifact: uploaded.artifact_id, device: 'mlx:0', max_tokens: maxTokens }),
      });
      if (!signal.aborted) setOcrResult(result);
    });
  }

  function decide(e: FormEvent) {
    e.preventDefault(); setLayaResult(null);
    void run('Evaluating decision', async signal => {
      const question = questionInput(questionType, instructions, options);
      const result = await apiRequest<SpecialistResult>('/api/v1/specialists/decisions/', token, {
        method: 'POST', signal, body: JSON.stringify({ model: layaModel, device, state, questions: { answer: question } }),
      });
      if (!signal.aborted) setLayaResult(result);
    });
  }

  const disabled = Boolean(busy) || !token.trim();
  return <div className="ml-page specialist-page">
    {error && <div className="error-box" role="alert">{error}</div>}
    {notice && <div className="success-box" role="status">{notice}</div>}
    {busy && <p role="status">{busy}… Local inference allows up to 120 seconds.</p>}
    <section className="panel ml-main-panel">
      <div className="panel-title"><div><h2>Local OCR &amp; typed decisions</h2><p>Read image text with GLM-OCR and ask Laya structured questions. Every run records its pinned model, device, input digest and measured usage.</p></div></div>
      <div className="panel-body">
        <details><summary>Acquire a pinned specialist model</summary>
          <form className="form-grid" onSubmit={e => {
            e.preventDefault();
            if (!catalog || !licenseAccepted) return;
            void run('Queuing model acquisition', async signal => {
              const r = await apiRequest<{ job_id: string }>('/api/v1/specialists/acquire/', token, { method: 'POST', signal,
                body: JSON.stringify({ kind, name: `${catalog.catalog[kind].name} ${Date.now()}`, pool: Number(pool), accepted_license: catalog.catalog[kind].license, idempotency_key: crypto.randomUUID() }) });
              if (!signal.aborted) setNotice(`Acquisition queued. Follow job ${r.job_id} in Workflows, then Refresh to select the model.`);
            });
          }}>
            <label>Specialist<select value={kind} onChange={e => { setKind(e.target.value as SpecialistKind); setLicenseAccepted(false); }}><option value="ocr">GLM-OCR</option><option value="laya">Laya</option></select></label>
            <label>Model-import pool<select required value={pool} onChange={e => setPool(e.target.value)}><option value="">Select a pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            {catalog && <p className="full-width muted">{catalog.catalog[kind].repo_id} · {(catalog.catalog[kind].byte_size / 1024**3).toFixed(2)} GiB · {catalog.catalog[kind].license}<br /><code>{catalog.catalog[kind].revision}</code></p>}
            <label className="checkbox-label full-width"><input type="checkbox" checked={licenseAccepted} onChange={e => setLicenseAccepted(e.target.checked)} />I accept the displayed model license.</label>
            <button disabled={disabled || !catalog || !pool || !licenseAccepted}>Download through worker</button>
          </form>
        </details>
        <div className="specialist-grid">
          <section className="detail-box"><h3>Image text recognition</h3><p className="muted">PNG or JPEG, up to 8 MiB and 2 million pixels. Apple Metal is required. Review extracted text before publishing.</p>
            <form onSubmit={recognize}>
              <label>OCR model<select required value={ocrModel} onChange={e => { setOcrModel(e.target.value); setOcrResult(null); }}><option value="">Select an acquired model</option>{catalog?.models.filter(m => m.kind === 'ocr').map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
              <label>Document image<input type="file" accept="image/png,image/jpeg" required onChange={e => { setFile(e.target.files?.[0] || null); setOcrResult(null); setReviewed(false); }} /></label>
              <label>Maximum output tokens<select value={maxTokens} onChange={e => setMaxTokens(Number(e.target.value))}><option value={256}>256</option><option value={512}>512</option><option value={1024}>1024</option></select></label>
              <button disabled={disabled || !file || !ocrModel}>Recognize text</button>
            </form>
            {ocrResult && <div className="specialist-result"><h4>Extracted text</h4><pre>{ocrResult.text}</pre><p>{ocrResult.elapsed_seconds.toFixed(2)} seconds · {ocrResult.device}</p>
              <label>Publish to dataset<select value={dataset} onChange={e => setDataset(e.target.value)}><option value="">Select an existing dataset</option>{datasets.map(d => <option key={d.dataset_id} value={d.dataset_id}>{d.name}</option>)}</select></label>
              <label className="checkbox-label"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />I have reviewed the extracted text.</label>
              <button disabled={disabled || !reviewed || !dataset} onClick={() => void run('Publishing reviewed OCR text', async signal => {
                const r = await apiRequest<{ revision_id: string; row_count: number }>(`/api/v1/datasets/${dataset}/prepare/`, token, { method: 'POST', signal,
                  body: JSON.stringify({ input_artifact_id: ocrResult.output_artifact?.artifact_id, chunk_characters: 128, detect: true, dedup: true }) });
                if (!signal.aborted) setNotice(`Published revision ${r.revision_id} with ${r.row_count} rows. Source privacy and deduplication checks ran before chunking.`);
              })}>Publish with source checks</button>
              <details><summary>Request, usage &amp; source evidence</summary><pre>{JSON.stringify(ocrResult, null, 2)}</pre></details>
            </div>}
          </section>
          <section className="detail-box"><h3>Laya decisions</h3><p className="muted">Choice, ordered score or yes/no over English text. Probabilities need domain calibration. Results are suggestions for review.</p>
            <form onSubmit={decide}>
              <label>Laya model<select required value={layaModel} onChange={e => { setLayaModel(e.target.value); setLayaResult(null); }}><option value="">Select an acquired model</option>{catalog?.models.filter(m => m.kind === 'laya').map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
              <label>Decision device<select value={device} onChange={e => setDevice(e.target.value)}><option value="mps:0">Apple GPU</option><option value="cpu">CPU</option></select></label>
              <label>State text<textarea required rows={4} value={state} onChange={e => { setState(e.target.value); setLayaResult(null); }} /></label>
              <label>Answer type<select value={questionType} onChange={e => { setQuestionType(e.target.value as typeof questionType); setLayaResult(null); }}><option value="choice">Choice</option><option value="score">Ordered score</option><option value="noul">Yes/no probability</option></select></label>
              <label>Question<textarea required rows={2} value={instructions} onChange={e => { setInstructions(e.target.value); setLayaResult(null); }} /></label>
              {questionType !== 'noul' && <label>{questionType === 'score' ? 'Ordered levels, lowest first' : 'Options, label: description'}<textarea required rows={4} value={options} onChange={e => { setOptions(e.target.value); setLayaResult(null); }} /><small>2–8 options, one per line.</small></label>}
              <button disabled={disabled || !layaModel}>Evaluate decision</button>
            </form>
            {layaResult && <div className="specialist-result"><h4>Typed answer</h4><pre>{JSON.stringify(layaResult.answers, null, 2)}</pre><p>{layaResult.elapsed_seconds.toFixed(2)} seconds · {layaResult.device} · No text generation</p><details><summary>Request, usage &amp; model evidence</summary><pre>{JSON.stringify(layaResult, null, 2)}</pre></details></div>}
          </section>
        </div>
      </div>
    </section>
  </div>;
}
