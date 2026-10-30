import { useEffect, useRef, useState } from 'react';
import './research-chat.css';
import { Button, Disclosure, FileInput, MultilineControl, Notice, Section, Select, TextControl } from '../components/ui';
import { EmptyState, Feedback } from '../components/Feedback';
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
    <Section title="Research session" description="Ask your local model about attached documents and reviewed web pages. Inspect the exact evidence and retained conversation memory.">
      {error && <Notice role="alert" tone="error">{error}</Notice>}
      {loading ? <Feedback state="loading" title="Loading document sessions…" /> : <>
        <div data-ui="field-grid">
          <Select label="Saved session" disabled={busy} value={session?.session_id || ''} onChange={e => { if (e.target.value) void load(e.target.value); else setSession(null); }}><option value="">New session</option>{catalog.sessions.map(s => <option key={s.session_id} value={s.session_id}>{s.title}</option>)}</Select>
          {!session && <><TextControl label="Session title" value={title} maxLength={180} disabled={busy} onChange={e => setTitle(e.target.value)} />
            <Select label="Local answer model" value={model} disabled={busy} onChange={e => setModel(e.target.value)}><option value="">Choose a provisioned model</option>{catalog.models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></>}
        </div>
        {!session && <><p className="muted">The pinned CPU RAG decoder must be provisioned locally. Each session keeps its own documents and history within the active project.</p>
          <div data-ui="actions"><Button type="button" variant="primary" disabled={busy || !model || !title.trim()} onClick={() => void mutate('/api/v1/research-sessions/', { title, model_version: model })}>Create session</Button></div></>}
        {session && <div data-ui="actions"><Button type="button" disabled={busy} onClick={() => void load(session.session_id)}>Reload session</Button><Button type="button" disabled={busy} onClick={() => setSession(null)}>New session</Button></div>}
      </>}
    </Section>
    {!loading && session && <>
      {!session.evidence_available && <Notice tone="caution">Saved evidence or its model is unavailable. Previous answers and memory are withheld. Clear memory to continue with currently accessible sources.</Notice>}
      <Section title="Sources" description="PDF and DOCX use the qualified text extractor. Code and text stay as UTF-8 source. Images require a completed qualified OCR job; audio transcription is unavailable here.">
        <FileInput label="Attach document or code (up to 1 MiB)" disabled={busy} accept=".pdf,.docx,.txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.csv,.rs,.go,.java,.c,.cpp,.h,.css,.html,.sql,.sh,.yaml,.yml" onChange={e => {
          const file = e.target.files?.[0]; e.target.value = ''; if (!file) return;
          const data = new FormData(); data.set('file', file); data.set('revision_no', String(session.revision_no)); void mutate(`/api/v1/research-sessions/${session.session_id}/attach/`, data);
        }} />
        <Disclosure summary="Use an OCR result" variant="quiet">
          <div data-ui="field-grid"><TextControl label="Completed OCR request ID" value={ocr} disabled={busy} onChange={e => setOcr(e.target.value)} /></div>
          <div data-ui="actions"><Button type="button" disabled={busy || !ocr.trim()} onClick={() => void action('attach-ocr', { request_id: ocr.trim() })}>Attach qualified OCR text</Button></div>
        </Disclosure>
        <Disclosure summary="Research reviewed web pages" variant="quiet">
          <p className="muted">Fetch one or two explicit HTTPS page URLs. Their origins must be approved in Privacy settings. Each step allows 20 seconds and 1 MiB per page. Search runs locally over fetched text; private questions and history are not sent to a search provider.</p>
          <MultilineControl label="Page URLs (one per line)" value={urls} disabled={busy} onChange={e => setUrls(e.target.value)} />
          <div data-ui="actions"><Button type="button" disabled={busy || !urls.trim()} onClick={() => void action('fetch', { urls: urls.split('\n').map(s => s.trim()).filter(Boolean) })}>Fetch pages</Button></div>
        </Disclosure>
        {session.documents.length ? <ul className="research-sources">{session.documents.map(d => <li key={d.document_id}><strong>{d.title}</strong>{d.available ? <><TextContent text={d.source_uri} /><Disclosure summary="Source provenance" variant="quiet"><DataInspector value={d.metadata} /></Disclosure><div data-ui="actions"><Button type="button" size="sm" disabled={busy} onClick={() => void action('remove-source', { document_id: d.document_id })}>Remove source</Button></div></> : <p className="muted">Excluded from retrieval and citations.</p>}</li>)}</ul>
          : <EmptyState title="No sources yet" description="Attach a document or fetch a reviewed page." />}
        {!!session.research_steps.length && <Disclosure summary="Actual fetch evidence" variant="quiet"><DataInspector value={session.research_steps} /></Disclosure>}
      </Section>
      <Section title="Ask with evidence" description="Lexical search selects up to three source spans. Local CPU generation reserves up to 128 output tokens. Citation checks validate source membership; answer correctness still needs review.">
        {session.turns.map((t, i) => <article key={i} className="research-turn" aria-label={`Research turn ${i + 1}`}><p><strong>You:</strong> {t.question}</p>
          {t.generation.answer ? <ChatResponseContent text={t.generation.answer} /> : <p className="muted">Answer withheld: {t.generation.status.replaceAll('_', ' ')}.</p>}
          {!!t.generation.citations.length && <ul className="research-citations">{t.generation.citations.map(c => <li key={c.chunk_id}>[{c.label}] {c.title} — characters {c.span_start}–{c.span_end}<TextContent text={c.source_uri} /></li>)}</ul>}
          <Disclosure summary="Measured generation and context" variant="quiet"><DataInspector value={t.generation.receipt} /></Disclosure></article>)}
        <form data-ui="form" onSubmit={e => { e.preventDefault(); void action('ask', { question, max_tokens: maxTokens, memory_tokens: memoryTokens }); }}>
          <MultilineControl label="Question" value={question} maxLength={8192} disabled={busy} onChange={e => setQuestion(e.target.value)} />
          <div data-ui="field-grid"><TextControl label="Output token limit" type="number" min={1} max={128} value={maxTokens} disabled={busy} onChange={e => setMaxTokens(Number(e.target.value))} /><TextControl label="History token limit" type="number" min={64} max={512} value={memoryTokens} disabled={busy} onChange={e => setMemoryTokens(Number(e.target.value))} /></div>
          <div data-ui="actions"><Button type="submit" variant="primary" disabled={busy || !question.trim() || !session.evidence_available || !session.documents.some(d => d.available)}>{busy ? 'Working…' : 'Search sources & answer'}</Button></div>
        </form>
        <Disclosure summary="Retained conversation memory" variant="quiet"><p className="muted">Pinned verbatim compaction retains recent text and bounded earlier prefixes. Inspect measured tokens and omissions. Source authorization is checked again before reuse.</p><DataInspector value={session.memory} /></Disclosure>
        <div data-ui="actions"><Button type="button" disabled={busy || !session.turns.length && session.evidence_available} onClick={() => void action('clear-memory')}>Clear conversation memory</Button></div>
      </Section>
    </>}
  </div>;
}
