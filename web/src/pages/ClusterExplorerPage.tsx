import { Identifier } from '../components/Identifier';
import { Button, Dialog, Disclosure, FileInput, KeyValueList, MultilineControl, Notice, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { RetrievalEvidenceCard } from '../components/RetrievalEvidenceCard';
import { InspectorPanel } from '../components/InspectorPanel';
import { useDraft, DraftIndicator } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
import { useEffect, useId, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { statusLabel } from '../api/status';
import { BarChart, ChartPanel } from '../components/Charts';
import './ml-pages.css';
import { EmbeddingIndexBuild } from '../components/EmbeddingIndexBuild';
import { RAGAnswers } from '../components/RAGAnswers';
import { RetrievalComparison } from '../components/RetrievalComparison';

interface KB { id?: number; knowledge_base_id: string; name: string; description: string }
interface Index { index_id: string; knowledge_base: number; revision_no: number; status: string; chunk_count: number; source_pins?: { embeddings_generated?: boolean } & Record<string, unknown> }
interface Chunk { chunk_id: string; text: string; score: number; metadata: Record<string, unknown> }

export function ClusterExplorerPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const createFormId = useId(), importFormId = useId();
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
  const [moreAvailable, setMoreAvailable] = useState(false);
  const searchGeneration = useRef(0);
  const selected = results.find(chunk => chunk.chunk_id === selectedId);
  const selectedRank = results.findIndex(chunk => chunk.chunk_id === selectedId) + 1;
  const selectedIndex = indexes.find(item => item.index_id === index);
  const [mode, setMode] = useState('lexical'); const [evidenceRefresh, setEvidenceRefresh] = useState(0);
  const [embeddingsOpen, setEmbeddingsOpen] = useState(false); const [answersOpen, setAnswersOpen] = useState(false); const [comparisonOpen, setComparisonOpen] = useState(false);
  const semantic = !!selectedIndex?.source_pins?.embeddings_generated; const queryMode = semantic ? mode : 'lexical';

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
      setBaseId(created.knowledge_base_id); setShowForm(false); setShowImport(true); setName(''); setDescription(''); setRetry(value => value + 1); setNotice(`Knowledge base “${name.trim()}” created.`);
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
      const body = await apiRequest<{ results: Chunk[] }>(`/api/v1/index-versions/${index}/query/`, token, { method: 'POST', body: JSON.stringify({ query: query.trim(), mode: queryMode, top_k: Number(topK) }) });
      if (generation === searchGeneration.current) { setResults(body.results); setSelectedId(body.results[0]?.chunk_id || ''); setQueried(true); setEvidenceRefresh(v => v + 1); }
    } catch(e) { if (generation === searchGeneration.current) setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const ready = !!token.trim();

  return <div className="ml-page">
    <Section title="Retrieval" description="Query a registered index and inspect the ranked source chunks." actions={<>
      <Button type="button" variant="primary" disabled={!ready || busy || !bases.length} onClick={() => setShowImport(true)}>Import documents & build index</Button>
      <Button type="button" disabled={!ready || busy} onClick={() => setShowForm(true)}>New knowledge base</Button>
    </>}>
      <ResourceState loading={loading && !indexes.length && !bases.length} error={error} onRetry={() => setRetry(value => value + 1)} />
      {notice && <Notice tone="success" role="status">{notice}</Notice>}
      <form data-ui="form" onSubmit={search}>
        <DraftIndicator draft={draft} disabled={busy} />
        <div data-ui="field-grid">
          <Select label="Index version" required value={index} onChange={event => { setIndex(event.target.value); clearResults(); }}>
            <option value="">Choose a registered index</option>{indexes.map(item => <option key={item.index_id} value={item.index_id}>KB record #{item.knowledge_base} · r{item.revision_no} · {statusLabel(item.status)} · {item.chunk_count} chunks</option>)}
          </Select>
          {semantic && <Select label="Search mode" value={mode} onChange={event => { setMode(event.target.value); clearResults(); }} options={[{ value: 'lexical', label: 'Lexical' }, { value: 'dense', label: 'Semantic' }, { value: 'hybrid', label: 'Hybrid' }]} />}
          <Select label="Results to retrieve" value={topK} onChange={event => { setTopK(event.target.value); clearResults(); }} options={[5, 10, 20].map(count => ({ value: String(count), label: `${count} chunks` }))} />
          <div data-span="full"><TextControl label="Query" required value={query} onChange={event => { setQuery(event.target.value); clearResults(); }} placeholder="Search indexed knowledge chunks…" /></div>
        </div>
        <div data-ui="actions">
          <Button variant="primary" disabled={busy || loading || !index || !query.trim()}>{busy ? 'Querying…' : 'Run query'}</Button>
          {selectedIndex && <span className="muted">{queryMode === 'dense' ? 'Semantic' : queryMode === 'hybrid' ? 'Hybrid' : 'Lexical'} search · revision {selectedIndex.revision_no} · {selectedIndex.chunk_count.toLocaleString()} indexed chunks</span>}
          {selectedIndex && <StatusBadge status={selectedIndex.status} />}
        </div>
      </form>
      {!loading && !indexes.length && <p className="muted">No registered indexes. Import document text to build your first searchable index.</p>}
      <div data-ui="split" data-open={selected ? '' : undefined}>
        <div className="ml-list">
          {queried && <p className="muted">{results.length} returned · requested top {topK}</p>}
          {results.map((chunk, rank) => <RetrievalEvidenceCard key={chunk.chunk_id} chunk={chunk} rank={rank + 1} query={query} selected={selected?.chunk_id === chunk.chunk_id} onSelect={() => setSelectedId(chunk.chunk_id)} />)}
          {!results.length && <EmptyState title={busy ? 'Retrieving chunks…' : queried ? 'No matches found' : 'Explore your knowledge'} description={queried ? 'Try more specific terms or choose a different index.' : 'Run a lexical query to inspect its ranked source evidence.'} />}
          <ChartPanel title="Retrieval ranking" description="Exact lexical scores returned by the index, not embedding similarities.">
            <BarChart data={results.map((chunk, rank) => ({ label: `Chunk ${rank + 1}`, value: chunk.score, color: selected?.chunk_id === chunk.chunk_id ? 0 : 4 }))} unit="Lexical score" emptyMessage={queried ? 'No document chunks matched this query.' : 'Select an index and run a query to compare retrieved chunk scores.'} />
          </ChartPanel>
        </div>
        {selected && <InspectorPanel key={selected.chunk_id} eyebrow="Source chunk" title={`Chunk ${selectedRank}`} closeLabel="Close chunk details" onClose={() => setSelectedId('')}>
          <p className="ml-prose">{selected.text}</p>
          <KeyValueList items={[{ label: 'Lexical score', value: selected.score }, { label: 'Chunk ID', value: <Identifier value={selected.chunk_id} label="Chunk ID" display="code" /> }]} />
          <Disclosure summary="Chunk metadata" variant="quiet"><DataInspector value={selected.metadata} /></Disclosure>
          <p className="ml-footnote">Only retrieval is connected. Context assembly and answer generation are not part of this workbench.</p>
        </InspectorPanel>}
      </div>
    </Section>
    <Disclosure summary="Embeddings" variant="card" open={embeddingsOpen} onToggle={event => setEmbeddingsOpen(event.currentTarget.open)}>{embeddingsOpen && <EmbeddingIndexBuild key={token} token={token} source={selectedIndex} refreshKey={refreshKey} onReady={id => { setIndex(id); clearResults(); setRetry(v => v + 1); }} />}</Disclosure>
    {selectedIndex && <Disclosure summary="Grounded answers" variant="card" open={answersOpen} onToggle={event => setAnswersOpen(event.currentTarget.open)}>{answersOpen && <RAGAnswers key={`generation:${token}:${selectedIndex.index_id}`} token={token} indexId={selectedIndex.index_id} semantic={semantic} refreshKey={refreshKey + evidenceRefresh} />}</Disclosure>}
    {selectedIndex && <Disclosure summary="Retrieval comparison" variant="card" open={comparisonOpen} onToggle={event => setComparisonOpen(event.currentTarget.open)}>{comparisonOpen && <RetrievalComparison key={`${token}:${selectedIndex.index_id}`} token={token} index={selectedIndex} indexes={indexes} query={query} cutoff={Number(topK)} mode={queryMode} refreshKey={refreshKey + evidenceRefresh} knowledgeBaseId={bases.find(base => base.id === selectedIndex.knowledge_base)?.knowledge_base_id} onSourcesChanged={() => { clearResults(); setRetry(v => v + 1); setEvidenceRefresh(v => v + 1); }} />}</Disclosure>}
    <Disclosure summary="Knowledge bases" variant="card">
      {!loading && !error && !bases.length && <p className="muted">No knowledge bases yet. Create a collection to get started.</p>}
      {bases.length > 0 && <div className="ml-cards">{bases.map(base => <article className="ml-card" key={base.knowledge_base_id}><h3>{base.name}</h3><p>{base.description || 'No description provided.'}</p><Identifier value={base.knowledge_base_id} label="Knowledge base ID" display="code" /></article>)}</div>}
      {moreAvailable && <p className="muted">More knowledge base or index pages exist; only the first pages are loaded.</p>}
    </Disclosure>
    <Dialog title="New knowledge base" description="A collection for related documents and their indexes." open={showForm} onClose={() => setShowForm(false)}
      footer={<><Button type="button" disabled={busy} onClick={() => setShowForm(false)}>Cancel</Button><Button form={createFormId} type="submit" variant="primary" disabled={busy || !name.trim()}>Create knowledge base</Button></>}>
      <form id={createFormId} data-ui="form" onSubmit={create}>
        <DraftIndicator draft={draft} disabled={busy} />
        <TextControl label="Knowledge base name" required value={name} onChange={event => setName(event.target.value)} maxLength={200} />
        <TextControl label="Description" value={description} onChange={event => setDescription(event.target.value)} />
      </form>
    </Dialog>
    <Dialog title="Import documents" description="Text is indexed locally with exact source spans and content hashes." open={showImport} onClose={() => setShowImport(false)} size="lg"
      footer={<><Button type="button" disabled={busy} onClick={() => setShowImport(false)}>Cancel</Button><Button form={importFormId} type="submit" variant="primary" disabled={busy || !baseId || !documentTitle.trim() || !documentContent.trim()}>{busy ? 'Building index…' : 'Build lexical index'}</Button></>}>
      <form id={importFormId} data-ui="form" onSubmit={importDocument}>
        <DraftIndicator draft={draft} disabled={busy} />
        <div data-ui="field-grid">
          <Select label="Knowledge base" required value={baseId} onChange={event => setBaseId(event.target.value)}><option value="">Choose a collection</option>{bases.map(base => <option key={base.knowledge_base_id} value={base.knowledge_base_id}>{base.name}</option>)}</Select>
          <FileInput label="Text file (optional)" accept=".txt,.md,.csv,text/plain,text/markdown,text/csv" onChange={event => { void readDocument(event.target.files?.[0]); }} />
          <TextControl label="Document title" required maxLength={255} value={documentTitle} onChange={event => setDocumentTitle(event.target.value)} />
          <TextControl label="Source identifier (optional)" hint="Reusing an identifier creates a document revision." maxLength={512} value={sourceUri} onChange={event => setSourceUri(event.target.value)} placeholder="Stable identifier for future revisions" />
          <div data-span="full"><MultilineControl label="Document text" required rows={8} maxLength={500000} value={documentContent} onChange={event => setDocumentContent(event.target.value)} /></div>
        </div>
      </form>
    </Dialog>
  </div>;
}
