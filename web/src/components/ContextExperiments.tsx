import { useEffect, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ContextBlockInputs } from './ContextBlockEditor';
import { DataInspector, TextContent } from './DataInspector';
import { Button, Disclosure, KeyValueList, Notice, Section, Select, StatusBadge, TextControl } from './ui';
import { Identifier } from './Identifier';
import { objectInput } from './form-data';
import type { RecipeVersion } from './ContextRecipeAuthor';
interface Variant { status: string; reason?: string; prompt?: string; output?: string; exact_match?: boolean; evidence_retained?: Record<string, boolean>; usage?: { prompt_tokens: number; completion_tokens: number }; elapsed_seconds?: number; omitted_blocks?: unknown[]; truncated_blocks?: unknown[] }
interface Experiment { experiment_id: string; name?: string; status: string; reason?: string; metrics?: Record<string, unknown>; details?: { origin?: string; cases_digest?: string; limits?: string; recipes?: { version_id: string }[]; pins?: Record<string, unknown>; decoding?: Record<string, unknown>; environment?: Record<string, unknown>; cases?: { case_id: string; session_key: string; expected: string; output_changed: boolean; baseline: Variant; candidate: Variant }[] } }
const newCase = (n: number) => ({ id: `case-${n}`, session: `session-${n}`, expected: '', variables: '{}', evidence: '' });
export function ContextExperiments({ token, version, versions }: { token: string; version: RecipeVersion; versions: RecipeVersion[] }) {
  const [configure, setConfigure] = useState(false);
  const [baseline, setBaseline] = useState(''), [name, setName] = useState(''), [seed, setSeed] = useState('42'), [cases, setCases] = useState([newCase(1)]);
  const [experiments, setExperiments] = useState<Experiment[]>([]), [selected, setSelected] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  useEffect(() => { const c = new AbortController(); apiPage<Experiment>('/api/v1/context-experiments/', token, c.signal).then(data => { if (!c.signal.aborted) setExperiments(data.results); }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }); return () => c.abort(); }, [token, version.recipe_version_id, retry]);
  async function run(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      const result = await apiRequest<Experiment>(`/api/v1/context-recipe-versions/${version.recipe_version_id}/paired-experiment/`, token, { method: 'POST', body: JSON.stringify({ name: name.trim(), baseline_version_id: baseline, seed: Number(seed), cases: cases.map(c => ({ case_id: c.id, session_key: c.session, expected: c.expected, variables: objectInput(c.variables), ...(c.evidence ? { evidence: { target: c.evidence } } : {}) })) }) });
      setExperiments(rows => [result, ...rows]); setSelected(result.experiment_id); setRetry(v => v + 1);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const report = experiments.find(e => e.experiment_id === selected);
  function patch(index: number, values: Partial<ReturnType<typeof newCase>>) { setCases(rows => rows.map((row, i) => i === index ? { ...row, ...values } : row)); }
  const baselines = versions.filter(v => v.recipe_version_id !== version.recipe_version_id && v.model_version && v.model_version === version.model_version && v.output_reserve_tokens === version.output_reserve_tokens);
  return <Section title="Measured paired context experiment" description="Compare the same frozen cases on two recipes pinned to the same CPU reference model, tokenizer, template and output reserve. Greedy inference records actual outputs, token usage and latency. Each case supplies its own memory and frozen tool text; no session state or live tools carry between cases."
    actions={version.model_version ? <Button type="button" disabled={busy} onClick={() => setConfigure(v => !v)}>{configure ? 'Close experiment setup' : 'Configure paired experiment'}</Button> : undefined}>
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    {!version.model_version && <Notice>Save a recipe revision with a verified local CPU reference model to enable measured inference. Estimator-only recipes remain available for prompt inspection.</Notice>}
    {version.model_version && configure && <form data-ui="form" onSubmit={run}>
      <div data-ui="field-grid">
        <TextControl label="Experiment name" required maxLength={200} disabled={busy} value={name} onChange={e => setName(e.target.value)} />
        <Select label="Baseline recipe revision" required disabled={busy} value={baseline} onChange={e => setBaseline(e.target.value)}><option value="">Choose a pinned baseline</option>{baselines.map(v => <option key={v.recipe_version_id} value={v.recipe_version_id}>Recipe {v.recipe} · r{v.revision_no}</option>)}</Select>
        <TextControl label="Decoding seed" type="number" required min={0} max={2147483639} disabled={busy} value={seed} onChange={e => setSeed(e.target.value)} />
      </div>
      {cases.map((c, index) => <Section key={index} level={3} title={`Experiment case ${index + 1}`} actions={cases.length > 1 ? <Button type="button" size="sm" disabled={busy} onClick={() => setCases(rows => rows.filter((_, i) => i !== index))}>Remove case {index + 1}</Button> : undefined}>
        <div data-ui="field-grid">
          <TextControl label={`Case ID ${index + 1}`} required maxLength={128} disabled={busy} value={c.id} onChange={e => patch(index, { id: e.target.value })} />
          <TextControl label={`Session key ${index + 1}`} required maxLength={128} disabled={busy} value={c.session} onChange={e => patch(index, { session: e.target.value })} />
          <TextControl label={`Expected exact answer ${index + 1}`} maxLength={512} disabled={busy} value={c.expected} onChange={e => patch(index, { expected: e.target.value })} />
          <TextControl label={`Evidence marker ${index + 1} (optional)`} maxLength={512} disabled={busy} value={c.evidence} onChange={e => patch(index, { evidence: e.target.value })} />
        </div>
        <ContextBlockInputs blocks={version.blocks.map(b => ({ key: b.block_key, content: b.content_template, role: b.role, essential: b.priority === 1 }))} value={c.variables} disabled={busy} onChange={value => patch(index, { variables: value })} />
      </Section>)}
      <div data-ui="actions"><Button type="button" disabled={busy || cases.length >= 8} onClick={() => setCases(rows => [...rows, newCase(rows.length + 1)])}>Add experiment case</Button><Button variant="primary" disabled={busy || !version.model_version || !baseline || !name.trim()}>{busy ? 'Running paired inference…' : 'Run measured pair'}</Button></div>
    </form>}
    <div data-ui="field-grid">
      <Select label="Saved context experiment" value={selected} disabled={busy} onChange={e => setSelected(e.target.value)} hint="History shows the loaded first page of accessible experiments. Exact match is scoped to the declared answers; it does not qualify model quality or prompt-injection safety."><option value="">Choose a recorded experiment</option>{experiments.map((e, index) => <option key={e.experiment_id} value={e.experiment_id}>Experiment {index + 1} · {e.name || 'Unavailable inputs'}</option>)}</Select>
    </div>
    {report && <Section level={3} title={report.status === 'unavailable' ? 'Experiment unavailable' : report.name || 'Recorded experiment'} description={report.status === 'unavailable' ? report.reason : report.details?.limits}>
      <KeyValueList columns={2} items={[
        { label: 'Context experiment', value: <Identifier value={report.experiment_id} label="Context experiment ID" display="code" /> },
        ...(report.status === 'unavailable' ? [] : [{ label: 'Frozen case digest', value: <Identifier value={report.details?.cases_digest} label="Frozen case digest" display="code" /> }]),
      ]} />
      {report.status !== 'unavailable' && <>
        <Disclosure summary="Model, tokenizer, decoding and environment pins" variant="quiet"><DataInspector value={{ pins: report.details?.pins, decoding: report.details?.decoding, environment: report.details?.environment, metrics: report.metrics }} /></Disclosure>
        {report.details?.cases?.map(c => <Disclosure key={c.case_id} variant="plain" open summary={`${c.case_id} · ${c.session_key}`}>
          <KeyValueList columns={2} items={[{ label: 'Expected', value: c.expected || '(empty)' }, { label: 'Output changed', value: c.output_changed ? 'Yes' : 'No' }]} />
          <div data-ui="field-grid">{(['baseline', 'candidate'] as const).map(side => { const row = c[side]; return <article key={side} data-ui="form" aria-label={`${side} result for ${c.case_id}`}>
            <div data-ui="actions"><strong>{side === 'baseline' ? 'Baseline' : 'Candidate'}</strong><StatusBadge status={row.status} /></div>
            {row.status === 'failed' ? <Notice tone="error" role="status">{row.reason}</Notice> : <>
              <p className="muted">Exact match: {String(row.exact_match)} · {row.usage?.prompt_tokens} input / {row.usage?.completion_tokens} output tokens · {row.elapsed_seconds?.toFixed(4)} s</p>
              <TextContent text={row.output || '(empty output)'} />
              <Disclosure summary="Exact prompt, evidence retention and omissions" variant="quiet"><TextContent text={row.prompt || ''} /><DataInspector value={{ evidence_retained: row.evidence_retained, omitted: row.omitted_blocks, truncated: row.truncated_blocks }} /></Disclosure>
            </>}
          </article>; })}</div>
        </Disclosure>)}
      </>}
    </Section>}
  </Section>;
}
