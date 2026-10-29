import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { statusLabel } from '../api/status';
import { Badge, Button, Checkbox, Disclosure, KeyValueList, MultilineControl, Notice, Section, Select, StatusBadge, TextControl } from './ui';
import { Feedback } from './Feedback';
import { DataInspector, TextContent } from './DataInspector';
import { Identifier } from './Identifier';

interface LocalModel { model_version_id: string; model_name?: string; architecture_ref: string; metadata?: { format?: string; configuration?: { model_type?: string } } }
interface Evidence { chunk_id: string; title: string; text: string }
interface Run { run_id: string; model_version_id: string; condition: string; query: string; status: string; answer: string; raw_output: string; created_at: string;
  citations: { label: number; chunk_id: string; title: string; source_uri: string }[];
  receipt: { reason: string; generation_executed: boolean; elapsed_ms: number; budget?: { input_tokens: number; output_reserve_tokens: number; runtime_limit_tokens: number; omitted_chunk_ids: string[] }; usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number } } }
const conditions: Record<string, string> = { none: 'No retrieval', retrieved: 'Retrieved evidence', human: 'Human-supplied evidence' };

function Answer({ run }: { run: Run }) {
  return <article data-ui="form">
    <div data-ui="actions"><Badge>{conditions[run.condition]}</Badge><StatusBadge status={run.status} tone={run.status === 'answered' ? 'success' : undefined} label={run.status === 'answered' ? 'Generated locally' : undefined} /></div>
    <p><strong>Question:</strong> {run.query}</p>
    {run.answer ? <TextContent text={run.answer} /> : <Notice tone="caution">{run.status === 'validation_refusal' ? 'The model output did not pass citation validation.' : 'No answer was returned.'} Reason: {run.receipt.reason.replaceAll('_', ' ')}.</Notice>}
    {run.citations.length > 0 && <Disclosure summary="Source links" variant="quiet" open><ul>{run.citations.map(c => <li key={c.chunk_id}><strong>[{c.label}] {c.title}</strong><p className="muted">{c.source_uri} <Identifier value={c.chunk_id} label="Source chunk" /></p></li>)}</ul></Disclosure>}
    {run.receipt.usage && <p className="muted">{run.receipt.usage.prompt_tokens} input + {run.receipt.usage.completion_tokens} generated tokens · {(run.receipt.elapsed_ms / 1000).toFixed(1)} seconds</p>}
    <Disclosure summary="Model, source links and exact token budget" variant="quiet"><KeyValueList items={[{ label: 'Pinned model version', value: <Identifier value={run.model_version_id} label="Pinned model version" display="code" /> }]} /><DataInspector value={run.receipt} /></Disclosure>
    {run.raw_output && <Disclosure summary="Raw local model output" variant="quiet"><TextContent text={run.raw_output} /></Disclosure>}
  </article>;
}

