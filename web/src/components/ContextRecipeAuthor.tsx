import { useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, MultilineControl, Notice, Section, Select, TextControl } from './ui';
import { useDraft, DraftIndicator } from './Draft';
export interface RecipeBlock { block_key: string; block_type: string; role: string; priority: number; order: number; content_template: string; max_tokens?: number | null }
export interface RecipeVersion { recipe_version_id: string; recipe: number; revision_no: number; model_limit_tokens: number; output_reserve_tokens: number; budget_policy: string; blocks: RecipeBlock[]; model_version?: number | null; runtime_pins?: Record<string, unknown> }
export interface ContextModel { id: number; model_version_id: string; architecture_ref: string; revision_no: number; model: number }
const initialBlocks: RecipeBlock[] = [
  { block_key: 'system', block_type: 'instruction', role: 'system', priority: 1, order: 0, content_template: '' },
  { block_key: 'evidence', block_type: 'evidence', role: 'user', priority: 2, order: 1, content_template: '' },
  { block_key: 'question', block_type: 'user_query', role: 'user', priority: 1, order: 2, content_template: '' },
];
const blockTypes = ['instruction', 'user_query', 'examples', 'evidence', 'history', 'memory', 'tool_result'].map(value => ({ value, label: value }));
const roles = ['system', 'user', 'assistant', 'tool'].map(value => ({ value, label: value }));
const contentLabel = (block: RecipeBlock) => block.block_key === 'system' ? 'System instruction' : block.block_key === 'evidence' ? 'Evidence template' : block.block_key === 'question' ? 'Question template' : `Content for ${block.block_key}`;
export function ContextRecipeAuthor({ token, source, versions, models, onSaved, onClose }: { token: string; source?: RecipeVersion; versions: RecipeVersion[]; models: ContextModel[]; onSaved(v: RecipeVersion): void; onClose(): void }) {
  const draft = useDraft('context-version-author', { name: '', blocks: JSON.stringify(source?.blocks || initialBlocks), limit: String(source?.model_limit_tokens || 4096), reserve: String(source?.output_reserve_tokens ?? 512), model: String(source?.model_version || ''), policy: source?.budget_policy || 'trim_lowest_priority' }, source?.recipe_version_id || 'new');
  const [name, setName] = draft.field('name'), [blocksValue, setBlocksValue] = draft.field('blocks'), [limit, setLimit] = draft.field('limit'), [reserve, setReserve] = draft.field('reserve'), [model, setModel] = draft.field('model'), [policy, setPolicy] = draft.field('policy');
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const blocks: RecipeBlock[] = JSON.parse(blocksValue);
  function setBlocks(value: RecipeBlock[] | ((rows: RecipeBlock[]) => RecipeBlock[])) {
    setBlocksValue(current => JSON.stringify(typeof value === 'function' ? value(JSON.parse(current)) : value));
  }
  function patch(index: number, field: Partial<RecipeBlock>) { setBlocks(rows => rows.map((row, i) => i === index ? { ...row, ...field } : row)); }
  function move(index: number, direction: number) { setBlocks(rows => { const next = [...rows]; [next[index], next[index + direction]] = [next[index + direction], next[index]]; return next; }); }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      const input = { model_limit_tokens: Number(limit), output_reserve_tokens: Number(reserve), budget_policy: policy, model_version: model ? Number(model) : null, blocks: blocks.map((row, order) => ({ ...row, order })) };
      let value: RecipeVersion;
      if (source) value = await apiRequest<RecipeVersion>('/api/v1/context-recipe-versions/', token, { method: 'POST', body: JSON.stringify({ ...input, recipe: source.recipe, revision_no: Math.max(source.revision_no, ...versions.filter(v => v.recipe === source.recipe).map(v => v.revision_no)) + 1 }) });
      else { const saved = await apiRequest<{ versions: RecipeVersion[] }>('/api/v1/context-recipes/', token, { method: 'POST', body: JSON.stringify({ name: name.trim(), initial_version: input }) }); value = saved.versions[0]; }
      draft.discard(); onSaved(value);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <form data-ui="form" onSubmit={save}>
    <DraftIndicator draft={draft} disabled={busy} />
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    <div data-ui="field-grid">
      {!source && <div data-span="full"><TextControl label="Recipe name" required maxLength={200} value={name} onChange={e => setName(e.target.value)} disabled={busy} /></div>}
      <div data-span="full"><Select label="Pinned model (optional)" disabled={busy} value={model} onChange={e => { setModel(e.target.value); if (e.target.value) { setLimit(models.find(m => String(m.id) === e.target.value)?.architecture_ref === 'modelanvil.general-transformer-sft.v1' ? '32' : '64'); setReserve('8'); } }}
        hint="The measured path uses verified local CPU reference weights, their exact tokenizer and the pinned role-lines template. Counts for unpinned recipes remain estimates. Model bytes are checked again on compilation and execution.">
        <option value="">Estimator only · no model execution</option>{models.filter(m => ['modelanvil.cpu-character-sft.v1', 'modelanvil.general-transformer-sft.v1'].includes(m.architecture_ref)).map(m => <option key={m.id} value={m.id}>Model record {m.model} · r{m.revision_no} · {m.architecture_ref}</option>)}
      </Select></div>
      <TextControl label="Model token limit" required type="number" min={1} max={model ? 64 : 1000000} value={limit} onChange={e => setLimit(e.target.value)} disabled={busy} />
      <TextControl label="Output token reserve" required type="number" min={model ? 1 : 0} max={model ? Math.min(32, Number(limit) - 1) : Number(limit) - 1} value={reserve} onChange={e => setReserve(e.target.value)} disabled={busy} />
      <Select label="Overflow policy" value={policy} disabled={busy} onChange={e => setPolicy(e.target.value)} options={[{ value: 'trim_lowest_priority', label: 'Omit lowest priority blocks' }, { value: 'fail_on_overflow', label: 'Fail on overflow' }, { value: 'trim_optional_evidence', label: 'Omit optional evidence only' }]} />
    </div>
    {blocks.map((block, i) => <Section key={i} level={3} title={`Block ${i + 1} · ${block.block_key}`} actions={<>
      <Button type="button" size="sm" aria-label={`Move block ${i + 1} up`} disabled={busy || !i} onClick={() => move(i, -1)}>Move up</Button>
      <Button type="button" size="sm" aria-label={`Move block ${i + 1} down`} disabled={busy || i === blocks.length - 1} onClick={() => move(i, 1)}>Move down</Button>
      <Button type="button" size="sm" disabled={busy || blocks.length === 1} onClick={() => setBlocks(rows => rows.filter((_, n) => n !== i))}>Remove block {i + 1}</Button>
    </>}>
      <div data-ui="field-grid">
        <TextControl label={`Block key ${i + 1}`} required maxLength={64} disabled={busy} value={block.block_key} onChange={e => patch(i, { block_key: e.target.value })} />
        <Select label={`Block type ${i + 1}`} disabled={busy} value={block.block_type} onChange={e => patch(i, { block_type: e.target.value })} options={blockTypes} />
        <Select label={`Role ${i + 1}`} disabled={busy} value={block.role} onChange={e => patch(i, { role: e.target.value })} options={roles} />
        <TextControl label={`Retention priority ${i + 1}`} type="number" required min={1} max={10} disabled={busy} value={block.priority} onChange={e => patch(i, { priority: Number(e.target.value) })} />
        <TextControl label={`Block token cap ${i + 1} (optional)`} type="number" min={1} max={1000000} disabled={busy} value={block.max_tokens ?? ''} onChange={e => patch(i, { max_tokens: e.target.value ? Number(e.target.value) : null })} />
        <div data-span="full"><MultilineControl label={contentLabel(block)} rows={3} maxLength={200000} disabled={busy} value={block.content_template} onChange={e => patch(i, { content_template: e.target.value })} /></div>
      </div>
    </Section>)}
    <div data-ui="actions"><Button type="button" disabled={busy || blocks.length >= 100} onClick={() => setBlocks(rows => [...rows, { block_key: `block_${rows.length + 1}`, block_type: 'evidence', role: 'user', priority: 2, order: rows.length, content_template: '' }])}>Add context block</Button></div>
    <p className="muted">Priority 1 content must fit in full, including each declared block cap. Caps include standalone tokenizer overhead. Optional block caps truncate explicitly and appear in the compilation receipt. “Omit optional evidence only” can omit evidence blocks with priorities 2–10; other categories are preserved. Evidence and tool results can contain untrusted instructions; rendering them does not prove resistance to prompt injection. Saving creates an immutable revision.</p>
    <div data-ui="actions"><Button variant="primary" disabled={busy || (!source && !name.trim())}>{busy ? 'Saving…' : source ? 'Save new recipe revision' : 'Save context recipe'}</Button><Button type="button" disabled={busy} onClick={onClose}>Close recipe editor</Button></div>
  </form>;
}
