import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartEmpty, ChartPanel, SegmentBar } from '../components/Charts';
import { FileCode2, Layers3 } from 'lucide-react';
interface Version { recipe_version_id: string; recipe: number; revision_no: number; model_limit_tokens: number; output_reserve_tokens: number; budget_policy: string; blocks: { block_key: string; content_template: string }[] }
interface Compiled { serialized_prompt: string; token_count: number; included_blocks: string[]; dropped_blocks: string[]; budget_exhausted: boolean; block_token_counts?: { block_key: string; token_count: number; truncated: boolean }[] }
export function ContextLabPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const [versions, setVersions] = useState<Version[]>([]); const [version, setVersion] = useState('');
  const [variables, setVariables] = useState('{}'); const [result, setResult] = useState<Compiled | null>(null);
  const compilation = useRef<AbortController | null>(null);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [retry, setRetry] = useState(0);
  useEffect(() => { const c = new AbortController(); compilation.current?.abort(); setResult(null); setBusy(false); setLoading(true); setError(null); apiPage<Version>('/api/v1/context-recipe-versions/', token, c.signal).then(p => { if (!c.signal.aborted) { setVersions(p.results); setVersion(current => p.results.some(v => v.recipe_version_id === current) ? current : ''); } }).catch(e => { if (!c.signal.aborted) { setVersions([]); setError(errorMessage(e)); } }).finally(() => { if (!c.signal.aborted) setLoading(false); }); return () => { c.abort(); compilation.current?.abort(); }; }, [token, refreshKey, retry]);
  async function compile(e: React.FormEvent) {
    e.preventDefault(); setError(null); setResult(null);
    let parsed: unknown; try { parsed = JSON.parse(variables); } catch { setError('Runtime block inputs must be valid JSON.'); return; }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) { setError('Runtime block inputs must be a JSON object.'); return; }
    const request = new AbortController(); compilation.current?.abort(); compilation.current = request; setBusy(true);
    try { const compiled = await apiRequest<Compiled>(`/api/v1/context-recipe-versions/${version}/compile/`, token, { method: 'POST', signal: request.signal, body: JSON.stringify({ variables: parsed }) }); if (!request.signal.aborted) setResult(compiled); }
    catch(e) { if (!request.signal.aborted) setError(errorMessage(e)); } finally { if (!request.signal.aborted) setBusy(false); }
  }
  const [authoring, setAuthoring] = useState(false);
  const [recipeName, setRecipeName] = useState('');
  const [modelLimit, setModelLimit] = useState('4096');
  const [outputReserve, setOutputReserve] = useState('512');
  const [systemText, setSystemText] = useState('');
  const [evidenceText, setEvidenceText] = useState('');
  const [questionText, setQuestionText] = useState('');
  async function saveRecipe(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const saved = await apiRequest<{ versions: Version[] }>('/api/v1/context-recipes/', token, { method: 'POST', body: JSON.stringify({ name: recipeName.trim(), initial_version: { model_limit_tokens: Number(modelLimit), output_reserve_tokens: Number(outputReserve), budget_policy: 'trim_lowest_priority', blocks: [
        { block_key: 'system', block_type: 'instruction', role: 'system', priority: 1, order: 0, content_template: systemText },
        { block_key: 'evidence', block_type: 'evidence', role: 'system', priority: 2, order: 1, content_template: evidenceText },
        { block_key: 'question', block_type: 'user_query', role: 'user', priority: 1, order: 2, content_template: questionText },
      ] } }) });
      setVersion(saved.versions[0].recipe_version_id); setAuthoring(false); setRecipeName(''); setVariables('{}'); setResult(null); setRetry(value => value + 1);
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const selected = versions.find(v => v.recipe_version_id === version);
  return <div className="context-workspace">
    <section className="panel"><div className="panel-title"><div><h2>Context recipe compiler</h2><p>Pin a recipe version and inspect its exact compiled input.</p></div><FileCode2 size={20} aria-hidden="true" /></div><div className="panel-body">
      <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
      <button className="secondary" disabled={!token.trim() || busy} onClick={() => setAuthoring(value => !value)}>{authoring ? 'Close recipe editor' : 'New context recipe'}</button>
      {authoring && <form className="form-grid" onSubmit={saveRecipe}>
        <label className="full-width">Recipe name<input required maxLength={200} value={recipeName} onChange={event => setRecipeName(event.target.value)} /></label>
        <label>Model token limit<input type="number" required min={1} max={1000000} value={modelLimit} onChange={event => setModelLimit(event.target.value)} /></label>
        <label>Output token reserve<input type="number" required min={0} max={Math.max(0, Number(modelLimit) - 1)} value={outputReserve} onChange={event => setOutputReserve(event.target.value)} /></label>
        <label className="full-width">System instruction<textarea required rows={3} value={systemText} onChange={event => setSystemText(event.target.value)} /></label>
        <label className="full-width">Evidence template<textarea rows={4} value={evidenceText} onChange={event => setEvidenceText(event.target.value)} /></label>
        <label className="full-width">Question template<textarea required rows={3} value={questionText} onChange={event => setQuestionText(event.target.value)} /></label>
        <p className="muted full-width">Save an immutable first revision. Evidence is omitted first on overflow; essential instructions and the question are retained or compilation fails.</p>
        <button className="primary" disabled={busy || !recipeName.trim() || !systemText.trim() || !questionText.trim()}>Save context recipe</button>
      </form>}
      <form className="form-grid" onSubmit={compile}>
        <label className="full-width">Recipe version<select required disabled={busy} value={version} onChange={e => { setVersion(e.target.value); setResult(null); }}><option value="">Select a saved recipe version</option>{versions.map(v => <option key={v.recipe_version_id} value={v.recipe_version_id}>Recipe #{v.recipe} · v{v.revision_no} · {v.model_limit_tokens.toLocaleString()} tokens</option>)}</select></label>
        <label className="full-width">Runtime block inputs (JSON)<textarea rows={6} disabled={busy} value={variables} onChange={e => { setVariables(e.target.value); setResult(null); }} spellCheck={false} /></label>
        <p className="muted full-width">Override saved content using block keys. Compilation uses the backend token estimator and does not execute model inference.</p>
        <button className="primary" disabled={busy || !version}>{busy ? 'Compiling…' : 'Compile Context Recipe'}</button>
      </form>
      {!loading && !error && !versions.length && <ChartEmpty message="Create a context recipe to begin compiling your own saved blocks." />}
      {selected && <><div className="section-heading"><h3>Saved context blocks</h3><span>{selected.blocks.length} blocks · v{selected.revision_no}</span></div><div className="context-blocks">{selected.blocks.map((block, i) => {
        const dropped = result?.dropped_blocks.includes(block.block_key);
        const included = result?.included_blocks.includes(block.block_key);
        return <article key={block.block_key} className={`context-block ${dropped ? 'dropped' : ''}`}><header><h3>{i + 1}. {block.block_key}</h3><span className={`state state-${dropped ? 'queued' : included ? 'completed' : 'pending'}`}>{dropped ? 'Omitted' : included ? 'Included' : 'Saved template'}</span></header><p>{block.content_template}</p></article>;
      })}</div></>}
    </div></section>
    <div><ChartPanel title={result ? 'Estimated token allocation' : 'Configured token budget'} description={selected ? `Model limit ${selected.model_limit_tokens.toLocaleString()} tokens · policy ${selected.budget_policy}` : 'Select a saved recipe to inspect its budget.'}>
      {selected ? <SegmentBar data={result ? [...(result.block_token_counts?.length ? result.block_token_counts.map((block, index) => ({ label: block.block_key, value: block.token_count, color: index % 5 })) : [{ label: 'Estimated input', value: result.token_count, color: 0 }]), { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }, { label: 'Remaining capacity', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens - result.token_count), color: 4 }] : [{ label: 'Available input budget', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens), color: 0 }, { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }]} unit="tokens" /> : <ChartEmpty message="Token capacity and output reserve come from the selected immutable recipe version." />}
      {result && <p className={`notice ${result.budget_exhausted ? '' : 'success'}`} role="status">{result.budget_exhausted ? 'Input budget exhausted — inspect omitted blocks.' : 'Compiled within the configured input budget.'} Estimated input: {result.token_count.toLocaleString()} tokens.</p>}
    </ChartPanel><section className="panel" style={{ marginTop: 20 }}><div className="panel-title"><div><h2>Compilation evidence</h2><p>Every included and omitted block is inspectable.</p></div><Layers3 size={19} aria-hidden="true" /></div><div className="panel-body"><p className="muted">Allocations use the compiler’s deterministic estimate of the serialized prompt, including role wrappers. Quality experiments require model execution.</p>{result && <dl className="runs-kv"><div><dt>Included blocks</dt><dd>{result.included_blocks.join(', ') || 'None'}</dd></div><div><dt>Omitted blocks</dt><dd>{result.dropped_blocks.join(', ') || 'None'}</dd></div></dl>}</div></section></div>
    {result && <section className="panel context-output"><div className="panel-title"><div><h2>Exact compiled input</h2><p>The serialized prompt returned by the compiler.</p></div><span className="badge">ESTIMATED TOKENS</span></div><div className="panel-body"><pre tabIndex={0} aria-label="Exact compiled prompt">{result.serialized_prompt}</pre></div></section>}
  </div>;
}
