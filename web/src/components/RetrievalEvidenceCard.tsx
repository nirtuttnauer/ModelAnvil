import { Button } from './ui';
import { DataInspector } from './DataInspector';
import { VersionChip } from './ResourcePicker';
import { highlightTerms } from './workbench-data';
import './workbench-components.css';

export function RetrievalEvidenceCard({ chunk, rank, query, selected, onSelect }: {
  chunk: { chunk_id: string; text: string; score: number; metadata: Record<string, unknown> };
  rank: number; query: string; selected?: boolean; onSelect?: () => void;
}) {
  const title = typeof chunk.metadata.document_title === 'string' && chunk.metadata.document_title ? chunk.metadata.document_title
    : typeof chunk.metadata.title === 'string' && chunk.metadata.title ? chunk.metadata.title : `Chunk ${rank}`;
  const source = typeof chunk.metadata.source_uri === 'string' ? chunk.metadata.source_uri : null;
  const scoreLabel = chunk.metadata.channel === 'dense' ? 'Cosine similarity' : chunk.metadata.channel === 'hybrid' ? 'Fused rank score' : 'Lexical score';
  const excerpt = chunk.text.length > 280 ? chunk.text.slice(0, 280) + '…' : chunk.text;
  function highlighted(text: string) { return highlightTerms(text, query).map((part, index) => part.matched ? <mark key={index}>{part.text}</mark> : part.text); }
  return <article className={`retrieval-evidence-card ${selected ? 'evidence-selected' : ''}`} aria-label={`Retrieved source ${rank}`}>
    <div className="wb-row"><span className="wb-revision">Rank {rank}</span><span className="wb-number">{scoreLabel}: {Number.isFinite(chunk.score) ? chunk.score.toLocaleString(undefined, { maximumFractionDigits: 4 }) : 'Not reported'}</span></div>
    <h3>{title}</h3>{source && <p className="wb-muted evidence-source">Source: {source}</p>}
    <p className="evidence-excerpt">{highlighted(excerpt)}</p>
    {onSelect && <Button type="button" aria-pressed={!!selected} onClick={onSelect}>Inspect source {rank}</Button>}
    <details><summary>Full source text</summary><div className="evidence-full-text">{highlighted(chunk.text)}</div></details>
    <details><summary>Source metadata and identity</summary><VersionChip name={title} id={chunk.chunk_id} /><DataInspector value={chunk.metadata} /></details>
  </article>;
}
