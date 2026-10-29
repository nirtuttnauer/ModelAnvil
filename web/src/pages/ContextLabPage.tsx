import { Button, Dialog, Disclosure, KeyValueList, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { ContextBlockEditor, ContextBlockInputs } from '../components/ContextBlockEditor';
import { objectInput } from '../components/form-data';
import { TextContent } from '../components/DataInspector';
import { Identifier } from '../components/Identifier';
import { useDraft, DraftIndicator } from '../components/Draft';
import { useEffect, useId, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartEmpty, ChartPanel, SegmentBar } from '../components/Charts';
import './ml-pages.css';
import { ContextExperiments } from '../components/ContextExperiments';
import { ContextRecipeAuthor, type ContextModel, type RecipeVersion } from '../components/ContextRecipeAuthor';

type Version = RecipeVersion;
interface Compiled { serialized_prompt: string; token_count: number; included_blocks: string[]; dropped_blocks: string[]; budget_exhausted: boolean; block_token_counts?: { block_key: string; token_count: number; truncated: boolean }[] }

export function ContextLabPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const formId = useId();
  const selectionDraft = useDraft('context-selection', { version: '' });
  const [versions, setVersions] = useState<Version[]>([]); const [version, setVersion] = selectionDraft.field('version');
  const [models, setModels] = useState<ContextModel[]>([]); const [revising, setRevising] = useState(false); const [experimentsOpen, setExperimentsOpen] = useState(false);
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
  const allocation = selected ? (result
    ? [...(result.block_token_counts?.length ? result.block_token_counts.map((block, index) => ({ label: block.block_key, value: block.token_count, color: index % 5 })) : [{ label: 'Estimated input', value: result.token_count, color: 0 }]), { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }, { label: 'Remaining capacity', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens - result.token_count), color: 4 }]
    : [{ label: 'Available input budget', value: Math.max(0, selected.model_limit_tokens - selected.output_reserve_tokens), color: 0 }, { label: 'Output reserve', value: selected.output_reserve_tokens, color: 2 }]) : [];

  return <div className="ml-page">
    <Section title="Compiler" description="Pin a recipe version and inspect its exact compiled input." actions={<>
      <Select aria-label="Recipe version" required disabled={busy} value={version} onChange={e => { setVersion(e.target.value); setResult(null); }}>
        <option value="">Select a saved recipe version</option>{versions.map((v, index) => <option key={v.recipe_version_id} value={v.recipe_version_id}>Recipe {index + 1} · v{v.revision_no} · {v.model_limit_tokens.toLocaleString()} tokens</option>)}
      </Select>
      <Button type="button" variant="primary" disabled={!token.trim() || busy} onClick={() => setAuthoring(true)}>New context recipe</Button>
      {selected && <Button type="button" disabled={busy} onClick={() => setRevising(true)}>Revise selected recipe</Button>}
    </>}>
      <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
      {!loading && !error && !versions.length && <EmptyState title="No context recipes yet" description="Create a context recipe to compile your own saved blocks." />}
      <form data-ui="form" onSubmit={compile}>
        <DraftIndicator draft={compilationDraft} disabled={busy} />
        {selected && <Disclosure summary="Override saved context (optional)" variant="quiet">
          <ContextBlockInputs blocks={selected.blocks.map(block => ({ key: block.block_key, content: block.content_template, role: block.role, essential: block.priority == null ? undefined : block.priority <= 1 }))} value={variables} disabled={busy} onChange={next => { setVariables(next); setResult(null); }} />
        </Disclosure>}
        <div data-ui="actions">
          <Button variant="primary" disabled={busy || !version}>{busy ? 'Compiling…' : 'Compile context recipe'}</Button>
          <span className="muted">Uses the backend token estimator; no model runs.</span>
        </div>
      </form>
      {result && <div className="ml-run">
        <div className="ml-run-head"><h3>Compiled input</h3><StatusBadge status={result.budget_exhausted ? 'budget_exhausted' : 'compiled'} tone={result.budget_exhausted ? 'caution' : 'success'} label={result.budget_exhausted ? 'Input budget exhausted' : 'Within budget'} /></div>
        <p role="status" className="muted">{result.budget_exhausted ? 'Input budget exhausted; inspect the omitted blocks.' : 'Compiled within the configured input budget.'} Estimated input: {result.token_count.toLocaleString()} tokens.</p>
        <TextContent text={result.serialized_prompt} label="Exact compiled prompt" />
        <KeyValueList columns={2} items={[{ label: 'Included blocks', value: result.included_blocks.join(', ') || 'None' }, { label: 'Omitted blocks', value: result.dropped_blocks.join(', ') || 'None' }]} />
      </div>}
      <ChartPanel bordered title={result ? 'Estimated token allocation' : 'Configured token budget'} description={selected ? `Model limit ${selected.model_limit_tokens.toLocaleString()} tokens · policy ${selected.budget_policy}` : 'Select a saved recipe to inspect its budget.'}>
        {selected ? <SegmentBar data={allocation} unit="tokens" /> : <ChartEmpty message="Token capacity and output reserve come from the selected recipe version." />}
      </ChartPanel>
      {selected && <Disclosure summary="Saved context blocks" variant="quiet">
        <p className="muted">Version <Identifier value={selected.recipe_version_id} label="Context recipe version ID" display="code" /></p>
        <ContextBlockEditor title={`Saved context blocks · v${selected.revision_no}`} blocks={selected.blocks.map(block => ({ key: block.block_key, content: block.content_template, role: block.role,
          essential: block.priority == null ? undefined : block.priority <= 1,
          status: result?.dropped_blocks.includes(block.block_key) ? 'Omitted' : result?.included_blocks.includes(block.block_key) ? 'Included' : 'Saved template',
          tokenCount: result?.block_token_counts?.find(count => count.block_key === block.block_key)?.token_count,
        }))} />
      </Disclosure>}
    </Section>
    {selected && <Disclosure summary="Measured context experiments" variant="card" open={experimentsOpen} onToggle={event => setExperimentsOpen(event.currentTarget.open)}>{experimentsOpen && <ContextExperiments key={`${token}:${selected.recipe_version_id}`} token={token} version={selected} versions={versions} />}</Disclosure>}
    <Dialog title="Revise context recipe" description="Save a new revision of the selected recipe." open={revising} onClose={() => setRevising(false)} size="lg">
      {revising && selected && <ContextRecipeAuthor key={selected.recipe_version_id} token={token} source={selected} versions={versions} models={models} onClose={() => setRevising(false)} onSaved={saved => { setVersion(saved.recipe_version_id); setRevising(false); setResult(null); setRetry(v => v + 1); }} />}
    </Dialog>
    <Dialog title="New context recipe" description="Save an immutable first revision with its token budget and blocks." open={authoring} onClose={() => setAuthoring(false)} size="lg"
      footer={<><Button type="button" disabled={busy} onClick={() => setAuthoring(false)}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || !recipeName.trim() || !systemText.trim() || !questionText.trim()}>Save context recipe</Button></>}>
      <form id={formId} data-ui="form" onSubmit={saveRecipe}>
        <DraftIndicator draft={draft} disabled={busy} />
        <div data-ui="field-grid">
          <div data-span="full"><TextControl label="Recipe name" required maxLength={200} value={recipeName} onChange={event => setRecipeName(event.target.value)} /></div>
          <TextControl label="Model token limit" type="number" required min={1} max={1000000} value={modelLimit} onChange={event => setModelLimit(event.target.value)} />
          <TextControl label="Output token reserve" type="number" required min={0} max={Math.max(0, Number(modelLimit) - 1)} value={outputReserve} onChange={event => setOutputReserve(event.target.value)} />
        </div>
        <ContextBlockEditor disabled={busy} title="Recipe context blocks" blocks={[
          { key: 'system', label: 'System instruction', content: systemText, role: 'system', essential: true },
          { key: 'evidence', label: 'Evidence template', content: evidenceText, role: 'system', essential: false },
          { key: 'question', label: 'Question template', content: questionText, role: 'user', essential: true },
        ]} onChange={(key, content) => { if (key === 'system') setSystemText(content); else if (key === 'evidence') setEvidenceText(content); else setQuestionText(content); }} />
        <p className="muted">Evidence is omitted first on overflow; essential instructions and the question are retained or compilation fails.</p>
      </form>
    </Dialog>
  </div>;
}
