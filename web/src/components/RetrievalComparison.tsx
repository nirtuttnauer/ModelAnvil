import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Identifier } from './Identifier';
import { TextContent } from './DataInspector';
import { Button, Checkbox, Disclosure, KeyValueList, Notice, RecordTable, Section, Select, TextControl } from './ui';
interface Index { index_id: string; knowledge_base: number; revision_no: number; adapter_type?: string }
interface Span { chunk_id: string; document_id: string; title: string; span: string; text: string }
interface Trace { trace_id: string; query: string; mode: string; latency_ms: number; results: { chunk_id: string; text: string; metadata: { document_title?: string; span?: string } }[] }
interface Report { run_id: string; valid: boolean; reason?: string; index_id?: string; index_revision?: number; mode?: string; qrels_version?: string; qrels_digest?: string; cutoff?: number; unit?: string; metrics?: Record<string, number | null>; coverage?: { queries_total: number; queries_with_positive_qrels: number }; queries?: { query_id: string; query?: string }[] }
interface Projection { available: boolean; reason?: string; method?: string; settings?: { limits?: string; explained_variance_ratio?: number[]; numpy_version?: string }; points?: { chunk_id: string; title: string; x: number; y: number }[]; table?: { chunk_id: string; document_title: string; x: number; y: number; cluster_name: string; text_preview: string }[] }

