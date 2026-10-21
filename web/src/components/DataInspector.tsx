import { Identifier, isOpaqueIdentifier } from './Identifier';
import { Badge } from './ui';
import { Check, Minus, FileText } from 'lucide-react';
import { structuredResponse } from '../api/response-content';
import './data-inspector.css';

export function dataLabel(key: string) {
  const words = key.replace(/([a-z\d])([A-Z])/g, '$1 $2').replace(/[_.-]+/g, ' ').trim();
  return words.replace(/\b(id|uuid|cpu|gpu|api|sha256|spdx|url|uri|gb|mb|pii)\b/gi, word => word.toUpperCase())
    .replace(/^\w/, letter => letter.toUpperCase());
}

export function TextContent({ text, label }: { text: string | null | undefined; label?: string }) {
  return <div className="readable-text" role={label ? 'region' : undefined} aria-label={label}>
    {text === null || text === undefined
      ? <span className="data-empty">Not reported</span>
      : text === '' ? <span className="data-empty">Empty text</span>
      : <p>{text}</p>}
  </div>;
}

export function ResponseContent({ text }: { text: string | null | undefined }) {
  const structured = structuredResponse(text);
  return structured ? <DataInspector value={structured} /> : <TextContent text={text} />;
}

export function DataValue({ value, label = 'ID', identifier = false }: { value: unknown; label?: string; identifier?: boolean }) {
  if (identifier && (typeof value === 'string' || typeof value === 'number') && String(value)) return <Identifier value={value} label={label} />;
  if (value === null || value === undefined) return <span className="data-empty">Not reported</span>;
  if (typeof value === 'boolean') return <span className="data-boolean">
    {value ? <Check size={14} aria-hidden="true" /> : <Minus size={14} aria-hidden="true" />}{value ? 'Yes' : 'No'}
  </span>;
  if (typeof value === 'number') {
    if (Number.isFinite(value) && Number(value.toPrecision(10)) !== value) return <details className="data-identifier"><summary><span className="data-number">{Number(value.toPrecision(10))}</span><span>Show exact value</span></summary><code>{String(value)}</code></details>;
    return <span className="data-number">{String(value)}</span>;
  }
  if (typeof value === 'string') {
    if (!value) return <span className="data-empty">Empty text</span>;
    if (isOpaqueIdentifier(value)) return <Identifier value={value} label={label} />;
    return <span className="data-string">{value}</span>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="data-empty">No items recorded</span>;
    return <ol className="data-records">{value.map((item, index) => <li key={index}>
      <span className="data-record-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
      <div><DataValue value={item} /></div>
    </li>)}</ol>;
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value);
    if (!entries.length) return <span className="data-empty">No fields recorded</span>;
    return <div className="data-fields">
      <dl className="data-facts">{entries.filter(([, item]) => item === null || typeof item !== 'object').map(([key, item]) =>
        <div key={key}><dt title={key}>{dataLabel(key)}</dt><dd><DataValue value={item} label={dataLabel(key)} identifier={/(^id$|_(?:id|uuid|digest)$)/i.test(key)} /></dd></div>
      )}</dl>
      {entries.filter(([, item]) => item !== null && typeof item === 'object').map(([key, item]) =>
        <section className="data-group" key={key} aria-label={dataLabel(key)}><div className="data-group-heading" title={key}><strong>{dataLabel(key)}</strong>{Array.isArray(item) && <span className="data-count">{item.length} {item.length === 1 ? 'item' : 'items'}</span>}</div><DataValue value={item} /></section>
      )}
    </div>;
  }
  return <span className="data-string">{String(value)}</span>;
}

export function DataInspector({ value, title, description }: { value: unknown; title?: string; description?: string }) {
  return <section className="data-inspector" aria-label={title}>
    {title && <header className="data-inspector-heading"><span className="data-inspector-icon"><FileText size={18} aria-hidden="true" /></span><div><h3>{title}</h3>{description && <p>{description}</p>}</div></header>}
    <DataValue value={value} />
  </section>;
}

interface EvaluationResult {
  case_id: string;
  slice_name: string;
  passed: boolean;
  score: number | null;
  input_prompt: string;
  candidate_output: string;
  expected_output: string;
  baseline_output?: string | null;
  baseline_score?: number | null;
  failure_reason: string;
}

export function EvaluationCase({ result }: { result: EvaluationResult }) {
  return <details className="evaluation-case">
    <summary><strong>{result.case_id}</strong><Badge className={`state state-${result.passed ? 'completed' : 'failed'}`}>{result.passed ? 'Pass' : 'Fail'}</Badge><span className="evaluation-case-slice">{result.slice_name}</span><span className="evaluation-case-score">Score {result.score ?? 'not reported'}</span></summary>
    <div className="evaluation-case-body">
      <section className="response-card response-input"><h3>Input prompt</h3><TextContent text={result.input_prompt} /></section>
      <div className="response-comparison">
        <section className="response-card"><h3>Candidate response</h3><ResponseContent text={result.candidate_output} /></section>
        <section className="response-card"><h3>Expected response</h3><ResponseContent text={result.expected_output} /></section>
      </div>
      {result.baseline_output !== undefined && <section className="response-card"><h3>Baseline response <span>Score {result.baseline_score ?? 'not reported'}</span></h3><ResponseContent text={result.baseline_output} /></section>}
      {result.failure_reason && <div className="response-failure"><strong>Failure reason</strong><TextContent text={result.failure_reason} /></div>}
    </div>
  </details>;
}
