import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { BarChart, ChartEmpty, ChartPanel, EventTimeline } from '../components/Charts';
import { Database, FileText, Search, Plus } from 'lucide-react';
import './data-workspace.css';
interface KB { knowledge_base_id: string; name: string; description: string }
interface Index { index_id: string; knowledge_base: number; revision_no: number; status: string; chunk_count: number }
interface Chunk { chunk_id: string; text: string; score: number; metadata: Record<string, unknown> }

export function ClusterExplorerPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const [bases, setBases] = useState<KB[]>([]);
  const [indexes, setIndexes] = useState<Index[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState('');
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState('5');
  const [results, setResults] = useState<Chunk[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [queried, setQueried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [baseId, setBaseId] = useState('');
  const [documentTitle, setDocumentTitle] = useState('');
  const [documentContent, setDocumentContent] = useState('');
  const [sourceUri, setSourceUri] = useState('');
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
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
      if (generation === searchGeneration.current) { setResults(body.results); setQueried(true); }
    } catch(e) { if (generation === searchGeneration.current) setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return <div className="data-workspace rag-workspace">
    <section className="panel"><div className="panel-title"><div><h2>Retrieval workbench</h2><p>Explore the document chunks returned by your query.</p></div><button className="primary" disabled={!token.trim() || busy} onClick={() => setShowForm(value => !value)}><Plus size={16} aria-hidden="true" />{showForm ? 'Close setup' : 'New knowledge base'}</button></div><div className="panel-body">
      <ResourceState loading={loading} error={error} onRetry={() => setRetry(value => value + 1)} />
      {notice && <div className="notice success" role="status">{notice}</div>}
      {showForm && <form className="form-grid" onSubmit={create}><label>Knowledge base name<input required value={name} onChange={event => setName(event.target.value)} maxLength={200} /></label><label>Description<input value={description} onChange={event => setDescription(event.target.value)} /></label><button className="primary" disabled={busy || !name.trim()}>Create knowledge base</button></form>}
      <button className="secondary" disabled={!token.trim() || busy || !bases.length} onClick={() => setShowImport(value => !value)}>{showImport ? 'Close document import' : 'Import documents & build index'}</button>
      {showImport && <form className="form-grid" onSubmit={importDocument}>
        <label>Knowledge base<select required value={baseId} onChange={event => setBaseId(event.target.value)}><option value="">Choose a collection</option>{bases.map(base => <option key={base.knowledge_base_id} value={base.knowledge_base_id}>{base.name}</option>)}</select></label>
        <label>Text file (optional)<input type="file" accept=".txt,.md,.csv,text/plain,text/markdown,text/csv" onChange={event => { void readDocument(event.target.files?.[0]); }} /></label>
        <label>Document title<input required maxLength={255} value={documentTitle} onChange={event => setDocumentTitle(event.target.value)} /></label>
        <label>Source identifier (optional)<input maxLength={512} value={sourceUri} onChange={event => setSourceUri(event.target.value)} placeholder="Stable identifier for future revisions" /></label>
        <label className="full-width">Document text<textarea required rows={8} maxLength={500000} value={documentContent} onChange={event => setDocumentContent(event.target.value)} /></label>
        <p className="muted full-width">Text is indexed locally with exact source spans and content hashes. Reusing a source identifier creates a document revision. Each index keeps its original chunk membership.</p>
        <button className="primary" disabled={busy || !baseId || !documentTitle.trim() || !documentContent.trim()}>{busy ? 'Building index…' : 'Build lexical index'}</button>
      </form>}
      <form className="rag-query-form" onSubmit={search}><label className="rag-query">Query<div className="data-search"><Search size={17} aria-hidden="true" /><input required value={query} onChange={event => { setQuery(event.target.value); clearResults(); }} placeholder="Search indexed knowledge chunks…" /></div></label><label>Top k<select value={topK} onChange={event => { setTopK(event.target.value); clearResults(); }}>{[5, 10, 20].map(count => <option value={count} key={count}>{count} chunks</option>)}</select></label><label className="rag-index">Index version<select required value={index} onChange={event => { setIndex(event.target.value); clearResults(); }}><option value="">Choose a registered index</option>{indexes.map(item => <option key={item.index_id} value={item.index_id}>KB record #{item.knowledge_base} · r{item.revision_no} · {item.status} · {item.chunk_count} chunks</option>)}</select></label><button className="primary" disabled={busy || loading || !index || !query.trim()}>{busy ? 'Querying…' : 'Run query'}</button></form>
      {selectedIndex && <div className="data-query-context"><span className="badge">LEXICAL SEARCH</span><span>Revision {selectedIndex.revision_no}</span><span>{selectedIndex.chunk_count.toLocaleString()} indexed chunks</span><span className={`state state-${selectedIndex.status}`}>{selectedIndex.status}</span></div>}
      {!loading && !indexes.length && <p className="muted">No registered indexes. Import document text to build your first searchable index.</p>}
    </div></section>
    <div className="visualization-grid equal"><ChartPanel title="Retrieval ranking" description="Exact lexical scores returned by the index. These are not embedding similarities."><BarChart data={results.map((chunk, rank) => ({ label: `#${rank + 1} · ${chunk.chunk_id.slice(0, 8)}`, value: chunk.score, color: selected?.chunk_id === chunk.chunk_id ? 0 : 4 }))} unit="Lexical score" emptyMessage={queried ? 'No document chunks matched this query.' : 'Select an index and run a query to compare retrieved chunk scores.'} /></ChartPanel>
      <section className="panel data-result-panel"><div className="panel-title"><div><h2>Retrieved chunks</h2><p>{queried ? `${results.length} returned · requested top ${topK}` : 'Results stay linked to the current query and index.'}</p></div><span className="badge">LEXICAL</span></div><div className="rag-results">{results.map((chunk, rank) => <button className={`rag-result ${selected?.chunk_id === chunk.chunk_id ? 'selected' : ''}`} key={chunk.chunk_id} aria-pressed={selected?.chunk_id === chunk.chunk_id} onClick={() => setSelectedId(chunk.chunk_id)}><span className="rag-rank">{rank + 1}</span><div><strong>Chunk {chunk.chunk_id.slice(0, 8)}</strong><p>{chunk.text}</p></div><span className="rag-score">{chunk.score.toLocaleString(undefined, { maximumFractionDigits: 4 })}<small>score</small></span></button>)}{!results.length && <div className="empty-state"><Search size={28} aria-hidden="true" /><h3>{busy ? 'Retrieving chunks…' : queried ? 'No matches found' : 'Explore your knowledge'}</h3><p>{queried ? 'Try more specific terms or choose a different index.' : 'Run a lexical query to inspect its ranked source evidence.'}</p></div>}</div></section></div>
    <div className="visualization-grid equal"><section className="panel"><div className="panel-title"><div><h2>Chunk inspector</h2><p>Full source text and exact metadata.</p></div><FileText size={19} aria-hidden="true" /></div><div className="panel-body">{selected ? <><code className="data-chunk-id">{selected.chunk_id}</code><div className="rag-chunk-text preserve-lines">{selected.text}</div><details><summary>Chunk metadata</summary><pre>{JSON.stringify(selected.metadata, null, 2)}</pre></details></> : <ChartEmpty message="Retrieved chunks will be available for source inspection after a query." />}</div></section>
      <ChartPanel title="Retrieval trace" description="Current query and registered index; only retrieval is connected."><EventTimeline events={[{ label: 'Query', detail: query.trim() || 'Enter your search terms.', status: query.trim() ? 'ready' : 'pending' }, { label: 'Retrieve', detail: selectedIndex ? `Lexical search · index ${selectedIndex.index_id.slice(0, 8)} · revision ${selectedIndex.revision_no}${queried ? ` · ${results.length} chunks returned` : ''}` : 'Select a registered index.', status: queried ? 'completed' : 'pending' }, { label: 'Assemble context & answer', detail: 'Context assembly and answer generation are not connected in this workbench.', status: 'pending' }]} /><div className="data-evidence-note"><strong>Embedding projection unavailable</strong><p>No projection coordinates are returned by this API. Ranking uses recorded lexical scores.</p></div></ChartPanel></div>
    <section className="panel"><div className="panel-title"><div><h2>Knowledge bases</h2><p>Registered collections in the loaded first page.</p></div><span className="badge">{bases.length} LOADED</span></div><div className="panel-body"><div className="rag-base-grid">{bases.map(base => <article className="rag-base-card" key={base.knowledge_base_id}><Database size={20} aria-hidden="true" /><div><h3>{base.name}</h3><p className="muted">{base.description || 'No description provided.'}</p><code>{base.knowledge_base_id.slice(0, 8)}</code></div></article>)}</div>{!loading && !error && !bases.length && <p className="muted">No knowledge bases yet. Create a collection to get started.</p>}{moreAvailable && <p className="muted">Additional knowledge base or index pages exist; only the first pages are loaded.</p>}</div></section>
  </div>;
}
