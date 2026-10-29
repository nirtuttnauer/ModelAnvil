import { useEffect, useRef, useState, type FormEvent } from 'react';
import { apiPage, apiRequest, authHeaders, errorMessage, getActiveProjectId } from '../api/client';
import { statusLabel } from '../api/status';
import { Button, Disclosure, KeyValueList, MultilineControl, Notice, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { DataInspector } from '../components/DataInspector';
import './ml-pages.css';
import './specialists.css';

type Model = { id: string; name: string; trained: boolean };
type Job = { request_id: string; job_id: string; status: string; desired_action?: string; error?: string;
  result?: { report: { duration_seconds: number; frames: number; sample_rate: number }; [key: string]: unknown } };

export function AudioPage({ token, refreshKey }: { token: string; refreshKey?: number }) {
  const [models, setModels] = useState<Model[]>([]);
  const [pools, setPools] = useState<{ id: number; name: string }[]>([]);
  const [policies, setPolicies] = useState<{ policy_id: string; name: string }[]>([]);
  const [model, setModel] = useState(''), [pool, setPool] = useState(''), [budget, setBudget] = useState('');
  const [text, setText] = useState('Hello world.'), [seed, setSeed] = useState(42), [seconds, setSeconds] = useState(6);
  const [jobs, setJobs] = useState<Job[]>([]), [selected, setSelected] = useState(''), [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [audio, setAudio] = useState('');
  const pending = useRef(false);
  useEffect(() => {
    const c = new AbortController();
    void Promise.all([
      apiRequest<{ models: Model[] }>('/api/v1/audio/', token, { signal: c.signal }),
      apiPage<{ id: number; name: string }>('/api/v1/worker-pools/', token, c.signal),
      apiPage<{ policy_id: string; name: string; unit: string; enabled: boolean; currency: string }>('/api/v1/budget-policies/', token, c.signal),
    ]).then(([catalog, p, b]) => {
      if (c.signal.aborted) return;
      setModels(catalog.models); setModel(catalog.models[0]?.id || ''); setPools(p.results);
      setPolicies(b.results.filter(v => v.enabled && v.unit === 'audio_samples' && !v.currency));
    }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => c.abort();
  }, [token, refreshKey]);
  useEffect(() => {
    const c = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const list = await apiRequest<Job[]>('/api/v1/audio/jobs/', token, { signal: c.signal });
        const detail = selected ? await apiRequest<Job>(`/api/v1/audio/jobs/${selected}/`, token, { signal: c.signal }) : null;
        if (!c.signal.aborted) { setJobs(list); setJob(detail); }
      } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
      if (!c.signal.aborted) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { c.abort(); clearTimeout(timer); };
  }, [token, selected, refreshKey]);
  useEffect(() => {
    const c = new AbortController(); let url = ''; setAudio('');
    if (job?.status === 'succeeded') {
      const headers = authHeaders(token), project = getActiveProjectId();
      if (project) headers.set('X-Project-ID', project);
      void fetch(`/api/v1/audio/jobs/${job.request_id}/audio/`, { headers, signal: c.signal, redirect: 'error' }).then(async r => {
        if (!r.ok || !r.headers.get('Content-Type')?.startsWith('audio/wav')) throw new Error('Speech download failed. Refresh to verify the output again.');
        const blob = await r.blob(); if (blob.size > 200000) throw new Error('Speech output exceeds its size limit.');
        if (!c.signal.aborted) { url = URL.createObjectURL(blob); setAudio(url); }
      }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    }
    return () => { c.abort(); if (url) URL.revokeObjectURL(url); };
  }, [token, job?.request_id, job?.status]);
  async function submit(e: FormEvent) {
    e.preventDefault(); if (pending.current) return; pending.current = true; setBusy(true); setError('');
    try {
      const queued = await apiRequest<Job>('/api/v1/audio/jobs/', token, { method: 'POST', body: JSON.stringify({ model, text, seed,
        max_seconds: seconds, pool: Number(pool), budget_policy: budget, idempotency_key: crypto.randomUUID() }) });
      setSelected(queued.request_id); setJob(queued);
    } catch (e) { setError(errorMessage(e)); }
    finally { pending.current = false; setBusy(false); }
  }
  const cancelable = job ? ['queued', 'running', 'interrupted'].includes(job.status) : false;
  return <div className="ml-page">
    <Section title="Speech generation" description="Generate English speech with the pinned SpeechT5 model, audio processor and vocoder.">
      {error && <Notice tone="error" role="alert">{error}</Notice>}
      <Notice tone="info">CPU speech uses fixed published demo conditioning. Human quality and speaker fidelity need separate review. ASR and voice cloning are not qualified.</Notice>
      {!models.length && <Notice tone="caution">No verified speech model is available. Import the bounded SpeechT5 profile with the operator setup command, then refresh.</Notice>}
      <form data-ui="form" onSubmit={submit}>
        <fieldset disabled={busy || !models.length} className="specialist-fields">
          <div data-ui="field-grid">
            <Select label="Speech model" required value={model} onChange={e => setModel(e.target.value)}><option value="">Select a model</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}{m.trained ? ' · trained draft' : ' · base'}</option>)}</Select>
            <Select label="Worker pool" required value={pool} onChange={e => setPool(e.target.value)}><option value="">Select a CPU speech pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
            <Select label="Audio quota" required value={budget} onChange={e => setBudget(e.target.value)}><option value="">Select an audio_samples policy</option>{policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name}</option>)}</Select>
            <TextControl label="Maximum seconds" required type="number" min={1} max={6} step={1} value={seconds} onChange={e => setSeconds(Number(e.target.value))} />
            <TextControl label="Seed" required type="number" min={0} max={2147483647} step={1} value={seed} onChange={e => setSeed(Number(e.target.value))} />
            <div data-span="full"><MultilineControl label="Text" required maxLength={96} rows={3} value={text} onChange={e => setText(e.target.value)}
              hint="Up to 96 characters and 6 seconds. Quota reserves three bounded attempts; lost attempts use their sample ceiling. A length limit or missing WAV fails the job." /></div>
          </div>
          <div data-ui="actions"><Button variant="primary" disabled={busy || !model || !pool || !budget}>{busy ? 'Queuing speech…' : 'Generate speech'}</Button></div>
        </fieldset>
      </form>
    </Section>
    <Section title="Speech jobs" description="Follow a queued job, play its verified output and inspect the generation provenance.">
      <div data-ui="field-grid">
        <Select label="Job" value={selected} onChange={e => { setSelected(e.target.value); setJob(null); }}><option value="">Select a job</option>{jobs.map((j, index) => <option key={j.request_id} value={j.request_id}>Speech job {index + 1} · {statusLabel(j.status)}</option>)}</Select>
      </div>
      {job && <div aria-live="polite" data-ui="form">
        <div data-ui="actions"><StatusBadge status={job.status} />{job.status === 'running' && <span className="muted">Generating bounded audio</span>}</div>
        {job.error && <Notice tone="error">{job.error}</Notice>}
        {cancelable && <div data-ui="actions"><Button type="button" disabled={busy || job.desired_action === 'cancel'} onClick={() => {
          setBusy(true); void apiRequest(`/api/v1/audio/jobs/${job.request_id}/cancel/`, token, { method: 'POST' }).catch(e => setError(errorMessage(e))).finally(() => setBusy(false));
        }}>Cancel speech</Button></div>}
        {job.result && <>
          <KeyValueList columns={2} items={[
            { label: 'Duration', value: `${job.result.report.duration_seconds.toFixed(2)} seconds` },
            { label: 'Sample rate', value: `${job.result.report.sample_rate.toLocaleString()} Hz mono PCM16` },
            { label: 'Samples', value: job.result.report.frames.toLocaleString() },
          ]} />
          {audio && <><audio controls preload="metadata" src={audio} aria-label="Generated speech" /><p><a href={audio} download="speech.wav">Download WAV</a></p></>}
          <Disclosure summary="Model, processor and generation provenance" variant="quiet"><DataInspector value={job.result} /></Disclosure>
        </>}
      </div>}
    </Section>
  </div>;
}
