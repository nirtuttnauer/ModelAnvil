import { useEffect, useRef, useState } from 'react';
import './research-chat.css';
import { Button, Card, Field, MultilineField, Notice } from '../components/ui';
import { DataInspector, TextContent } from '../components/DataInspector';
import { ChatResponseContent } from '../components/MarkdownResponse';
import { apiRequest, errorMessage } from '../api/client';

type Citation = { label: number; title: string; source_uri: string; span_start: number; span_end: number; chunk_id: string };
type Generation = { status: string; answer: string; citations: Citation[]; receipt: Record<string, unknown> };
type Session = { session_id: string; title: string; revision_no: number; evidence_available: boolean; memory: Record<string, unknown>;
  documents: { document_id: string; title: string; available: boolean; source_uri: string; metadata: Record<string, unknown> }[];
  turns: { question: string; generation: Generation }[]; research_steps: Record<string, unknown>[] };
type Catalog = { sessions: { session_id: string; title: string }[]; models: { id: string; name: string }[] };

export function ResearchChat({ token, refreshKey }: { token: string; refreshKey?: number }) {
  const [catalog, setCatalog] = useState<Catalog>({ sessions: [], models: [] });
  const [session, setSession] = useState<Session | null>(null);
  const [model, setModel] = useState(''), [title, setTitle] = useState('Document research');
  const [question, setQuestion] = useState(''), [urls, setUrls] = useState(''), [ocr, setOcr] = useState('');
  const [maxTokens, setMaxTokens] = useState(64), [memoryTokens, setMemoryTokens] = useState(256);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const abort = useRef<AbortController | null>(null);
  useEffect(() => {
    const c = new AbortController(); abort.current?.abort(); abort.current = c;
    setSession(null); setCatalog({ sessions: [], models: [] }); setModel(''); setQuestion(''); setUrls(''); setOcr(''); setError(''); setLoading(true); setBusy(false);
    void apiRequest<Catalog>('/api/v1/research-sessions/', token, { signal: c.signal }).then(data => {
      if (!c.signal.aborted) { setCatalog(data); setModel(data.models[0]?.id || ''); }
    }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, refreshKey]);
  async function load(id: string) {
    const c = new AbortController(); abort.current?.abort(); abort.current = c; setBusy(true); setError('');
    try { const value = await apiRequest<Session>(`/api/v1/research-sessions/${id}/`, token, { signal: c.signal }); if (!c.signal.aborted) setSession(value); }
    catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
    finally { if (!c.signal.aborted) setBusy(false); }
  }
  async function mutate(path: string, data: Record<string, unknown> | FormData) {
    const c = new AbortController(); abort.current?.abort(); abort.current = c; setBusy(true); setError('');
    try {
      const value = await apiRequest<Session>(path, token, { method: 'POST', body: data instanceof FormData ? data : JSON.stringify(data), signal: c.signal });
      if (!c.signal.aborted) { setSession(value); setCatalog(current => ({ ...current, sessions: [{ session_id: value.session_id, title: value.title }, ...current.sessions.filter(s => s.session_id !== value.session_id)] })); }
    } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
    finally { if (!c.signal.aborted) setBusy(false); }
  }
  function action(name: string, data: Record<string, unknown> = {}) {
    if (session) return mutate(`/api/v1/research-sessions/${session.session_id}/${name}/`, { revision_no: session.revision_no, ...data });
  }
  return <div className="research-chat">
    <div className="workflow-page-heading"><div><h2>Documents &amp; research</h2><p>Ask your local model about attached documents and reviewed web pages. Inspect the exact evidence and retained conversation memory.</p></div></div>
    {error && <Notice role="alert" tone="error">{error}</Notice>}
    {loading ? <p role="status">Loading document sessions…</p> : <>
      <Card><h3>Research session</h3><div className="form-grid">
        <label>Saved session<select aria-label="Saved research session" disabled={busy} value={session?.session_id || ''} onChange={e => { if (e.target.value) void load(e.target.value); else setSession(null); }}><option value="">New session</option>{catalog.sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.title}</option>)}</select></label>
        {!session && <><label>Session title<Field value={title} maxLength={180} disabled={busy} onChange={e => setTitle(e.target.value)} /></label>
          <label>Local answer model<select value={model} disabled={busy} onChange={e => setModel(e.target.value)}><option value="">Choose a provisioned model</option>{catalog.models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label></>}
      </div>{!session && <><p className="hint">The pinned CPU RAG decoder must be provisioned locally. Each session keeps its own documents and history within the active project.</p><Button disabled={busy || !model || !title.trim()} onClick={() => void mutate('/api/v1/research-sessions/', { title, model_version: model })}>Create session</Button></>}
      {session && <div className="actions"><Button disabled={busy} onClick={() => void load(session.session_id)}>Reload session</Button><Button disabled={busy} onClick={() => setSession(null)}>New session</Button></div>}</Card>
      {session && <>
        {!session.evidence_available && <Notice tone="caution">Saved evidence or its model is unavailable. Previous answers and memory are withheld. Clear memory to continue with currently accessible sources.</Notice>}
        <Card><h3>Sources</h3><p className="hint">PDF and DOCX use the qualified text extractor. Code and text stay as UTF-8 source. Images require a completed qualified OCR job; audio transcription is unavailable here.</p>
          <label>Attach document or code (up to 1 MiB)<Field type="file" disabled={busy} accept=".pdf,.docx,.txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.csv,.rs,.go,.java,.c,.cpp,.h,.css,.html,.sql,.sh,.yaml,.yml" onChange={e => {
            const file = e.target.files?.[0]; e.target.value = ''; if (!file) return;
            const data = new FormData(); data.set('file', file); data.set('revision_no', String(session.revision_no)); void mutate(`/api/v1/research-sessions/${session.session_id}/attach/`, data);
          }} /></label>
          <details><summary>Use an OCR result</summary><label>Completed OCR request ID<Field value={ocr} disabled={busy} onChange={e => setOcr(e.target.value)} /></label><Button disabled={busy || !ocr.trim()} onClick={() => void action('attach-ocr', { request_id: ocr.trim() })}>Attach qualified OCR text</Button></details>
          <details><summary>Research reviewed web pages</summary><p className="hint">Fetch one or two explicit HTTPS page URLs. Their origins must be approved in Privacy settings. Each step allows 20 seconds and 1 MiB per page. Search runs locally over fetched text; private questions and history are not sent to a search provider.</p>
            <label>Page URLs (one per line)<MultilineField value={urls} disabled={busy} onChange={e => setUrls(e.target.value)} /></label>
            <Button disabled={busy || !urls.trim()} onClick={() => void action('fetch', { urls: urls.split('\n').map(s => s.trim()).filter(Boolean) })}>Fetch pages</Button>
          </details>
          {session.documents.length ? <ul>{session.documents.map(d => <li key={d.document_id}><strong>{d.title}</strong>{d.available ? <><TextContent text={d.source_uri} /><details><summary>Source provenance</summary><DataInspector value={d.metadata} /></details><Button disabled={busy} onClick={() => void action('remove-source', { document_id: d.document_id })}>Remove source</Button></> : <p>Excluded from retrieval and citations.</p>}</li>)}</ul> : <p>No sources yet. Attach a document or fetch a reviewed page.</p>}
          {!!session.research_steps.length && <details><summary>Actual fetch evidence</summary><DataInspector value={session.research_steps} /></details>}
        </Card>
        <Card><h3>Ask with evidence</h3><p className="hint">Lexical search selects up to three source spans. Local CPU generation reserves up to 128 output tokens. Citation checks validate source membership; answer correctness still needs review.</p>
          {session.turns.map((t, i) => <section key={i} aria-label={`Research turn ${i + 1}`}><p><strong>You:</strong> {t.question}</p>
            {t.generation.answer ? <ChatResponseContent text={t.generation.answer} /> : <p>Answer withheld: {t.generation.status.replaceAll('_', ' ')}.</p>}
            {!!t.generation.citations.length && <ul>{t.generation.citations.map(c => <li key={c.chunk_id}>[{c.label}] {c.title} — characters {c.span_start}–{c.span_end}<TextContent text={c.source_uri} /></li>)}</ul>}
            <details><summary>Measured generation and context</summary><DataInspector value={t.generation.receipt} /></details></section>)}
          <form onSubmit={e => { e.preventDefault(); void action('ask', { question, max_tokens: maxTokens, memory_tokens: memoryTokens }); }}>
            <label>Question<MultilineField value={question} maxLength={8192} disabled={busy} onChange={e => setQuestion(e.target.value)} /></label>
            <div className="form-grid"><label>Output token limit<Field type="number" min={1} max={128} value={maxTokens} disabled={busy} onChange={e => setMaxTokens(Number(e.target.value))} /></label><label>History token limit<Field type="number" min={64} max={512} value={memoryTokens} disabled={busy} onChange={e => setMemoryTokens(Number(e.target.value))} /></label></div>
            <Button type="submit" disabled={busy || !question.trim() || !session.evidence_available || !session.documents.some(d => d.available)}>{busy ? 'Working…' : 'Search sources & answer'}</Button>
          </form>
          <details><summary>Retained conversation memory</summary><p className="hint">Pinned verbatim compaction retains recent text and bounded earlier prefixes. Inspect measured tokens and omissions. Source authorization is checked again before reuse.</p><DataInspector value={session.memory} /></details>
          <Button disabled={busy || !session.turns.length && session.evidence_available} onClick={() => void action('clear-memory')}>Clear conversation memory</Button>
        </Card>
      </>}
    </>}
  </div>;
}
