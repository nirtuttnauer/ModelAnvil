import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field } from '../components/ui';
import { ContextBlockEditor, ContextBlockInputs } from '../components/ContextBlockEditor';
import { objectInput } from '../components/form-data';
import { TextContent } from '../components/DataInspector';
import { useDraft, DraftStatus } from '../components/Draft';
import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartEmpty, ChartPanel, SegmentBar } from '../components/Charts';
import { FileCode2, Layers3 } from 'lucide-react';
interface Version { recipe_version_id: string; recipe: number; revision_no: number; model_limit_tokens: number; output_reserve_tokens: number; budget_policy: string; blocks: { block_key: string; content_template: string; role?: string; priority?: number }[] }
interface Compiled { serialized_prompt: string; token_count: number; included_blocks: string[]; dropped_blocks: string[]; budget_exhausted: boolean; block_token_counts?: { block_key: string; token_count: number; truncated: boolean }[] }
export function ContextLabPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const selectionDraft = useDraft('context-selection', { version: '' });
  const [versions, setVersions] = useState<Version[]>([]); const [version, setVersion] = selectionDraft.field('version');
  const compilationDraft = useDraft('context-inputs', { variables: '{}' }, version);
  const [variables, setVariables] = compilationDraft.field('variables'); const [result, setResult] = useState<Compiled | null>(null);
  const compilation = useRef<AbortController | null>(null);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null); const [retry, setRetry] = useState(0);
  useEffect(() => { const c = new AbortController(); compilation.current?.abort(); setResult(null); setBusy(false); setLoading(true); setError(null); apiPage<Version>('/api/v1/context-recipe-versions/', token, c.signal).then(p => { if (!c.signal.aborted) { setVersions(p.results);  } }).catch(e => { if (!c.signal.aborted) { setVersions([]); setError(errorMessage(e)); } }).finally(() => { if (!c.signal.aborted) setLoading(false); }); return () => { c.abort(); compilation.current?.abort(); }; }, [token, refreshKey, retry]);
  async function compile(e: React.FormEvent) {
    e.preventDefault(); setError(null); setResult(null);
    let parsed: Record<string, unknown>; try { parsed = objectInput(variables); } catch (e) { setError(errorMessage(e)); return; }
    const request = new AbortController(); compilation.current?.abort(); compilation.current = request; setBusy(true);
    try { const compiled = await apiRequest<Compiled>(`/api/v1/context-recipe-versions/${version}/compile/`, token, { method: 'POST', signal: request.signal, body: JSON.stringify({ variables: parsed }) }); if (!request.signal.aborted) setResult(compiled); }
    catch(e) { if (!request.signal.aborted) setError(errorMessage(e)); } finally { if (!request.signal.aborted) setBusy(false); }
  }
  const draft = useDraft('context-author', { authoring: false as boolean, recipeName: '', modelLimit: '4096', outputReserve: '512', systemText: '', evidenceText: '', questionText: '' });
  const [authoring, setAuthoring] = draft.field('authoring');
  const [recipeName, setRecipeName] = draft.field('recipeName');
  const [modelLimit, setModelLimit] = draft.field('modelLimit');
  const [outputReserve, setOutputReserve] = draft.field('outputReserve');
  const [systemText, setSystemText] = draft.field('systemText');
  const [evidenceText, setEvidenceText] = draft.field('evidenceText');
  const [questionText, setQuestionText] = draft.field('questionText');
  async function saveRecipe(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const saved = await apiRequest<{ versions: Version[] }>('/api/v1/context-recipes/', token, { method: 'POST', body: JSON.stringify({ name: recipeName.trim(), initial_version: { model_limit_tokens: Number(modelLimit), output_reserve_tokens: Number(outputReserve), budget_policy: 'trim_lowest_priority', blocks: [
        { block_key: 'system', block_type: 'instruction', role: 'system', priority: 1, order: 0, content_template: systemText },
        { block_key: 'evidence', block_type: 'evidence', role: 'system', priority: 2, order: 1, content_template: evidenceText },
        { block_key: 'question', block_type: 'user_query', role: 'user', priority: 1, order: 2, content_template: questionText },
      ] } }) });
      draft.discard(); setVersion(saved.versions[0].recipe_version_id); setAuthoring(false); setRecipeName(''); setVariables('{}'); setResult(null); setRetry(value => value + 1);
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const selected = versions.find(v => v.recipe_version_id === version);
  return <div className="context-workspace">
    <Card className="panel"><div className="panel-title"><div><h2>Context recipe compiler</h2><p>Pin a recipe version and inspect its exact compiled input.</p></div><FileCode2 size={20} aria-hidden="true" /></div><div className="panel-body">
      <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
      <Button className="secondary" disabled={!token.trim() || busy} onClick={() => setAuthoring(value => !value)}>{authoring ? 'Close recipe editor' : 'New context recipe'}</Button>
      {authoring && <form className="form-grid" onSubmit={saveRecipe}><DraftStatus draft={draft} disabled={busy} />
        <label className="full-width">Recipe name<Field required maxLength={200} value={recipeName} onChange={event => setRecipeName(event.target.value)} /></label>
        <label>Model token limit<Field type="number" required min={1} max={1000000} value={modelLimit} onChange={event => setModelLimit(event.target.value)} /></label>
        <label>Output token reserve<Field type="number" required min={0} max={Math.max(0, Number(modelLimit) - 1)} value={outputReserve} onChange={event => setOutputReserve(event.target.value)} /></label>
        <ContextBlockEditor disabled={busy} title="Recipe context blocks" blocks={[
          { key: 'system', label: 'System instruction', content: systemText, role: 'system', essential: true },
          { key: 'evidence', label: 'Evidence template', content: evidenceText, role: 'system', essential: false },
          { key: 'question', label: 'Question template', content: questionText, role: 'user', essential: true },
        ]} onChange={(key, content) => { if (key === 'system') setSystemText(content); else if (key === 'evidence') setEvidenceText(content); else setQuestionText(content); }} />
        <p className="muted full-width">Save an immutable first revision. Evidence is omitted first on overflow; essential instructions and the question are retained or compilation fails.</p>
        <Button className="primary" disabled={busy || !recipeName.trim() || !systemText.trim() || !questionText.trim()}>Save context recipe</Button>
      </form>}
      <form className="form-grid" onSubmit={compile}><DraftStatus draft={compilationDraft} disabled={busy} />
        <label className="full-width">Recipe version<select required disabled={busy} value={version} onChange={e => { setVersion(e.target.value); setResult(null); }}><option value="">Select a saved recipe version</option>{versions.map((v, index) => <option key={v.recipe_version_id} value={v.recipe_version_id}>Recipe {index + 1} · v{v.revision_no} · {v.model_limit_tokens.toLocaleString()} tokens</option>)}</select></label>
        {selected && <Identifier value={selected.recipe_version_id} label="Context recipe version ID" />}{selected && <details className="workspace-details full-width"><summary>Override saved context (optional)</summary><ContextBlockInputs blocks={selected.blocks.map(block => ({ key: block.block_key, content: block.content_template, role: block.role, essential: block.priority == null ? undefined : block.priority <= 1 }))} value={variables} disabled={busy} onChange={next => { setVariables(next); setResult(null); }} /></details>}

        <p className="muted full-width">Override saved content using block keys. Compilation uses the backend token estimator and does not execute model inference.</p>
        <Button className="primary" disabled={busy || !version}>{busy ? 'Compiling…' : 'Compile Context Recipe'}</Button>
      </form>
      {!loading && !error && !versions.length && <ChartEmpty message="Create a context recipe to begin compiling your own saved blocks." />}
      {selected && <details className="workspace-details"><summary>Saved context blocks</summary><ContextBlockEditor title={`Saved context blocks · v${selected.revision_no}`} blocks={selected.blocks.map(block => ({ key: block.block_key, content: block.content_template, role: block.role,
        essential: block.priority == null ? undefined : block.priority <= 1,
        status: result?.dropped_blocks.includes(block.block_key) ? 'Omitted' : result?.included_blocks.includes(block.block_key) ? 'Included' : 'Saved template',
        tokenCount: result?.block_token_counts?.find(count => count.block_key === block.block_key)?.token_count,
      }))} /></details>}
    </div></Card>
    <div><ChartPanel title={result ? 'Estimated token allocation' : 'Configured token budget'} description={selected ? `Model limit ${selected.model_limit_tokens.toLocaleString()} tokens · policy ${selected.budget_policy}` : 'Select a saved recipe to inspect its budget.'}>
      {selected ? <SegmentBar data={result ? [...(result.block_token_counts?.length ? result.block_token_counts.map((block, index) => ({ label: block.block_key, value: block.token_count, color: index % 5 })) : [{ label: 'Estimated input', value: result.token_count, color: 0 }]), { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }, { label: 'Remaining capacity', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens - result.token_count), color: 4 }] : [{ label: 'Available input budget', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens), color: 0 }, { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }]} unit="tokens" /> : <ChartEmpty message="Token capacity and output reserve come from the selected immutable recipe version." />}
      {result && <p className={`notice ${result.budget_exhausted ? '' : 'success'}`} role="status">{result.budget_exhausted ? 'Input budget exhausted — inspect omitted blocks.' : 'Compiled within the configured input budget.'} Estimated input: {result.token_count.toLocaleString()} tokens.</p>}
    </ChartPanel><Card className="panel" style={{ marginTop: 20 }}><div className="panel-title"><div><h2>Compilation evidence</h2><p>Every included and omitted block is inspectable.</p></div><Layers3 size={19} aria-hidden="true" /></div><div className="panel-body"><p className="muted">Allocations use the compiler’s deterministic estimate of the serialized prompt, including role wrappers. Quality experiments require model execution.</p>{result && <dl className="runs-kv"><div><dt>Included blocks</dt><dd>{result.included_blocks.join(', ') || 'None'}</dd></div><div><dt>Omitted blocks</dt><dd>{result.dropped_blocks.join(', ') || 'None'}</dd></div></dl>}</div></Card></div>
    {result && <Card className="panel context-output"><div className="panel-title"><div><h2>Exact compiled input</h2><p>The serialized prompt returned by the compiler.</p></div><Badge className="badge">ESTIMATED TOKENS</Badge></div><div className="panel-body"><TextContent text={result.serialized_prompt} label="Exact compiled prompt" /></div></Card>}
  </div>;
}