export function RetrievalComparison({ token, index, indexes, query, cutoff, mode = 'lexical', refreshKey, knowledgeBaseId, onSourcesChanged }: {
  token: string; index: Index; indexes: Index[]; query: string; cutoff: number; mode?: string; refreshKey: number; knowledgeBaseId?: string; onSourcesChanged: () => void;
}) {
  const [pool, setPool] = useState<Span[]>([]), [next, setNext] = useState<number | null>(null), [total, setTotal] = useState(0);
  const [relevant, setRelevant] = useState<string[]>([]), [version, setVersion] = useState('judgments-v1'), [baseline, setBaseline] = useState('');
  const [reports, setReports] = useState<Report[]>([]), [traces, setTraces] = useState<Trace[]>([]), [projection, setProjection] = useState<Projection | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  const path = `/api/v1/index-versions/${index.index_id}`;
  useEffect(() => {
    const c = new AbortController(); setError('');
    Promise.all([apiRequest<{ results: Span[]; next_offset: number | null; total: number }>(`${path}/judgment-pool/`, token, { signal: c.signal }),
      apiRequest<{ results: Report[] }>(`${path}/comparisons/`, token, { signal: c.signal }),
      apiRequest<{ results: Trace[] }>(`${path}/traces/`, token, { signal: c.signal }),
      apiRequest<Projection>(`${path}/projection/`, token, { signal: c.signal }).catch(e => ({ available: false, reason: errorMessage(e) }))])
      .then(([p, r, t, projection]) => { if (!c.signal.aborted) { setPool(p.results); setNext(p.next_offset); setTotal(p.total); setReports(r.results); setTraces(t.results); setProjection(projection); } })
      .catch(e => { if (!c.signal.aborted) { setError(errorMessage(e)); setPool([]); setReports([]); setTraces([]); setProjection(null); } });
    return () => c.abort();
  }, [token, path, refreshKey, retry]);
  async function evaluate(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const data = await apiRequest<{ results: Report[] }>(`${path}/comparisons/`, token, { method: 'POST', body: JSON.stringify({ qrels_version: version.trim(), top_k: cutoff, modes: [mode], cases: [{ query_id: 'query-1', query: query.trim(), qrels: Object.fromEntries(relevant.map(id => [id, 1])) }], ...(baseline ? { baseline_index_id: baseline } : {}) }) });
      setReports(data.results); setRetry(v => v + 1);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function loadMore() {
    if (next === null) return; setBusy(true); setError('');
    try { const data = await apiRequest<{ results: Span[]; next_offset: number | null }>(`${path}/judgment-pool/?offset=${next}`, token); setPool(rows => [...rows, ...data.results]); setNext(data.next_offset); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function revoke(source: Span) {
    if (!knowledgeBaseId || !window.confirm(`Revoke access to “${source.title}”? Its spans will become unavailable in old indexes, traces, reports and projections.`)) return;
    setBusy(true); setError('');
    try { await apiRequest(`/api/v1/knowledge-bases/${knowledgeBaseId}/revoke-document/`, token, { method: 'POST', body: JSON.stringify({ document_id: source.document_id }) }); setRelevant([]); setPool([]); setReports([]); setTraces([]); setProjection(null); onSourcesChanged(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function project() {
    setBusy(true); setError('');
    try { setProjection(await apiRequest<Projection>(`${path}/projection/`, token, { method: 'POST', body: '{}' })); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const points = projection?.points || [];
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const minX = Math.min(...xs), minY = Math.min(...ys), rangeX = Math.max(...xs) - minX || 1, rangeY = Math.max(...ys) - minY || 1;
  return <Section title="Versioned retrieval comparison" description="Mark the source spans relevant to the query above. Unmarked retrieved spans count as nonrelevant; no positive judgments means N/A. Reports pin the query, index, judgment version, cutoff and exact judgment digest."
    actions={<Button type="button" disabled={busy} onClick={() => setRetry(v => v + 1)}>Refresh retrieval evidence</Button>}>
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    <Disclosure summary={`Judge source spans · ${relevant.length} relevant · ${pool.length} of ${total} loaded`} variant="quiet">
      {pool.map(source => <div key={source.chunk_id} data-ui="form">
        <Checkbox label={`Relevant: ${source.title} · span ${source.span}`} disabled={busy} checked={relevant.includes(source.chunk_id)} onChange={e => setRelevant(ids => e.target.checked ? [...ids, source.chunk_id] : ids.filter(id => id !== source.chunk_id))} />
        <TextContent text={source.text} />
        <div data-ui="actions"><span className="muted">Chunk <Identifier value={source.chunk_id} label="Judged chunk ID" display="code" /></span>{knowledgeBaseId && <Button type="button" size="sm" disabled={busy} onClick={() => void revoke(source)}>Revoke source access</Button>}</div>
      </div>)}
      {next !== null && <div data-ui="actions"><Button type="button" disabled={busy} onClick={() => void loadMore()}>Load more source spans</Button></div>}
    </Disclosure>
    <form data-ui="form" onSubmit={evaluate}>
      <div data-ui="field-grid">
        <TextControl label="Judgment version" required disabled={busy} maxLength={128} value={version} onChange={e => setVersion(e.target.value)} />
        <Select label="Baseline index (optional)" disabled={busy} value={baseline} onChange={e => setBaseline(e.target.value)}><option value="">Current index only</option>{indexes.filter(i => i.index_id !== index.index_id && i.knowledge_base === index.knowledge_base).map(i => <option key={i.index_id} value={i.index_id}>Revision {i.revision_no} · {i.adapter_type || 'registered'} retrieval</option>)}</Select>
      </div>
      <div data-ui="actions"><Button variant="primary" disabled={busy || !query.trim() || !version.trim()}>Evaluate pinned retrieval</Button><span className="muted">{mode} · cutoff {cutoff} · {relevant.length} positive judgments</span></div>
    </form>
    {reports.map((report, number) => <Disclosure key={report.run_id} variant="plain" open summary={report.valid ? `Retrieval report ${reports.length - number} · r${report.index_revision} · ${report.qrels_version} · ${report.mode}` : `Retrieval report ${reports.length - number} · unavailable`}>
      {!report.valid ? <Notice tone="caution">{report.reason}</Notice> : <>
        <KeyValueList columns={2} items={[
          { label: 'Report', value: <Identifier value={report.run_id} label="Retrieval report ID" display="code" /> },
          { label: 'Compared index', value: <Identifier value={report.index_id} label="Compared index ID" display="code" /> },
          { label: 'Judgment digest', value: <Identifier value={report.qrels_digest} label="Judgment digest" display="code" /> },
          { label: 'Cutoff', value: `${report.cutoff} · unit ${report.unit}` },
          { label: 'Judged coverage', value: `${report.coverage?.queries_with_positive_qrels} / ${report.coverage?.queries_total} queries` },
          { label: 'Query snapshot', value: report.queries?.map(q => q.query || q.query_id).join('; ') },
        ]} />
        <KeyValueList columns={2} items={Object.entries(report.metrics || {}).map(([key, value]) => ({ key, label: key, value: value === null ? 'N/A · no positive judgments' : value.toFixed(4) }))} />
      </>}
      {!report.valid && <p className="muted">Report <Identifier value={report.run_id} label="Retrieval report ID" display="code" /></p>}
    </Disclosure>)}
    <Section level={3} title="Recorded retrieval traces" description="Recent 50 traces. Sources are rechecked when loaded. No reranker or generator was executed.">
      {traces.map(trace => <Disclosure key={trace.trace_id} variant="plain" summary={`${trace.query} · ${trace.mode} · ${trace.latency_ms.toFixed(2)} ms`}>
        <p className="muted">Trace <Identifier value={trace.trace_id} label="Trace ID" display="code" /></p>
        {trace.results.map(row => <article key={row.chunk_id}><strong>{row.metadata.document_title} · span {row.metadata.span}</strong><TextContent text={row.text} /></article>)}
      </Disclosure>)}
    </Section>
    <Section level={3} title="Measured embedding projection" actions={<Button type="button" disabled={busy || index.adapter_type === 'lexical'} onClick={() => void project()}>Build measured PCA</Button>}>
      {!projection?.available ? <Notice>{projection?.reason || 'A measured projection requires compatible actual embedding vectors. Lexical indexing does not generate them.'}</Notice> : <>
        <p className="muted">{projection.method?.toUpperCase()} · {points.length} points. {projection.settings?.limits}</p>
        <svg viewBox="0 0 600 320" role="img" aria-label="Measured PCA of authorized source vectors" style={{ width: '100%', maxHeight: 400 }}><title>Measured PCA. Exact coordinates and source text are in the table below.</title><path d="M40 20V280H580" fill="none" stroke="var(--border)" /><text x="280" y="310" fill="var(--text)">Principal component 1</text><text transform="translate(16 190) rotate(-90)" fill="var(--text)">Principal component 2</text>{points.map(point => <circle key={point.chunk_id} cx={50 + (point.x - minX) / rangeX * 510} cy={265 - (point.y - minY) / rangeY * 230} r="5" fill="var(--primary)" tabIndex={0} aria-label={`${point.title}: PC1 ${point.x}, PC2 ${point.y}`}><title>{point.title}: {point.x}, {point.y}</title></circle>)}</svg>
        <div className="table-scroll" tabIndex={0}><RecordTable><caption>Measured projection table · same authorized points</caption><thead><tr><th>Source</th><th>PC1</th><th>PC2</th><th>Original-vector cluster</th><th>Source preview</th></tr></thead><tbody>{projection.table?.map(row => <tr key={row.chunk_id}><td>{row.document_title}</td><td>{row.x}</td><td>{row.y}</td><td>{row.cluster_name}</td><td>{row.text_preview}</td></tr>)}</tbody></RecordTable></div>
      </>}
    </Section>
  </Section>;
}
