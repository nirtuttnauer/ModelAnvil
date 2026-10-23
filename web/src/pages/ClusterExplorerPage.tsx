import { RetrievalComparison } from '../components/RetrievalComparison';
import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field, MultilineField, Notice } from '../components/ui';
import { Feedback } from '../components/Feedback';
import { RetrievalEvidenceCard } from '../components/RetrievalEvidenceCard';
import { useDraft, DraftStatus } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { BarChart, ChartEmpty, ChartPanel, EventTimeline } from '../components/Charts';
import { Database, FileText, Search, Plus } from 'lucide-react';
import './data-workspace.css';
interface KB { id?: number; knowledge_base_id: string; name: string; description: string }
interface Index { source_pins?: Record<string, unknown>; adapter_type?: string; index_id: string; knowledge_base: number; revision_no: number; status: string; chunk_count: number }
interface Chunk { chunk_id: string; text: string; score: number; metadata: Record<string, unknown> }

export function ClusterExplorerPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const draft = useDraft('rag-author', { showForm: false as boolean, name: '', description: '', showImport: false as boolean, baseId: '', documentTitle: '', documentContent: '', sourceUri: '', index: '', query: '', topK: '5' });
  const [bases, setBases] = useState<KB[]>([]);
  const [indexes, setIndexes] = useState<Index[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = draft.field('index');
  const [query, setQuery] = draft.field('query');
  const [topK, setTopK] = draft.field('topK');
  const [results, setResults] = useState<Chunk[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [queried, setQueried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = draft.field('showForm');
  const [name, setName] = draft.field('name');
  const [description, setDescription] = draft.field('description');
  const [showImport, setShowImport] = draft.field('showImport');
  const [baseId, setBaseId] = draft.field('baseId');
  const [documentTitle, setDocumentTitle] = draft.field('documentTitle');
  const [documentContent, setDocumentContent] = draft.field('documentContent');
  const [sourceUri, setSourceUri] = draft.field('sourceUri');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const [evidenceRefresh, setEvidenceRefresh] = useState(0);
  const [moreAvailable, setMoreAvailable] = useState(false);
  const searchGeneration = useRef(0);
  const selected = results.find(chunk => chunk.chunk_id === selectedId) || results[0];
  const selectedIndex = indexes.find(item => item.index_id === index);

  useEffect(() => { setNotice(''); }, [token]);
  useEffect(() => {
    const controller = new AbortController();
    searchGeneration.current += 1; setResults([]); setQueried(false); setBases([]); setIndexes([]); setLoading(true); setError(null);
    Promise.all([apiPage<KB>('/api/v1/knowledge-bases/', token, controller.signal), apiPage<Index>('/api/v1/index-versions/', token, controller.signal)])
      .then(([b, i]) => { if (!controller.signal.aborted) { setBases(b.results); setIndexes(i.results); setMoreAvailable(!!b.next || !!i.next); setIndex(current => i.results.some(item => item.index_id === current) ? current : ''); } })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); searchGeneration.current += 1; };
  }, [token, refreshKey, retry]);

  async function create(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await apiRequest<KB>('/api/v1/knowledge-bases/', token, { method: 'POST', body: JSON.stringify({ name: name.trim(), description: description.trim() }) });
      setBaseId(created.knowledge_base_id); setShowImport(true); setName(''); setDescription(''); setShowForm(false); setRetry(value => value + 1); setNotice(`Knowledge base “${name.trim()}” created.`);
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function importDocument(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null); clearResults();
    try {
      const created = await apiRequest<Index>(`/api/v1/knowledge-bases/${baseId}/index/`, token, { method: 'POST', body: JSON.stringify({ documents: [{ title: documentTitle.trim(), content: documentContent, ...(sourceUri.trim() ? { source_uri: sourceUri.trim() } : {}) }] }) });
      setIndex(created.index_id); setShowImport(false); setDocumentContent(''); setRetry(value => value + 1);
      setNotice(`Index r${created.revision_no} ready · ${created.chunk_count} source-linked chunks.`);
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function readDocument(file?: File) {
    if (!file) return;
    if (file.size > 500000) { setError('Choose a text file smaller than 500 KB.'); return; }
    try { setDocumentContent(await file.text()); setDocumentTitle(file.name); setSourceUri(`upload:${file.name}`); }
    catch(e) { setError(errorMessage(e)); }
  }
  function clearResults() { searchGeneration.current += 1; setResults([]); setSelectedId(''); setQueried(false); }
  async function search(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null); clearResults();
    const generation = searchGeneration.current;
    try {
      const body = await apiRequest<{ results: Chunk[] }>(`/api/v1/index-versions/${index}/query/`, token, { method: 'POST', body: JSON.stringify({ query: query.trim(), mode: 'lexical', top_k: Number(topK) }) });
      if (generation === searchGeneration.current) { setResults(body.results); setQueried(true); setEvidenceRefresh(v => v + 1); }
    } catch(e) { if (generation === searchGeneration.current) setError(errorMessage(e)); } finally { setBusy(false); }
  }

  const knowledgeBases = <Card className="panel"><div className="panel-title"><div><h2>Knowledge bases</h2><p>Registered collections in the loaded first page.</p></div><Badge className="badge">{bases.length} LOADED</Badge></div><div className="panel-body"><div className="rag-base-grid">{bases.map(base => <article className="rag-base-card" key={base.knowledge_base_id}><Database size={20} aria-hidden="true" /><div><h3>{base.name}</h3><p className="muted">{base.description || 'No description provided.'}</p><Identifier value={base.knowledge_base_id} label="Knowledge base ID" /></div></article>)}</div>{!loading && !error && !bases.length && <p className="muted">No knowledge bases yet. Create a collection to get started.</p>}{moreAvailable && <p className="muted">Additional knowledge base or index pages exist; only the first pages are loaded.</p>}</div></Card>;
  return <div className="data-workspace rag-workspace">
    <div className="page-actions"><Button className="primary" disabled={!token.trim() || busy} onClick={() => setShowForm(value => !value)}><Plus size={16} aria-hidden="true" />{showForm ? 'Close setup' : 'New knowledge base'}</Button></div>
    <Card className="panel"><div className="panel-body">
      <ResourceState loading={loading} error={error} onRetry={() => setRetry(value => value + 1)} />
      {notice && <Notice tone="success" className="notice success" role="status">{notice}</Notice>}
      {showForm && <form className="form-grid" onSubmit={create}><DraftStatus draft={draft} disabled={busy} /><label>Knowledge base name<Field required value={name} onChange={event => setName(event.target.value)} maxLength={200} /></label><label>Description<Field value={description} onChange={event => setDescription(event.target.value)} /></label><Button className="primary" disabled={busy || !name.trim()}>Create knowledge base</Button></form>}
      <Button className="secondary" disabled={!token.trim() || busy || !bases.length} onClick={() => setShowImport(value => !value)}>{showImport ? 'Close document import' : 'Import documents & build index'}</Button>
      {showImport && <form className="form-grid" onSubmit={importDocument}><DraftStatus draft={draft} disabled={busy} />
        <label>Knowledge base<select required value={baseId} onChange={event => setBaseId(event.target.value)}><option value="">Choose a collection</option>{bases.map(base => <option key={base.knowledge_base_id} value={base.knowledge_base_id}>{base.name}</option>)}</select></label>
        <label>Text file (optional)<input type="file" accept=".txt,.md,.csv,text/plain,text/markdown,text/csv" onChange={event => { void readDocument(event.target.files?.[0]); }} /></label>
        <label>Document title<Field required maxLength={255} value={documentTitle} onChange={event => setDocumentTitle(event.target.value)} /></label>
        <label>Source identifier (optional)<Field maxLength={512} value={sourceUri} onChange={event => setSourceUri(event.target.value)} placeholder="Stable identifier for future revisions" /></label>
        <label className="full-width">Document text<MultilineField required rows={8} maxLength={500000} value={documentContent} onChange={event => setDocumentContent(event.target.value)} /></label>
        <p className="muted full-width">Text is indexed locally with exact source spans and content hashes. Reusing a source identifier creates a document revision. Each index keeps its original chunk membership.</p>
        <Button className="primary" disabled={busy || !baseId || !documentTitle.trim() || !documentContent.trim()}>{busy ? 'Building index…' : 'Build lexical index'}</Button>
      </form>}
      {knowledgeBases}
      <form className="rag-query-form" onSubmit={search}><DraftStatus draft={draft} disabled={busy} /><label className="rag-query">Query<div className="data-search"><Search size={17} aria-hidden="true" /><Field required value={query} onChange={event => { setQuery(event.target.value); clearResults(); }} placeholder="Search indexed knowledge chunks…" /></div></label><label>Results to retrieve<select value={topK} onChange={event => { setTopK(event.target.value); clearResults(); }}>{[5, 10, 20].map(count => <option value={count} key={count}>{count} chunks</option>)}</select></label><label className="rag-index">Index version<select required value={index} onChange={event => { setIndex(event.target.value); clearResults(); }}><option value="">Choose a registered index</option>{indexes.map(item => <option key={item.index_id} value={item.index_id}>KB record #{item.knowledge_base} · r{item.revision_no} · {item.status} · {item.chunk_count} chunks</option>)}</select></label><Button className="primary" disabled={busy || loading || !index || !query.trim()}>{busy ? 'Querying…' : 'Run query'}</Button></form>
      {selectedIndex && <div className="data-query-context"><Badge className="badge">LEXICAL SEARCH</Badge><span>Revision {selectedIndex.revision_no}</span><span>{selectedIndex.chunk_count.toLocaleString()} indexed chunks</span><Badge className={`state state-${selectedIndex.status}`}>{selectedIndex.status}</Badge></div>}
      {selectedIndex?.source_pins && <details><summary>Frozen source and chunking receipt</summary><DataInspector value={selectedIndex.source_pins} /></details>}
      {!loading && !indexes.length && <p className="muted">No registered indexes. Import document text to build your first searchable index.</p>}
    </div></Card>
    <div className="visualization-grid equal"><ChartPanel title="Retrieval ranking" description="Exact lexical scores returned by the index. These are not embedding similarities."><BarChart data={results.map((chunk, rank) => ({ label: `Chunk ${rank + 1}`, value: chunk.score, color: selected?.chunk_id === chunk.chunk_id ? 0 : 4 }))} unit="Lexical score" emptyMessage={queried ? 'No document chunks matched this query.' : 'Select an index and run a query to compare retrieved chunk scores.'} /></ChartPanel>
      <Card className="panel data-result-panel"><div className="panel-title"><div><h2>Retrieved chunks</h2><p>{queried ? `${results.length} returned · requested top ${topK}` : 'Results stay linked to the current query and index.'}</p></div><Badge className="badge">LEXICAL</Badge></div><div className="rag-results">{results.map((chunk, rank) => <RetrievalEvidenceCard key={chunk.chunk_id} chunk={chunk} rank={rank + 1} query={query} selected={selected?.chunk_id === chunk.chunk_id} onSelect={() => setSelectedId(chunk.chunk_id)} />)}{!results.length && <Feedback state={busy ? 'loading' : 'empty'} title={busy ? 'Retrieving chunks…' : queried ? 'No matches found' : 'Explore your knowledge'} description={queried ? 'Try more specific terms or choose a different index.' : 'Run a lexical query to inspect its ranked source evidence.'} />}</div></Card></div>
    <div className="visualization-grid equal"><Card className="panel"><div className="panel-title"><div><h2>Chunk inspector</h2><p>Full source text and exact metadata.</p></div><FileText size={19} aria-hidden="true" /></div><div className="panel-body">{selected ? <><Identifier value={selected.chunk_id} label="Chunk ID" /><div className="rag-chunk-text preserve-lines">{selected.text}</div><details><summary>Chunk metadata</summary><DataInspector value={selected.metadata} /></details></> : <ChartEmpty message="Retrieved chunks will be available for source inspection after a query." />}</div></Card>
      <ChartPanel title="Retrieval trace" description="Current query and registered index; only retrieval is connected."><EventTimeline events={[{ label: 'Query', detail: query.trim() || 'Enter your search terms.', status: query.trim() ? 'ready' : 'pending' }, { label: 'Retrieve', detail: selectedIndex ? `Lexical search · index revision ${selectedIndex.revision_no}${queried ? ` · ${results.length} chunks returned` : ''}` : 'Select a registered index.', status: queried ? 'completed' : 'pending' }, { label: 'Assemble context & answer', detail: 'Context assembly and answer generation are not connected in this workbench.', status: 'pending' }]} /><p className="muted">Saved traces and measured projection provenance are below. Ranking uses recorded lexical scores.</p></ChartPanel></div>
    {selectedIndex && <RetrievalComparison key={`${token}:${selectedIndex.index_id}`} token={token} index={selectedIndex} indexes={indexes} query={query} cutoff={Number(topK)} refreshKey={refreshKey + evidenceRefresh} knowledgeBaseId={bases.find(base => base.id === selectedIndex.knowledge_base)?.knowledge_base_id} onSourcesChanged={() => { clearResults(); setRetry(v => v + 1); setEvidenceRefresh(v => v + 1); }} />}
  </div>;
}
