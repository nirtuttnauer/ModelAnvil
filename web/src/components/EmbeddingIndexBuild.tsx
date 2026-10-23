import { allResources } from '../api/resources';
import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Card, Field, Notice } from './ui';
import { Identifier } from './Identifier';
interface Source { index_id: string; status: string; revision_no: number; chunk_count: number }
interface Space { space_id: string; name: string; dimension: number }
interface Pool { id: number; name: string; status: string; result_egress: string }
interface Policy { policy_id: string; name: string; unit: string; currency: string; enabled: boolean }
interface Profile { available: boolean; reason: string; model: string; revision: string; dimension: number }
interface Build { build_id: string; index_id: string; job_status: string; index_status: string; completed_chunks: number; total_chunks: number; error: string }
const active = (build: Build) => ['queued', 'running', 'interrupted'].includes(build.job_status);
export function EmbeddingIndexBuild({ token, source, refreshKey, onReady }: { token: string; source?: Source; refreshKey: number; onReady: (id: string) => void }) {
  const [spaces, setSpaces] = useState<Space[]>([]), [pools, setPools] = useState<Pool[]>([]), [policies, setPolicies] = useState<Policy[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null), [builds, setBuilds] = useState<Build[]>([]);
  const [space, setSpace] = useState(''), [pool, setPool] = useState(''), [policy, setPolicy] = useState(''), [name, setName] = useState(''), [accepted, setAccepted] = useState(false);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [retry, setRetry] = useState(0);
  const ready = useRef(new Set<string>()), callback = useRef(onReady); callback.current = onReady;
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(''); setSpaces([]); setBuilds([]);
    Promise.all([apiRequest<Profile>('/api/v1/embedding-spaces/profile/', token, { signal: c.signal }),
      allResources<Space>('/api/v1/embedding-spaces/', token, c.signal), allResources<Pool>('/api/v1/worker-pools/', token, c.signal),
      allResources<Policy>('/api/v1/budget-policies/', token, c.signal), allResources<Build>('/api/v1/embedding-builds/', token, c.signal)])
      .then(([p, s, pools, policies, b]) => { if (!c.signal.aborted) { setProfile(p); setSpaces(s); setPools(pools.filter(p => p.status === 'active' && p.result_egress === 'envelope')); setPolicies(policies.filter(p => p.enabled && p.unit === 'embedding_attempts' && !p.currency)); setBuilds(b); } })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, refreshKey, retry]);
  useEffect(() => {
    if (!builds.some(active)) return;
    const c = new AbortController(); const timer = window.setTimeout(() => { allResources<Build>('/api/v1/embedding-builds/', token, c.signal)
      .then(rows => { if (!c.signal.aborted) { setBuilds(rows); rows.filter(b => b.index_status === 'ready' && !ready.current.has(b.build_id)).forEach(b => { ready.current.add(b.build_id); callback.current(b.index_id); }); } })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }); }, 2000);
    return () => { c.abort(); window.clearTimeout(timer); };
  }, [builds, token]);
  async function register(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const saved = await apiRequest<Space>('/api/v1/embedding-spaces/', token, { method: 'POST', body: JSON.stringify({ name: name.trim(), accepted_license: 'apache-2.0' }) }); setSpaces(rows => [saved, ...rows]); setSpace(saved.space_id); setName(''); setAccepted(false); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function queue(event: React.FormEvent) {
    event.preventDefault(); if (!source) return; setBusy(true); setError('');
    try { const saved = await apiRequest<Build>('/api/v1/embedding-builds/', token, { method: 'POST', body: JSON.stringify({ source_index: source.index_id, space, pool: Number(pool), budget_policy: policy, idempotency_key: crypto.randomUUID() }) }); setBuilds(rows => [saved, ...rows]); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function control(build: Build, action: 'cancel' | 'retry') {
    setBusy(true); setError('');
    try { const saved = await apiRequest<Build>(`/api/v1/embedding-builds/${build.build_id}/${action}/`, token, { method: 'POST', body: '{}' }); setBuilds(rows => rows.map(b => b.build_id === saved.build_id ? saved : b)); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <Card className="panel"><div className="panel-title"><div><h2>Local embedding index</h2><p>Build semantic search from the selected frozen source revision.</p></div><Button disabled={busy || loading} onClick={() => setRetry(v => v + 1)}>Refresh embedding builds</Button></div><div className="panel-body">
    {error && <Notice tone="error" role="alert">{error}</Notice>}{loading && <p role="status">Loading embedding setup…</p>}
    {profile && <><p>{profile.model} · normalized {profile.dimension} dimensional vectors · CPU. Each text must fit 254 content tokens. Builds support up to 1,000 chunks; source data stays on your worker.</p><details><summary>Pinned model revision</summary><Identifier value={profile.revision} label="Embedding model revision" /></details>
      {!profile.available && <Notice tone="caution">{profile.reason} An administrator connects a local CPU embeddings worker through Infrastructure.</Notice>}
      <details><summary>Register a pinned model space</summary><form className="form-grid" onSubmit={register}><label>Embedding space name<Field required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label><label className="checkbox-label"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />I accept the model’s Apache 2.0 license.</label><Button disabled={busy || !profile.available || !name.trim() || !accepted}>Register embedding space</Button></form></details>
      <form className="form-grid" onSubmit={queue}><p className="full-width">{source ? `Selected source: revision ${source.revision_no} · ${source.chunk_count} chunks · ${source.status}. A new revision is published when all vectors are verified.` : 'Select a ready source index above after importing documents.'}</p>
        <label>Embedding space<select required value={space} onChange={e => setSpace(e.target.value)}><option value="">Choose a pinned space</option>{spaces.map(s => <option key={s.space_id} value={s.space_id}>{s.name} · {s.dimension} dimensions</option>)}</select></label>
        <label>Embedding worker pool<select required value={pool} onChange={e => setPool(e.target.value)}><option value="">Choose an active pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Embedding attempt allowance<select required value={policy} onChange={e => setPolicy(e.target.value)}><option value="">Choose an attempt quota</option>{policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.name}</option>)}</select></label>
        <p className="muted full-width">Connect a matching worker in Infrastructure and create an embedding build attempt allowance in Budgets. Three attempts are reserved; only started attempts are charged. Cancellation keeps verified chunks for retry.</p><Button className="primary" disabled={busy || loading || !profile.available || source?.status !== 'ready' || !space || !pool || !policy}>Queue embedding index</Button>
      </form></>}
    {builds.map(build => <article className="detail-box" key={build.build_id}><p role="status">Embedding build · {build.job_status} · {build.completed_chunks} / {build.total_chunks} chunks verified · index {build.index_status}</p><Identifier value={build.build_id} label="Embedding build ID" />{build.error && <p>{build.error}</p>}<div className="actions">{['queued', 'running', 'interrupted'].includes(build.job_status) && <Button disabled={busy} onClick={() => void control(build, 'cancel')}>Cancel embedding build</Button>}{['failed', 'cancelled', 'interrupted'].includes(build.job_status) && <Button disabled={busy} onClick={() => void control(build, 'retry')}>Resume verified build</Button>}{build.index_status === 'ready' && <Button onClick={() => onReady(build.index_id)}>Use ready embedding index</Button>}</div></article>)}
  </div></Card>;
}