export function RAGAnswers({ token, indexId, semantic, refreshKey = 0 }: { token: string; indexId: string; semantic: boolean; refreshKey?: number }) {
  const [models, setModels] = useState<LocalModel[]>([]); const [model, setModel] = useState(''); const [question, setQuestion] = useState('');
  const [condition, setCondition] = useState('retrieved'); const [mode, setMode] = useState(semantic ? 'dense' : 'lexical');
  const [maxTokens, setMaxTokens] = useState('64'); const [policy, setPolicy] = useState('fail');
  const [pool, setPool] = useState<Evidence[]>([]); const [selected, setSelected] = useState<string[]>([]); const [offset, setOffset] = useState<number | null>(null);
  const [runs, setRuns] = useState<Run[]>([]); const [result, setResult] = useState<Run | null>(null); const [error, setError] = useState('');
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [retry, setRetry] = useState(0); const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const c = new AbortController(); request.current?.abort(); setBusy(false); setLoading(true); setError(''); setResult(null); setPool([]); setSelected([]); setRuns([]);
    Promise.all([apiPage<LocalModel>('/api/v1/model-versions/', token, c.signal),
      apiRequest<{ results: Evidence[]; next_offset: number | null }>(`/api/v1/index-versions/${indexId}/judgment-pool/`, token, { signal: c.signal }),
      apiRequest<{ results: Run[] }>(`/api/v1/index-versions/${indexId}/generations/`, token, { signal: c.signal })])
      .then(([available, evidence, history]) => { if (c.signal.aborted) return;
        const supported = available.results.filter(m => m.metadata?.format === 'safetensors' && ['llama', 'qwen2', 'mistral', 'gemma', 'gemma2', 'gpt2'].includes(m.metadata?.configuration?.model_type || ''));
        setModels(supported); setModel(current => supported.some(m => m.model_version_id === current) ? current : supported[0]?.model_version_id || '');
        setPool(evidence.results); setOffset(evidence.next_offset); setRuns(history.results);
      }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => { c.abort(); request.current?.abort(); };
  }, [token, indexId, refreshKey, retry]);
  async function moreEvidence() {
    if (offset === null) return; const c = new AbortController(); request.current?.abort(); request.current = c; setBusy(true); setError('');
    try { const data = await apiRequest<{ results: Evidence[]; next_offset: number | null }>(`/api/v1/index-versions/${indexId}/judgment-pool/?offset=${offset}`, token, { signal: c.signal }); if (c.signal.aborted) return; setPool(v => [...v, ...data.results]); setOffset(data.next_offset); }
    catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); } finally { if (!c.signal.aborted) setBusy(false); }
  }
  async function generate(event: React.FormEvent) {
    event.preventDefault(); const c = new AbortController(); request.current?.abort(); request.current = c; setBusy(true); setError(''); setResult(null);
    try { const run = await apiRequest<Run>(`/api/v1/index-versions/${indexId}/generations/`, token, { method: 'POST', signal: c.signal,
      body: JSON.stringify({ query: question, model_version: model, condition, retrieval_mode: semantic ? mode : 'lexical', max_tokens: Number(maxTokens), overflow_policy: policy, ...(condition === 'human' ? { human_chunk_ids: selected } : {}) }) });
      if (!c.signal.aborted) { setResult(run); setRuns(v => [run, ...v].slice(0, 20)); }
    } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); } finally { if (!c.signal.aborted) setBusy(false); }
  }
  return <Section title="Answer with a local model" description="Compare the same question with no evidence, retrieved sources or evidence you select." actions={<Badge>Local CPU</Badge>}>
    {error && <Notice tone="error" role="alert"><span>{error}</span><Button type="button" disabled={busy} onClick={() => setRetry(v => v + 1)}>Reload model and source lists</Button></Notice>}
    {loading ? <Feedback state="loading" title="Loading available models and source history…" /> : !models.length ? <Notice>Import a supported local Safetensors text model in Models to start. The model is loaded and checked when you generate.</Notice> :
    <form data-ui="form" onSubmit={generate}>
      <div data-ui="field-grid">
        <Select label="Local model" required value={model} disabled={busy} onChange={e => setModel(e.target.value)}>{models.map(m => <option key={m.model_version_id} value={m.model_version_id}>{m.model_name || 'Local text snapshot'}</option>)}</Select>
        <Select label="Evidence condition" value={condition} disabled={busy} onChange={e => setCondition(e.target.value)} options={Object.entries(conditions).map(([value, label]) => ({ value, label }))} />
        <div data-span="full"><MultilineControl label="Question" required maxLength={8192} rows={3} value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} /></div>
        {condition === 'retrieved' && semantic && <Select label="Retrieval mode" value={mode} disabled={busy} onChange={e => setMode(e.target.value)} options={[{ value: 'dense', label: 'Semantic cosine' }, { value: 'hybrid', label: 'Hybrid rank fusion' }, { value: 'lexical', label: 'Full-text lexical' }]} />}
      </div>
      {condition === 'human' && <Section level={3} title="Select up to five source chunks">
        <div data-ui="form">{pool.map(c => <Checkbox key={c.chunk_id} label={c.title} hint={c.text.slice(0, 240)} checked={selected.includes(c.chunk_id)} disabled={busy || (!selected.includes(c.chunk_id) && selected.length >= 5)} onChange={e => { const checked = e.target.checked; setSelected(v => checked ? [...v, c.chunk_id] : v.filter(id => id !== c.chunk_id)); }} />)}</div>
        {offset !== null && <div data-ui="actions"><Button type="button" disabled={busy} onClick={() => void moreEvidence()}>Load more source chunks</Button></div>}
      </Section>}
      <Disclosure summary="Output budget and context overflow" variant="quiet">
        <div data-ui="field-grid">
          <TextControl label="Output reserve (tokens)" type="number" min="1" max="128" required value={maxTokens} disabled={busy} onChange={e => setMaxTokens(e.target.value)} />
          <Select label="Overflow policy" value={policy} disabled={busy} onChange={e => setPolicy(e.target.value)} options={[{ value: 'fail', label: 'Fail if the complete context does not fit' }, { value: 'omit_optional_evidence', label: 'Omit optional evidence, lowest rank first' }]} />
        </div>
        <p className="muted">The required question stays intact. Exact tokenizer and template counts reserve output capacity before generation. Decoding is greedy with seed 42; each run retains its settings.</p>
      </Disclosure>
      <p className="muted">Question and answer drafts stay in memory. Saved runs recheck current source and model access when opened.</p>
      <div data-ui="actions"><Button variant="primary" disabled={busy || !question.trim() || !model || (condition === 'human' && !selected.length)}>{busy ? 'Loading model and generating…' : 'Generate local answer'}</Button></div>
    </form>}
    {result && <Answer run={result} />}
    {runs.length > 0 && <Section level={3} title="Saved evidence conditions">
      {runs.map(run => <Disclosure key={run.run_id} variant="plain" summary={`${conditions[run.condition]} · ${statusLabel(run.status)} · ${new Date(run.created_at).toLocaleString()}`}><Answer run={run} /></Disclosure>)}
    </Section>}
  </Section>;
}
