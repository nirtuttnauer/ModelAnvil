import { useEffect, useRef, useState, type FormEvent } from 'react';
import { apiPage, apiRequest, authHeaders, errorMessage, getActiveProjectId } from '../api/client';
import { Button, Notice } from '../components/ui';
import { DataInspector } from '../components/DataInspector';
import { ChatResponseContent } from '../components/MarkdownResponse';
import './specialists.css';
import './tools-chat.css';

type Target = { id: string; name: string; kind: string; available: boolean; allowed_tools: string[]; endpoint?: string; reason?: string };
type Catalog = { models: { id: string; name: string }[]; installed_mcp_targets: Target[]; mcp_targets: string[]; code_execution: boolean; sandbox: { available: boolean; reason?: string } };
type Trace = { kind: string; id?: string; name?: string; content?: string; reason?: string; successful?: boolean; [key: string]: unknown };
type Run = { request_id: string; job_id: string; status: string; error?: string; answer?: string; desired_action?: string; attempt_count?: number; trace?: Trace[]; usage?: unknown; trace_artifact?: unknown };

export function ToolsChat({ token, refreshKey = 0 }: { token: string; refreshKey?: number }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null), [model, setModel] = useState('');
  const [targets, setTargets] = useState<string[]>([]), [code, setCode] = useState(false), [schemas, setSchemas] = useState<unknown>(null);
  const [pools, setPools] = useState<{ id: number; name: string }[]>([]), [pool, setPool] = useState('');
  const [policies, setPolicies] = useState<{ policy_id: string; name: string }[]>([]), [budget, setBudget] = useState('');
  const [prompt, setPrompt] = useState('Use add to calculate 17 plus 25, then explain the result.'), [maximum, setMaximum] = useState(128);
  const [runs, setRuns] = useState<Run[]>([]), [selected, setSelected] = useState(''), [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const pending = useRef(false);
  useEffect(() => {
    const c = new AbortController();
    void Promise.all([apiRequest<Catalog>('/api/v1/tools/', token, { signal: c.signal }),
      apiPage<{ id: number; name: string }>('/api/v1/worker-pools/', token, c.signal),
      apiPage<{ policy_id: string; name: string; unit: string; enabled: boolean; currency: string }>('/api/v1/budget-policies/', token, c.signal),
    ]).then(([value, workers, quotas]) => {
      if (c.signal.aborted) return;
      setCatalog(value); setModel(value.models[0]?.id || ''); setPools(workers.results);
      setPolicies(quotas.results.filter(p => p.enabled && p.unit === 'generated_tokens' && !p.currency));
      setTargets(current => current.filter(id => value.mcp_targets.includes(id))); setCode(current => current && value.code_execution);
    }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => c.abort();
  }, [token, refreshKey]);
  useEffect(() => {
    const c = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const rows = await apiRequest<Run[]>('/api/v1/tools/jobs/', token, { signal: c.signal });
        const detail = selected ? await apiRequest<Run>(`/api/v1/tools/jobs/${selected}/`, token, { signal: c.signal }) : null;
        if (!c.signal.aborted) { setRuns(rows); setRun(detail); }
      } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
      if (!c.signal.aborted) timer = setTimeout(poll, 2000);
    }
    void poll(); return () => { c.abort(); clearTimeout(timer); };
  }, [token, selected, refreshKey]);
  async function submit(e: FormEvent) {
    e.preventDefault(); if (pending.current) return; pending.current = true; setBusy(true); setError('');
    try {
      const result = await apiRequest<Run>('/api/v1/tools/jobs/', token, { method: 'POST', body: JSON.stringify({ model, prompt, targets,
        code_execution: code, max_tokens: maximum, pool: Number(pool), budget_policy: budget, idempotency_key: crypto.randomUUID() }) });
      setSelected(result.request_id); setRun(result);
    } catch (e) { setError(errorMessage(e)); } finally { pending.current = false; setBusy(false); }
  }
  async function inspect(id: string) {
    setBusy(true); setError('');
    try { setSchemas(await apiRequest('/api/v1/tools/discover/', token, { method: 'POST', body: JSON.stringify({ target: id }) })); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function download() {
    if (!run) return; setBusy(true); setError('');
    try {
      const headers = authHeaders(token), project = getActiveProjectId(); if (project) headers.set('X-Project-ID', project);
      const response = await fetch(`/api/v1/tools/jobs/${run.request_id}/trace/`, { headers, redirect: 'error' });
      if (!response.ok || !response.headers.get('Content-Type')?.startsWith('application/json')) throw new Error('The trace could not be verified. Reload this run.');
      const blob = await response.blob(); if (blob.size > 1024 * 1024) throw new Error('The trace exceeds its download bound.');
      const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = 'tool-trace.json'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <section data-ui="card" className="ml-page tools-chat">
    <div data-ui="section-header"><div><h2>Tools</h2><p>Let the local model call the tools you select, then continue from their actual results.</p></div></div>
    <div data-ui="form">
      {error && <Notice role="alert" tone="error">{error}</Notice>}
      <p>Three model turns, two tool calls and 1,536 context tokens. MCP targets must be reviewed as read-only. Python runs offline in a disposable container with a read-only image, no host files, one CPU, 128 MiB memory and a five-second limit. Model text cannot grant permissions.</p>
      {!catalog && !error && <p role="status">Loading permitted tools…</p>}
      {catalog && !catalog.models.length && <Notice>No verified tool model is available. Provision the exact Qwen3 CPU profile, then Refresh.</Notice>}
      <form onSubmit={submit} className="tools-form">
        <fieldset disabled={busy || !catalog?.models.length} className="specialist-fields form-grid full-width">
          <label>Tool model<select aria-label="Tool model" required value={model} onChange={e => setModel(e.target.value)}><option value="">Select a model</option>{catalog?.models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
          <label>Worker pool<select aria-label="Worker pool" required value={pool} onChange={e => setPool(e.target.value)}><option value="">Select a CPU tools pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label>Generated-token quota<select aria-label="Generated-token quota" required value={budget} onChange={e => setBudget(e.target.value)}><option value="">Select a quota</option>{policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name}</option>)}</select></label>
          <label>Maximum tokens per turn<input type="number" min={1} max={128} required value={maximum} onChange={e => setMaximum(Number(e.target.value))} /></label>
          <fieldset className="full-width tools-policy"><legend>Allowed tools for this run</legend>
            <p>Project administrators enable targets in <a href="#overview">Privacy and data</a>. Remote MCP sends selected tool arguments to its installed endpoint; credentials stay on the API host. Offline mode blocks remote targets.</p>
            {catalog?.installed_mcp_targets.map(t => <div key={t.id}>
              <label className="tools-check"><input type="checkbox" checked={targets.includes(t.id)} disabled={!t.available || !catalog.mcp_targets.includes(t.id)}
                onChange={e => setTargets(current => e.target.checked ? [...current, t.id] : current.filter(v => v !== t.id))} />{t.name} · {t.allowed_tools.join(', ')}{!catalog.mcp_targets.includes(t.id) ? ' · permission required' : ''}</label>
              {t.endpoint && <p className="muted">{t.endpoint}</p>}
              {t.reason && <p>{t.reason}</p>}
              <Button type="button" disabled={busy || !catalog.mcp_targets.includes(t.id)} onClick={() => void inspect(t.id)}>Inspect {t.name} schemas</Button>
            </div>)}
            <label className="tools-check"><input type="checkbox" checked={code} disabled={!catalog?.code_execution || !catalog.sandbox.available} onChange={e => setCode(e.target.checked)} />Isolated Python{!catalog?.code_execution ? ' · permission required' : ''}</label>
            {!catalog?.sandbox.available && <p>{catalog?.sandbox.reason}</p>}
          </fieldset>
          <label className="full-width">Prompt<textarea required maxLength={2048} rows={3} value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
          <p className="muted full-width">Quota reserves nine turns across possible attempts. Actual generated tokens replace the estimate when verified. A lost tool result is never automatically executed again. Customer quality and other model profiles need separate qualification.</p>
          <Button disabled={busy || !model || !pool || !budget || (!targets.length && !code)}>{busy ? 'Working…' : 'Run tool chat'}</Button>
        </fieldset>
      </form>
      {schemas != null && <details className="detail-box" open><summary>Discovered MCP schemas</summary><DataInspector value={schemas} /></details>}
      <label className="tools-history">Recent tool runs<select aria-label="Recent tool runs" value={selected} onChange={e => setSelected(e.target.value)}><option value="">Select a run</option>{runs.map(r => <option key={r.request_id} value={r.request_id}>{r.request_id.slice(0, 8)} · {r.status}</option>)}</select></label>
      {run && <section aria-label="Tool run result">
        <p role="status">Status: {run.status} · attempts: {run.attempt_count ?? 0}</p>
        {run.error && <Notice tone="error">{run.error}</Notice>}
        {run.answer && <ChatResponseContent text={run.answer} />}
        <div className="actions">
          <Button disabled={busy || !['queued', 'running', 'interrupted'].includes(run.status) || run.desired_action === 'cancel'} onClick={() => {
            setBusy(true); void apiRequest(`/api/v1/tools/jobs/${run.request_id}/cancel/`, token, { method: 'POST', body: '{}' }).catch(e => setError(errorMessage(e))).finally(() => setBusy(false));
          }}>Cancel tool run</Button>
          <Button disabled={busy || !run.trace_artifact} onClick={() => void download()}>Download execution trace</Button>
        </div>
        <ol className="tools-events">{run.trace?.map((event, i) => <li key={i}><strong>{event.kind.replaceAll('_', ' ')}{event.name ? ` · ${event.name}` : ''}</strong>{event.reason && <p>{event.reason}</p>}
          <details><summary>Execution evidence</summary><DataInspector value={event} /></details></li>)}</ol>
        {run.usage != null && <DataInspector value={run.usage} />}
      </section>}
    </div>
  </section>;
}
