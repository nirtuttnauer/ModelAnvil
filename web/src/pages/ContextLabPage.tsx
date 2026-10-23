import { ContextRecipeAuthor, type RecipeVersion, type ContextModel } from '../components/ContextRecipeAuthor';
import { ContextExperiments } from '../components/ContextExperiments';
import { Identifier } from '../components/Identifier';
import { Badge, Button, Card } from '../components/ui';
import { ContextBlockEditor, ContextBlockInputs } from '../components/ContextBlockEditor';
import { objectInput } from '../components/form-data';
import { TextContent } from '../components/DataInspector';
import { useDraft, DraftStatus } from '../components/Draft';
import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartEmpty, ChartPanel, SegmentBar } from '../components/Charts';
import { FileCode2, Layers3 } from 'lucide-react';
type Version = RecipeVersion;
interface Compiled { budget?: { runtime_validated: boolean; input_tokens: number; output_reserve_tokens: number; total_reserved_tokens: number; runtime_limit_tokens: number | null; configured_limit_tokens: number; remaining_tokens: number; overflow_policy: string }; omitted_blocks?: { block_key: string; block_type?: string; reason: string }[]; truncated_blocks?: { block_key: string; reason: string; original_tokens: number; tokens_retained: number; included_in_final?: boolean }[]; token_count_method?: string; serialized_prompt: string; token_count: number; included_blocks: string[]; dropped_blocks: string[]; budget_exhausted: boolean; block_token_counts?: { block_key: string; token_count: number; truncated: boolean }[] }
export function ContextLabPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const selectionDraft = useDraft('context-selection', { version: '' });
  const [models, setModels] = useState<ContextModel[]>([]); const [versions, setVersions] = useState<Version[]>([]); const [version, setVersion] = selectionDraft.field('version');
  const compilationDraft = useDraft('context-inputs', { variables: '{}' }, version);
  const [variables, setVariables] = compilationDraft.field('variables'); const [result, setResult] = useState<Compiled | null>(null);
  const compilation = useRef<AbortController | null>(null);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [retry, setRetry] = useState(0);
  useEffect(() => { const c = new AbortController(); compilation.current?.abort(); setResult(null); setBusy(false); setLoading(true); setError(null); Promise.all([apiPage<Version>('/api/v1/context-recipe-versions/', token, c.signal), apiPage<ContextModel>('/api/v1/model-versions/', token, c.signal)]).then(([p, m]) => { if (!c.signal.aborted) { setVersions(p.results); setModels(m.results); } }).catch(e => { if (!c.signal.aborted) { setVersions([]); setError(errorMessage(e)); } }).finally(() => { if (!c.signal.aborted) setLoading(false); }); return () => { c.abort(); compilation.current?.abort(); }; }, [token, refreshKey, retry]);
  async function compile(e: React.FormEvent) {
    e.preventDefault(); setError(null); setResult(null);
    let parsed: Record<string, unknown>; try { parsed = objectInput(variables); } catch (e) { setError(errorMessage(e)); return; }
    const request = new AbortController(); compilation.current?.abort(); compilation.current = request; setBusy(true);
    try { const compiled = await apiRequest<Compiled>(`/api/v1/context-recipe-versions/${version}/compile/`, token, { method: 'POST', signal: request.signal, body: JSON.stringify({ variables: parsed }) }); if (!request.signal.aborted) setResult(compiled); }
    catch(e) { if (!request.signal.aborted) setError(errorMessage(e)); } finally { if (!request.signal.aborted) setBusy(false); }
  }
  const authoringDraft = useDraft('context-author-open', { authoring: false as boolean });
  const [authoring, setAuthoring] = authoringDraft.field('authoring');
  const [revisionSource, setRevisionSource] = useState<Version | undefined>(undefined);
  const selected = versions.find(v => v.recipe_version_id === version);
  return <div className="context-workspace">
    <Card className="panel"><div className="panel-title"><div><h2>Context recipe compiler</h2><p>Pin a recipe version and inspect its exact compiled input.</p></div><FileCode2 size={20} aria-hidden="true" /></div><div className="panel-body">
      <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
      <Button className="secondary" disabled={!token.trim() || busy} onClick={() => { setRevisionSource(undefined); setAuthoring(value => !value); }}>{authoring ? 'Close recipe editor' : 'New context recipe'}</Button>
      {selected && <Button disabled={busy} onClick={() => { setRevisionSource(selected); setAuthoring(true); }}>Revise selected recipe</Button>}
      {authoring && <ContextRecipeAuthor key={revisionSource?.recipe_version_id || 'new'} token={token} source={revisionSource} versions={versions} models={models} onClose={() => setAuthoring(false)} onSaved={saved => { setVersion(saved.recipe_version_id); setAuthoring(false); setVariables('{}'); setResult(null); setRetry(v => v + 1); }} />}
      <form className="form-grid" onSubmit={compile}><DraftStatus draft={compilationDraft} disabled={busy} />
        <label className="full-width">Recipe version<select required disabled={busy} value={version} onChange={e => { setVersion(e.target.value); setResult(null); }}><option value="">Select a saved recipe version</option>{versions.map((v, index) => <option key={v.recipe_version_id} value={v.recipe_version_id}>Recipe {index + 1} · v{v.revision_no} · {v.model_limit_tokens.toLocaleString()} tokens</option>)}</select></label>
        {selected && <Identifier value={selected.recipe_version_id} label="Context recipe version ID" />}{selected && <details className="workspace-details full-width"><summary>Override saved context (optional)</summary><ContextBlockInputs blocks={selected.blocks.map(block => ({ key: block.block_key, content: block.content_template, role: block.role, essential: block.priority == null ? undefined : block.priority <= 1 }))} value={variables} disabled={busy} onChange={next => { setVariables(next); setResult(null); }} /></details>}

        <p className="muted full-width">Override saved content using block keys. Pinned CPU recipes use the exact runtime tokenizer and role-lines template. Unpinned recipes use an explicitly labeled estimate. Compilation itself does not execute inference.</p>
        <Button className="primary" disabled={busy || loading || !selected}>{busy ? 'Compiling…' : 'Compile Context Recipe'}</Button>
      </form>
      {!loading && !error && !versions.length && <ChartEmpty message="Create a context recipe to begin compiling your own saved blocks." />}
      {selected && <details className="workspace-details"><summary>Saved context blocks</summary><ContextBlockEditor title={`Saved context blocks · v${selected.revision_no}`} exactTokens={result?.token_count_method === 'exact_runtime_tokenizer'} blocks={selected.blocks.map(block => ({ key: block.block_key, content: block.content_template, role: block.role,
        essential: block.priority == null ? undefined : block.priority <= 1,
        status: result?.dropped_blocks.includes(block.block_key) ? 'Omitted' : result?.included_blocks.includes(block.block_key) ? 'Included' : 'Saved template',
        tokenCount: result?.block_token_counts?.find(count => count.block_key === block.block_key)?.token_count,
      }))} /></details>}
    </div></Card>
    <div><ChartPanel title={result ? result.token_count_method === 'exact_runtime_tokenizer' ? 'Exact runtime token allocation' : 'Estimated token allocation' : 'Configured token budget'} description={selected ? `Model limit ${selected.model_limit_tokens.toLocaleString()} tokens · policy ${selected.budget_policy}` : 'Select a saved recipe to inspect its budget.'}>
      {selected ? <SegmentBar data={result ? [...(result.block_token_counts?.length ? result.block_token_counts.map((block, index) => ({ label: block.block_key, value: block.token_count, color: index % 5 })) : [{ label: result.token_count_method === 'exact_runtime_tokenizer' ? 'Input / template overhead' : 'Estimated input', value: result.token_count, color: 0 }]), { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }, { label: 'Remaining capacity', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens - result.token_count), color: 4 }] : [{ label: 'Available input budget', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens), color: 0 }, { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }]} unit="tokens" /> : <ChartEmpty message="Token capacity and output reserve come from the selected immutable recipe version." />}
      {result && <p className={`notice ${result.budget_exhausted ? '' : 'success'}`} role="status">{result.budget_exhausted ? 'Input budget exhausted — inspect omitted blocks.' : 'Compiled within the configured input budget.'} {result.token_count_method === 'exact_runtime_tokenizer' ? 'Exact input' : 'Estimated input'}: {result.token_count.toLocaleString()} tokens.</p>}
    </ChartPanel><Card className="panel" style={{ marginTop: 20 }}><div className="panel-title"><div><h2>Compilation evidence</h2><p>Every included and omitted block is inspectable.</p></div><Layers3 size={19} aria-hidden="true" /></div><div className="panel-body"><p className="muted">Allocations include the selected template and special tokens. Counts are exact for a pinned verified CPU runtime; other recipes retain estimated counts.</p>{result && <dl className="runs-kv"><div><dt>Included blocks</dt><dd>{result.included_blocks.join(', ') || 'None'}</dd></div><div><dt>Omitted blocks</dt><dd>{result.dropped_blocks.join(', ') || 'None'}</dd></div></dl>}</div></Card></div>
    {result?.budget && <Card className="panel"><div className="panel-title"><h2>Compiled token budget</h2><Badge className="badge">{result.budget.runtime_validated ? 'RUNTIME VALIDATED' : 'ESTIMATE · NO RUNTIME VALIDATION'}</Badge></div><div className="panel-body"><p>{result.budget.input_tokens} input + {result.budget.output_reserve_tokens} output reserve = {result.budget.total_reserved_tokens} / {result.budget.configured_limit_tokens} configured tokens. {result.budget.remaining_tokens} tokens remain.{result.budget.runtime_limit_tokens !== null && ` Pinned runtime limit: ${result.budget.runtime_limit_tokens} tokens.`}</p><p>Overflow policy: {result.budget.overflow_policy.replaceAll('_', ' ')}. Priority 1 content is preserved. Counts include the complete template and tokenizer overhead; block allocations are changes in serialized prefix counts.</p>{!!result.omitted_blocks?.length && <div><h3>Omitted blocks</h3><ul>{result.omitted_blocks.map(block => <li key={block.block_key}>{block.block_key} · {block.block_type || 'optional block'} · {block.reason.replaceAll('_', ' ')}</li>)}</ul></div>}{!!result.truncated_blocks?.length && <div><h3>Explicit block truncation</h3><ul>{result.truncated_blocks.map(block => <li key={block.block_key}>{block.block_key}: {block.original_tokens} → {block.tokens_retained} standalone tokens{block.included_in_final === false ? ' before subsequent omission' : ''} · {block.reason.replaceAll('_', ' ')}</li>)}</ul></div>}</div></Card>}
    {selected && <ContextExperiments key={`${token}:${selected.recipe_version_id}`} token={token} version={selected} versions={versions} />}
    {result && <Card className="panel context-output"><div className="panel-title"><div><h2>Exact compiled input</h2><p>The serialized prompt returned by the compiler.</p></div><Badge className="badge">{result.token_count_method === 'exact_runtime_tokenizer' ? 'EXACT RUNTIME TOKENS' : 'ESTIMATED TOKENS'}</Badge></div><div className="panel-body"><TextContent text={result.serialized_prompt} label="Exact compiled prompt" /></div></Card>}
  </div>;
}
