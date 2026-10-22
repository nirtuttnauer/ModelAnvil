import { Identifier, isOpaqueIdentifier } from '../components/Identifier';
import { Badge, Button, Card, Field, MultilineField, Notice } from '../components/ui';
import { ObjectFields, RecordListEditor } from '../components/FormEditors';
import { readRecords, recordsInput, sampleFields, spanFields, structuredInput } from '../components/form-data';
import { resourceHash, handoffHash } from '../api/resource-routes';
import { useResourceHandoff } from '../components/ResourceHandoff';
import { DataInspector } from '../components/DataInspector';
import { useDraft, DraftStatus } from '../components/Draft';
import { useEffect, useRef, useState } from 'react';
import { ApiRequestError, apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { allResources, downloadJson, type RegisteredModel } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import { BarChart, ChartPanel, LineChart, SegmentBar } from '../components/Charts';
import { initialLabel, matchesQueue, nextPending, parseSamples, preferenceLabels, validLabel, validateSamples, type AnnotationTask as Task, type Review } from '../api/annotation';
import './data-workspace.css';
import './annotation.css';

interface Batch { batch_id: string; cycle_no: number; status: string; sample_count: number; reviewed_count: number; approved_count: number; drafting_model_id: string | null }
interface Snapshot { dataset_revision_id?: string | null; snapshot_id: string; cycle_no: number; item_count: number; manifest_digest: string }
interface Campaign {
  configuration?: { source_revision?: string; protected_source_groups?: string[]; audit_sample_refs?: string[] }; campaign_id: string; name: string; status: string; seed_mode: string; current_cycle: number; max_cycles: number;
  budget_limit_dollars: number; accumulated_cost_dollars: number; active_model_id: string | null;
  label_schema: { kind: string; classes: string[] }; rubric: { guidelines_text: string } | null;
  batches: Batch[]; snapshots: Snapshot[];
}
function spanRows(raw: string): boolean {
  try { return readRecords(raw).every(row => Object.keys(row).every(key => ['start', 'end', 'label'].includes(key))); }
  catch { return false; }
}
export function AnnotationPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const selectionDraft = useDraft('annotation-selection', { campaignId: new URLSearchParams(window.location.hash.split('?')[1]).get('campaign') || '', batchId: '', taskId: '', blindReview: false as boolean, autoAdvance: true as boolean });
  const [campaignId, setCampaignId] = selectionDraft.field('campaignId');
  const [batchId, setBatchId] = selectionDraft.field('batchId');
  const [queue, setQueue] = useState<{ key: string; tasks: Task[] }>({ key: '', tasks: [] });
  const [blindReview, setBlindReview] = selectionDraft.field('blindReview');
  const [autoAdvance, setAutoAdvance] = selectionDraft.field('autoAdvance');
  const queueKey = `${batchId}:${blindReview}`;
  const tasks = queue.key === queueKey ? queue.tasks : [];
  function setTasks(update: (current: Task[]) => Task[]) { setQueue(current => current.key === queueKey ? { ...current, tasks: update(current.tasks) } : current); }
  const [taskId, setTaskId] = selectionDraft.field('taskId');
  const [history, setHistory] = useState<Review[] | null>(null);
  const [historyNext, setHistoryNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [queueLoading, setQueueLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const [queueRetry, setQueueRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const editorRef = useRef<HTMLElement>(null);
  const [conflict, setConflict] = useState(false);
  const [openImportId, setOpenImportId] = useState('');
  const [search, setSearch] = useState('');
  const draft = useDraft('annotation-campaign', { setup: false as boolean, name: '', kind: 'classification', classes: 'positive, negative', guidelines: '', seed: 'manual', model: '', cycles: '3', budget: '100', auditRefs: '', sourceRevision: '' });
  const [setup, setSetup] = draft.field('setup');
  const [name, setName] = draft.field('name');
  const [kind, setKind] = draft.field('kind');
  const [classes, setClasses] = draft.field('classes');
  const [guidelines, setGuidelines] = draft.field('guidelines');
  const [seed, setSeed] = draft.field('seed');
  const [model, setModel] = draft.field('model');
  const [cycles, setCycles] = draft.field('cycles');
  const [budget, setBudget] = draft.field('budget');
  const [auditRefs, setAuditRefs] = draft.field('auditRefs');
  const batchDraft = useDraft('annotation-batch', { samples: '', importOpen: false as boolean }, campaignId);
  const [samples, setSamples] = batchDraft.field('samples');
  const [sourceRevision, setSourceRevision] = draft.field('sourceRevision');
  const [revisions, setRevisions] = useState<{ revision_id: string; dataset_name: string; revision_no: number; state: string }[]>([]);
  const [batchLimit, setBatchLimit] = useState('100');
  const [reviewers, setReviewers] = useState<{ principal_id: string; name: string }[]>([]);
  const [assignmentAllowed, setAssignmentAllowed] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => { const change = () => setOnline(navigator.onLine); window.addEventListener('online', change); window.addEventListener('offline', change); return () => { window.removeEventListener('online', change); window.removeEventListener('offline', change); }; }, []);
  useEffect(() => { const c = new AbortController(); allResources<typeof revisions[number]>('/api/v1/dataset-revisions/', token, c.signal).then(rows => { if (!c.signal.aborted) setRevisions(rows.filter(r => r.state === 'published')); }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }); return () => c.abort(); }, [token, refreshKey]);
  const handoffError = useResourceHandoff(token, (kind, value) => { if (kind === 'dataset-revision') { setSourceRevision(value.revision_id || ''); setSetup(true); } });
  const [importOpen, setImportOpen] = batchDraft.field('importOpen');
  const [queueFilter, setQueueFilter] = useState('all');
  const campaign = campaigns.find(c => c.campaign_id === campaignId);
  const sourceFields = sampleFields;
  const batch = campaign?.batches.find(b => b.batch_id === batchId);
  const task = batch ? tasks.find(t => t.task_id === taskId) : undefined;
  const reviewDraft = useDraft('annotation-review', { label: !blindReview && task ? initialLabel(task) : '', revision: task?.latest_review?.revision_no || 0 }, `${taskId}:${blindReview ? 'blind' : 'assisted'}`);
  const [label, setLabel] = reviewDraft.field('label');
  const canReview = !!task && !queueLoading && online && campaign?.status === 'active' && !!batch && batch.status !== 'closed';
  const staleDraft = !!task && reviewDraft.field('revision')[0] !== (task.latest_review?.revision_no || 0);
  const labelValid = !!campaign && validLabel(campaign.label_schema, label);
  const reviewBlocked = busy || !canReview || staleDraft || conflict || !!task?.needs_adjudication;
  const taskPath = task ? `/api/v1/annotation-tasks/${task.task_id}/` : '';
  const blindQuery = blindReview ? '?blind=1' : '';
  const pendingCount = tasks.filter(t => !t.latest_review && !t.needs_adjudication).length;
  const flaggedCount = tasks.filter(t => t.needs_adjudication).length;

  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null); setCampaigns([]); setModels([]);
    Promise.all([allResources<Campaign>('/api/v1/labeling-campaigns/', token, controller.signal), allResources<RegisteredModel>('/api/v1/model-versions/', token, controller.signal)])
      .then(([c, m]) => { if (!controller.signal.aborted) { setCampaigns(c); setModels(m); setCampaignId(current => c.some(item => item.campaign_id === current) ? current : c[0]?.campaign_id || ''); } })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refreshKey, retry]);

  useEffect(() => {
    if (!campaign) return;
    setBatchId(current => campaign.batches.some(b => b.batch_id === current) ? current : [...campaign.batches].sort((a, b) => b.cycle_no - a.cycle_no)[0]?.batch_id || '');
  }, [campaign]);

  useEffect(() => {
    const controller = new AbortController(); setHistory(null); setHistoryNext(null);
    if (!batch) return () => controller.abort();
    setQueueLoading(true);
    allResources<Task>(`/api/v1/labeling-batches/${batchId}/tasks/${blindQuery}`, token, controller.signal)
      .then(rows => { if (!controller.signal.aborted) {
        setQueue({ key: queueKey, tasks: rows });
        setTaskId(current => rows.some(t => t.task_id === current) ? current : rows.find(t => !t.latest_review && !t.needs_adjudication)?.task_id || rows[0]?.task_id || '');
      } })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setQueueLoading(false); });
    return () => controller.abort();
  }, [batchId, !!batch, token, refreshKey, queueRetry, blindReview]);

  useEffect(() => { setHistory(null); setHistoryNext(null); setConflict(false); }, [taskId, batchId, blindReview]);

  async function mutate<T>(path: string, body: unknown, success: (result: T) => void) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null); setNotice('');
    try { success(await apiRequest<T>(path, token, { method: 'POST', body: JSON.stringify(body) })); }
    catch (e) { setError(errorMessage(e)); }
    finally { busyRef.current = false; setBusy(false); }
  }
  function updateCampaign(value: Campaign) { setCampaigns(current => current.map(c => c.campaign_id === value.campaign_id ? value : c)); }
  function selectCampaign(id: string) { setCampaignId(id); setBatchId(''); setTaskId(''); setQueueFilter('all'); setSearch(''); setError(null); setNotice(''); setImportOpen(false); window.history.replaceState(null, '', `#annotation${id ? `?campaign=${id}` : ''}`); }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    await mutate<Campaign>('/api/v1/labeling-campaigns/', {
      name, kind, ...(sourceRevision ? { source_revision: sourceRevision } : {}), classes: kind === 'classification' ? classes.split(',').map(v => v.trim()).filter(Boolean) : [],
      guidelines, seed_mode: seed, drafting_model_id: seed === 'existing_model' ? model : null,
      max_cycles: Number(cycles), budget_limit_dollars: Number(budget), audit_sample_refs: auditRefs.split('\n').map(v => v.trim()).filter(Boolean),
    }, c => { draft.discard(); setCampaigns(current => [c, ...current]); selectCampaign(c.campaign_id); setSetup(false); setName(''); setOpenImportId(c.campaign_id); setNotice('Campaign created. Add source samples to begin review.'); });
  }
  useEffect(() => { if (openImportId && campaignId === openImportId) { setImportOpen(true); setOpenImportId(''); } }, [campaignId, openImportId]);
  async function importBatch(e: React.FormEvent) {
    e.preventDefault(); if (!campaign) return;
    let parsed: unknown;
    if (!campaign.configuration?.source_revision) try { parsed = recordsInput(samples, sourceFields, 500, 'id'); validateSamples(parsed as Record<string, unknown>[], campaign.label_schema, campaign.active_model_id, campaign.configuration?.audit_sample_refs); }
    catch (e) { setError(errorMessage(e)); return; }
    await mutate<Batch>(`/api/v1/labeling-campaigns/${campaign.campaign_id}/batches/`, campaign.configuration?.source_revision ? { limit: Number(batchLimit) } : { samples: parsed }, b => {
      batchDraft.discard(); updateCampaign({ ...campaign, batches: [...campaign.batches, b] }); setBatchId(b.batch_id); setSamples(''); setImportOpen(false); setNotice(`Cycle ${b.cycle_no} opened with ${b.sample_count} samples.`);
    });
  }
  async function review(decision: string, adjudicate = false) {
    if (!task || !campaign || !batch || busyRef.current || !canReview || staleDraft || conflict || (task.needs_adjudication && !adjudicate)) return;
    if (!['skipped', 'rejected'].includes(decision) && !labelValid) { setError('Choose a valid label before saving.'); return; }
    let value: unknown = label;
    if (decision !== 'skipped' && decision !== 'rejected' && ['ner_span', 'rubric_scoring'].includes(campaign.label_schema.kind)) {
      try {
        value = campaign.label_schema.kind === 'ner_span' && spanRows(label) ? recordsInput(label, spanFields, Infinity) : structuredInput(label);
        if (campaign.label_schema.kind === 'ner_span' && Array.isArray(value) && value.some(span => typeof span.start === 'number' && typeof span.end === 'number' && span.end <= span.start)) throw new Error('Each entity span must end after it starts.');
      } catch (e) { setError(errorMessage(e)); return; }
    }
    busyRef.current = true; setBusy(true); setError(null); setNotice('');
    try {
      const updated = await apiRequest<Task>(`${taskPath}review/${blindQuery}`, token, { method: 'POST', body: JSON.stringify({
        decision, blind_review: blindReview, adjudicate, human_label: ['skipped', 'rejected'].includes(decision) ? {} : { label: value }, expected_revision: reviewDraft.field('revision')[0] + 1,
      }) });
      reviewDraft.discard(); setTasks(current => current.map(t => t.task_id === updated.task_id ? updated : t));
      updateCampaign({ ...campaign, batches: campaign.batches.map(b => b.batch_id === batch.batch_id ? { ...b, reviewed_count: b.reviewed_count + (task.latest_review ? 0 : 1) } : b) });
      if (autoAdvance && !updated.needs_adjudication) {
        const remaining = tasks.map(t => t.task_id === updated.task_id ? updated : t);
        const next = nextPending(remaining, task.task_id);
        if (next) { setTaskId(next); requestAnimationFrame(() => editorRef.current?.focus({ preventScroll: true })); }
      }
      setNotice(updated.needs_adjudication ? `Review saved for ${sampleName(task)}. A manager must resolve the disagreement.` : `Review saved for ${sampleName(task)}.`);
    } catch (e) {
      setError(errorMessage(e));
      if (e instanceof ApiRequestError && e.status === 409) {
        setConflict(true);
        try {
          const latest = await apiRequest<Task>(`${taskPath}${blindQuery}`, token);
          setTasks(current => current.map(t => t.task_id === latest.task_id ? latest : t));
        } catch { /* Retain the draft and require an explicit refresh before retrying. */ }
      }
    } finally { busyRef.current = false; setBusy(false); }
  }
  async function importFile(file: File) {
    if (!campaign || busyRef.current) return;
    if (file.size > 1_000_000) { setError('Choose a JSON or JSONL file smaller than 1 MB, with up to 500 samples.'); return; }
    busyRef.current = true; setBusy(true); setError(null);
    try {
      const added = parseSamples(await file.text());
      const existing = samples.trim() ? recordsInput(samples, sourceFields, 500, 'id') : [];
      const combined = [...existing, ...added];
      validateSamples(combined, campaign.label_schema, campaign.active_model_id, campaign.configuration?.audit_sample_refs);
      setSamples(JSON.stringify(combined));
      setNotice(`${added.length} samples added from ${file.name}. Review them before opening the batch.`);
    } catch (e) { setError(errorMessage(e)); }
    finally { busyRef.current = false; setBusy(false); }
  }
  useEffect(() => {
    const c = new AbortController(); setReviewers([]); setAssignmentAllowed(false);
    if (taskId) apiRequest<{ reviewers: typeof reviewers }>(`/api/v1/annotation-tasks/${taskId}/assignment/`, token, { signal: c.signal }).then(result => { if (!c.signal.aborted) { setReviewers(result.reviewers); setAssignmentAllowed(true); } }).catch(() => {});
    return () => c.abort();
  }, [taskId, token]);
  async function closeBatch() {
    if (!campaign || !batch) return;
    await mutate<Snapshot>(`/api/v1/labeling-batches/${batch.batch_id}/close/`, {}, s => {
      setNotice(`Cycle ${s.cycle_no} closed. Immutable cumulative snapshot: ${s.item_count} approved items.`);
      setRetry(v => v + 1); setQueueRetry(v => v + 1);
    });
  }
  async function refreshLatest() {
    if (!task || !campaign || busyRef.current) return;
    busyRef.current = true; setBusy(true); setError(null);
    try {
      const [latest, currentCampaign] = await Promise.all([
        apiRequest<Task>(`${taskPath}${blindQuery}`, token),
        apiRequest<Campaign>(`/api/v1/labeling-campaigns/${campaign.campaign_id}/`, token),
      ]);
      setTasks(current => current.map(t => t.task_id === latest.task_id ? latest : t));
      updateCampaign(currentCampaign); setConflict(false);
    } catch (e) { setError(errorMessage(e)); }
    finally { busyRef.current = false; setBusy(false); }
  }
  async function loadHistory(more = false) {
    if (!task) return;
    setBusy(true); setError(null);
    try {
      const path = `${taskPath}history/${blindQuery}`;
      const page = await apiPage<Review>(more && historyNext ? nextPagePath(historyNext, path) : path, token);
      setHistory(current => more ? [...current || [], ...page.results] : page.results); setHistoryNext(page.next || null);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function exportSnapshot(snapshot: Snapshot) {
    setBusy(true); setError(null);
    try { await downloadJson(`/api/v1/annotation-snapshots/${snapshot.snapshot_id}/export/`, token, `labels-cycle-${snapshot.cycle_no}.json`); }
    catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  function sampleName(item: Task) { return isOpaqueIdentifier(item.sample_ref) ? `Sample ${tasks.findIndex(row => row.task_id === item.task_id) + 1}` : item.sample_ref; }
  const visibleTasks = tasks.filter(t => matchesQueue(t, queueFilter, search) || (isOpaqueIdentifier(t.sample_ref) && matchesQueue(t, queueFilter) && sampleName(t).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())));

  const taskIndex = visibleTasks.findIndex(t => t.task_id === taskId);
  function navigate(direction: number) {
    const next = visibleTasks[taskIndex + direction];
    if (next && !busy) setTaskId(next.task_id);
  }
  function reviewKeys(e: React.KeyboardEvent<HTMLElement>) {
    if (e.repeat || busy) return;
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault(); if (!reviewBlocked && labelValid) void review('corrected'); return;
    }
    if (e.altKey && ['ArrowLeft', 'ArrowRight'].includes(e.key)) {
      e.preventDefault(); navigate(e.key === 'ArrowLeft' ? -1 : 1); return;
    }
    const target = e.target as HTMLElement;
    if (e.ctrlKey || e.metaKey || e.altKey || target.closest('input, textarea, select, button, [contenteditable="true"]')) return;
    const options = campaign?.label_schema.kind === 'classification' ? campaign.label_schema.classes : campaign?.label_schema.kind === 'preference_ranking' ? preferenceLabels : [];
    const number = Number(e.key);
    if (!reviewBlocked && /^[1-9]$/.test(e.key) && options[number - 1]) { e.preventDefault(); setLabel(options[number - 1]); }
  }

  return <Card className="panel annotation-page">
    <div className="panel-title"><div><h2>Annotation review</h2><p>Review source evidence, refine labels, and freeze approved snapshots.</p></div><Button className="primary" disabled={loading || busy} onClick={() => setSetup(v => !v)}>{setup ? 'Close setup' : 'New campaign'}</Button></div>
    <div className="panel-body">
      <>{handoffError && <p role="alert">{handoffError}</p>}{!online && <p role="status">Offline. Your edits stay in this tab; reconnect before saving a review.</p>}</><ResourceState loading={loading} error={error} onRetry={() => { setRetry(v => v + 1); setQueueRetry(v => v + 1); }} />
      {notice && <Notice tone="success" className="notice success" role="status">{notice}</Notice>}
      {(!campaign || setup) && <ol className="flow-steps annotation-workflow" aria-label="Labeling workflow"><li>1. Set up campaign</li><li>2. Add source batch</li><li>3. Review labels</li><li>4. Close & export</li></ol>}
      {setup && <form className="form-grid" onSubmit={create}><DraftStatus draft={draft} disabled={busy} />
        <label>Published source revision<select value={sourceRevision} onChange={e => setSourceRevision(e.target.value)}><option value="">Manual source samples</option>{revisions.map((r, index) => <option key={r.revision_id} value={r.revision_id} disabled={kind === 'preference_ranking'}>{r.dataset_name || `Dataset ${index + 1}`}  · r{r.revision_no}</option>)}</select></label>
        <label>Campaign name<Field required maxLength={180} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Label schema<select value={kind} onChange={e => setKind(e.target.value)}><option value="classification">Classification</option><option value="text_generation">Text response</option><option value="preference_ranking" disabled={!!sourceRevision}>Preference ranking (manual source samples)</option><option value="ner_span" disabled>Entity spans</option><option value="rubric_scoring" disabled>Rubric scoring</option></select></label>
        <p className="muted full-width">Preference ranking uses manual source samples with both candidate responses and an optional prompt.</p>
        {kind === 'classification' && <label className="full-width">Class labels, separated by commas<Field required value={classes} onChange={e => setClasses(e.target.value)} /></label>}
        <label>Seed mode<select value={seed} onChange={e => setSeed(e.target.value)}><option value="manual">Manual labeling</option><option value="existing_model">Review imported model drafts</option></select></label>
        {seed === 'existing_model' && <label>Drafting model version<select required value={model} onChange={e => setModel(e.target.value)}><option value="">Select a pinned version</option>{models.map(m => <option key={m.id} value={m.model_version_id}>{m.model_name} · r{m.revision_no}</option>)}</select></label>}
        <label className="full-width">Review guidelines<MultilineField rows={3} value={guidelines} onChange={e => setGuidelines(e.target.value)} placeholder="Describe how reviewers should choose or correct each label." /></label>
        <details className="annotation-setup-section full-width"><summary>Cycle limits, budget & protected samples</summary><div className="form-grid"><label>Cycle limit<Field type="number" min="1" max="100" required value={cycles} onChange={e => setCycles(e.target.value)} /></label>
        <label>Budget ceiling (USD)<Field type="number" min="0" max="1000000" step="0.01" required value={budget} onChange={e => setBudget(e.target.value)} /></label>
        <label className="full-width">Protected audit sample IDs (one per line)<MultilineField rows={2} value={auditRefs} onChange={e => setAuditRefs(e.target.value)} placeholder="These IDs will be excluded from source batches." /></label></div></details>
        <p className="muted full-width">{sourceRevision && seed === 'existing_model' && 'Published-source batches start with manual labels; selecting a model does not generate predictions. '}Samples without imported predictions can be labeled manually. Imported drafts must carry the selected model version ID. Automatic model inference and retraining are not connected yet. The budget ceiling records campaign intent; this review flow incurs no executor spend.</p>
        <div className="actions full-width"><Button className="primary" disabled={busy || !online || (kind === 'preference_ranking' && !!sourceRevision) || (seed === 'existing_model' && !model)}>{busy ? 'Creating…' : 'Create campaign'}</Button></div>
      </form>}
      {!loading && !error && !campaigns.length && !setup && <div className="empty-state"><h3>Start your first labeling campaign</h3><p>Create a label schema and review guidelines, then import samples from your source pool.</p><Button onClick={() => setSetup(true)}>Set up labeling</Button></div>}
      <div className="annotation-toolbar">{!!campaigns.length && <div className="campaign-picker"><div className="identifier-label"><label htmlFor="annotation-campaign-picker">Campaign</label><Identifier value={campaignId} label="Campaign ID" /></div><select id="annotation-campaign-picker" value={campaignId} disabled={busy} onChange={e => selectCampaign(e.target.value)}><option value="">Select a campaign</option>{campaigns.map(c => <option key={c.campaign_id} value={c.campaign_id}>{c.name} · {c.status} · cycle {c.current_cycle}/{c.max_cycles}</option>)}</select></div>}
        {!!campaign?.batches.length && <div className="campaign-picker"><div className="identifier-label"><label htmlFor="annotation-batch-picker">Batch</label><Identifier value={batchId} label="Batch ID" /></div><select id="annotation-batch-picker" value={batchId} disabled={busy} onChange={e => setBatchId(e.target.value)}>{[...campaign.batches].sort((a, b) => b.cycle_no - a.cycle_no).map(b => <option key={b.batch_id} value={b.batch_id}>Cycle {b.cycle_no} · {b.status} · {b.reviewed_count}/{b.sample_count} reviewed</option>)}</select></div>}
      {campaign && <details className="annotation-campaign-details"><summary>Campaign settings & limits</summary><div className="campaign-summary"><div><h3>{campaign.name} <Badge className={`state state-${campaign.status}`}>{campaign.status}</Badge></h3><p>{campaign.label_schema.kind.replaceAll('_', ' ')} · {campaign.seed_mode === 'manual' ? 'Manual seed' : 'Imported model drafts'} · {campaign.current_cycle}/{campaign.max_cycles} cycles closed</p><small>Recorded spend ${campaign.accumulated_cost_dollars.toFixed(2)} / ${campaign.budget_limit_dollars.toFixed(2)} ceiling</small></div>
          <div className="actions">{['active', 'paused'].includes(campaign.status) && <Button disabled={busy} onClick={() => void mutate<Campaign>(`/api/v1/labeling-campaigns/${campaign.campaign_id}/lifecycle/`, { transition: campaign.status === 'paused' ? 'resume' : 'pause' }, updateCampaign)}>{campaign.status === 'paused' ? 'Resume campaign' : 'Pause campaign'}</Button>}
          </div>
        </div>
        </details>}
      </div>
      {campaign && <>
        {(importOpen || !campaign.batches.some(b => b.status !== 'closed') || campaign.status === 'paused') && <div className="actions annotation-batch-actions"><Button className="primary" disabled={busy || campaign.status !== 'active' || campaign.batches.some(b => b.status !== 'closed')} onClick={() => setImportOpen(v => !v)}>{importOpen ? 'Close import' : 'Add source batch'}</Button>{campaign.status === 'paused' && <Button disabled={busy || !online} onClick={() => void mutate<Campaign>(`/api/v1/labeling-campaigns/${campaign.campaign_id}/lifecycle/`, { transition: 'resume' }, updateCampaign)}>Resume campaign</Button>}</div>}
        {importOpen && <form className="form-grid" onSubmit={importBatch}><DraftStatus draft={batchDraft} disabled={busy} />{campaign.configuration?.source_revision ? <><a href={resourceHash('dataset-revision', campaign.configuration.source_revision)}>Inspect pinned source revision</a><label>Eligible samples in next batch<Field type="number" required min="1" max="500" value={batchLimit} onChange={e => setBatchLimit(e.target.value)} /></label><p className="muted">Protected source groups and previously reviewed samples are excluded by the server. Pinned-source batches start with manual labels; upload samples with predictions in a separate manual-source campaign to review model drafts.</p></> : <><div className="annotation-import-file full-width"><h3>Import source samples</h3><p>Choose a JSON array or JSONL file, or add samples below. Imported samples are appended to your current draft.</p><label>Sample file (JSON or JSONL, up to 1 MB)<Field type="file" accept=".json,.jsonl,.ndjson,application/json,application/x-ndjson" disabled={busy} onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void importFile(file); }} /></label><details><summary>Sample format</summary><pre>{JSON.stringify({ id: 'sample-1', ...(campaign.label_schema.kind === 'preference_ranking' ? { prompt: 'Question to compare', candidate_a: 'First response', candidate_b: 'Second response' } : { text: 'Source content to label' }), ...(campaign.active_model_id ? { draft_prediction: { predicted_label: campaign.label_schema.kind === 'classification' ? campaign.label_schema.classes[0] : campaign.label_schema.kind === 'preference_ranking' ? 'candidate_a' : 'Draft response', model_version_id: campaign.active_model_id } } : {}) }, null, 2)}</pre></details></div><RecordListEditor title="Source samples" itemName="Sample" fields={sourceFields} maximum={500} uniqueKey="id" value={samples} onChange={setSamples} disabled={busy} description="Add a unique ID and source content for each sample. Fill the fields that apply to your review task." /></>}<p className="muted full-width">Up to 500 samples per cycle. Each needs a unique id. Text and classification tasks need nonempty text, prompt, or input. Preference tasks need both candidate responses; a prompt is optional. Protected audit IDs, evaluation splits, and reused inputs are rejected.{campaign.active_model_id && <> Imported predictions must include the predicted label and pinned model version: <Identifier value={campaign.active_model_id} label="Drafting model version ID" />.</>}</p><Button className="primary" disabled={busy || !online || campaign.status !== 'active' || (!campaign.configuration?.source_revision && !samples.trim())}>Open review batch</Button></form>}

        {batch && <>
          <div className="actions queue-summary"><strong>{batch.reviewed_count} / {batch.sample_count} reviewed</strong><progress value={batch.reviewed_count} max={batch.sample_count || 1} aria-label="Batch review progress" /><Badge className={`state state-${batch.status}`}>{batch.status}</Badge>{batch.status !== 'closed' && <Button className="primary" disabled={busy || !online || campaign.status !== 'active' || queueLoading || tasks.length !== batch.sample_count || batch.reviewed_count !== batch.sample_count || flaggedCount > 0} onClick={() => void closeBatch()}>Close batch & freeze snapshot</Button>}</div>
          <p className="muted">{flaggedCount > 0 && `${flaggedCount} samples need manager adjudication before closing. `}Closing freezes approved labels. Rejected and skipped samples are excluded. Later cycles append to the cumulative snapshot.</p>
          <ResourceState loading={queueLoading} />
          {!queueLoading && tasks.length === batch.sample_count && batch.reviewed_count === batch.sample_count && !flaggedCount && batch.status !== 'closed' && <Notice tone="success" className="annotation-completion"><strong>Batch ready to close</strong><p>Every sample has a decision. Close the batch above to freeze approved labels and create a training snapshot.</p></Notice>}
          <div className="annotation-workspace premium-review-workspace">
            <section className="review-queue" aria-label="Review queue"><div className="annotation-queue-tools"><h3>Review queue</h3>
              <label className="annotation-toggle"><input type="checkbox" disabled={busy || queueLoading} checked={blindReview} onChange={e => setBlindReview(e.target.checked)} />Independent review · hide predictions</label>
              <label>Find sample<Field type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search IDs or source text" /></label>
              <label>Show samples<select value={queueFilter} onChange={e => setQueueFilter(e.target.value)}><option value="all">All samples ({tasks.length})</option><option value="pending">Awaiting review ({pendingCount})</option><option value="reviewed">Reviewed ({tasks.filter(t => t.latest_review).length})</option><option value="flagged">Needs adjudication ({flaggedCount})</option><option value="skipped">Skipped ({tasks.filter(t => t.latest_review?.decision === 'skipped').length})</option></select></label>
              {blindReview && <p className="muted">Predictions and previous labels are hidden. Earlier exposure cannot be undone.</p>}<p className="annotation-queue-count">{visibleTasks.length} of {tasks.length} samples</p></div><div className="annotation-queue-list">
              {visibleTasks.map(t => <div className="annotation-queue-row" key={t.task_id}><Button disabled={busy} aria-current={taskId === t.task_id ? 'true' : undefined} className={`queue-item ${taskId === t.task_id ? 'selected' : ''}`} onClick={() => setTaskId(t.task_id)}><strong>{sampleName(t)}</strong><span>{t.needs_adjudication ? 'Needs adjudication' : t.latest_review ? t.latest_review.decision.replaceAll('_', ' ') : 'Awaiting review'}</span></Button><Identifier value={t.sample_ref} label="Source sample ID" /></div>)}
              {!queueLoading && !visibleTasks.length && <p className="muted">No samples match this filter.{(search || queueFilter !== 'all') && <Button onClick={() => { setSearch(''); setQueueFilter('all'); }}>Clear filters</Button>}</p>}
              </div>
            </section>
            {task && <section ref={editorRef} tabIndex={-1} aria-label={`Review sample ${sampleName(task)}`} className="review-editor" onKeyDown={reviewKeys}>
              <div className="annotation-review-toolbar"><div className="actions"><Button aria-label="Previous sample" disabled={busy || taskIndex <= 0} onClick={() => navigate(-1)}>Previous</Button><span>{taskIndex >= 0 ? `${taskIndex + 1} of ${visibleTasks.length}` : 'Outside current filter'}</span><Button aria-label="Next sample" disabled={busy || taskIndex >= visibleTasks.length - 1} onClick={() => navigate(1)}>Next</Button></div><label className="annotation-toggle"><input type="checkbox" disabled={busy} checked={autoAdvance} onChange={e => setAutoAdvance(e.target.checked)} />Next awaiting sample after save</label></div>
              <div className="annotation-source"><div className="annotation-section-title"><h3>{isOpaqueIdentifier(task.sample_ref) ? sampleName(task) : `Sample ${task.sample_ref}`} <Identifier value={task.sample_ref} label="Source sample ID" /><Identifier value={task.task_id} label="Annotation task ID" /></h3><Badge>{task.latest_review ? task.latest_review.decision.replaceAll('_', ' ') : 'Awaiting review'}</Badge></div>{campaign.rubric && <details open><summary>Review guidelines</summary><p className="preserve-lines">{campaign.rubric.guidelines_text}</p></details>}
              <div className="annotation-source-blocks">{Object.entries(task.content).filter(([key]) => !['draft_prediction', 'id'].includes(key)).map(([key, value]) => <article className="annotation-content-block" key={key}><Badge className="badge">{key.replaceAll('_', ' ')}</Badge>{typeof value === 'string' ? isOpaqueIdentifier(value) ? <Identifier value={value} label={key.replaceAll('_', ' ')} /> : <p className="preserve-lines">{value}</p> : <DataInspector value={value} />}</article>)}</div>
              {!blindReview && task.content.draft_prediction && <details open><summary>Original imported prediction</summary><DataInspector value={task.content.draft_prediction} /></details>}
              </div><div className="annotation-decision"><DraftStatus draft={reviewDraft} disabled={busy || !canReview} /><h3>Review annotation</h3><details className="annotation-shortcuts"><summary>Keyboard shortcuts</summary><p>1–9 selects a label when the review panel is focused. Ctrl/⌘ + Enter saves. Alt + Left/Right moves between samples. Radio labels support arrow keys.</p></details>
              {task.needs_adjudication && <p role="alert">This task has an escalated or conflicting review. A manager must adjudicate before this batch can close.</p>}
              {(staleDraft || conflict) && <Notice className="notice"><p role="alert">Your draft was based on an older review. Inspect the latest record before submitting.</p><Button disabled={busy} onClick={() => void refreshLatest()}>Refresh latest review</Button>{!blindReview && <DataInspector value={task.latest_review?.human_label || {}} />}<Button disabled={busy || conflict} onClick={() => reviewDraft.field('revision')[1](task.latest_review?.revision_no || 0)}>Keep my label against latest revision</Button><Button disabled={busy || conflict} onClick={() => reviewDraft.discard()}>Discard my draft & use latest</Button></Notice>}
              {assignmentAllowed && <label>Assigned reviewer<select disabled={busy || !canReview} value={task.assigned_reviewer || ''} onChange={e => void mutate<Task>(`${taskPath}assignment/${blindQuery}`, { reviewer: e.target.value }, updated => setTasks(current => current.map(t => t.task_id === updated.task_id ? updated : t)))}><option value="">Any authorized reviewer</option>{reviewers.map(r => <option key={r.principal_id} value={r.principal_id}>{r.name}</option>)}</select></label>}
              {['ner_span', 'rubric_scoring'].includes(campaign.label_schema.kind) && <p role="status">Review existing entity spans and rubric scores here. Publishing these schemas as training datasets is unavailable.</p>}<p className="muted">{campaign.label_schema.kind.replaceAll('_', ' ')} · revision {(task.latest_review?.revision_no || 0) + 1}</p>
              {['classification', 'preference_ranking'].includes(campaign.label_schema.kind) ? <fieldset className="annotation-label-options" disabled={busy || !canReview}><legend>Human label</legend>{(campaign.label_schema.kind === 'classification' ? campaign.label_schema.classes : preferenceLabels).map((value, index) => <label className={`annotation-label-option ${label === value ? 'selected' : ''}`} key={value}><input type="radio" name={`label-${task.task_id}`} value={value} checked={label === value} onChange={() => setLabel(value)} /><span>{value.replaceAll('_', ' ')}</span>{index < 9 && <kbd className="annotation-label-number">{index + 1}</kbd>}</label>)}</fieldset> : campaign.label_schema.kind === 'ner_span' && spanRows(label) ? <RecordListEditor title="Entity spans" itemName="Entity span" fields={spanFields} value={label} onChange={setLabel} disabled={busy || !canReview} description="Use zero-based character positions. Each end position must follow its start." /> : ['ner_span', 'rubric_scoring'].includes(campaign.label_schema.kind) ? <ObjectFields title={campaign.label_schema.kind === 'ner_span' ? "Entity labels" : "Rubric scores"} value={label} onChange={setLabel} disabled={busy || !canReview} nameLabel={campaign.label_schema.kind === 'rubric_scoring' ? "Criterion" : "Field name"} valueLabel={campaign.label_schema.kind === 'rubric_scoring' ? "Score" : "Value"} defaultKind={campaign.label_schema.kind === 'rubric_scoring' ? 'number' : 'text'} /> : <label>Human label<MultilineField disabled={busy || !canReview} rows={7} value={label} onChange={e => setLabel(e.target.value)} /></label>}
              {canReview && <div className="actions annotation-review-actions"><Button className="primary" disabled={reviewBlocked || !labelValid} onClick={() => void review('corrected')}>{busy ? 'Saving…' : autoAdvance ? 'Save label & next' : 'Save label'}</Button>{!blindReview && task.content.draft_prediction && <Button disabled={reviewBlocked || !labelValid || label !== initialLabel({ ...task, latest_review: null })} onClick={() => void review('accepted_without_edit')}>Accept draft</Button>}<Button disabled={reviewBlocked} onClick={() => void review('rejected')}>Reject sample</Button><Button disabled={reviewBlocked} onClick={() => void review('skipped')}>Skip sample</Button><Button disabled={busy || !!task.needs_adjudication} onClick={() => void mutate<Task>(`${taskPath}escalate/${blindQuery}`, { reason: 'Reviewer requested adjudication.' }, updated => setTasks(current => current.map(t => t.task_id === updated.task_id ? updated : t)))}>Escalate review</Button>{task.needs_adjudication && assignmentAllowed && <Button disabled={busy || !labelValid || staleDraft || conflict} onClick={() => void review('corrected', true)}>Adjudicate label as manager</Button>}</div>}
              {!canReview && <p className="muted">{!online ? 'Reconnect to save. Your edits stay in this tab.' : batch.status === 'closed' ? 'This batch is closed. Labels and history are immutable.' : 'Resume the campaign to continue reviewing.'}</p>}
              <Button disabled={busy} onClick={() => void loadHistory()}>View review history</Button>{history && <div className="review-history"><h4>Review history</h4>{history.length ? history.map(r => <details key={r.record_id}><summary>Revision {r.revision_no} · {r.decision.replaceAll('_', ' ')} · {new Date(r.created_at).toLocaleString()}</summary><p>Reviewer <Identifier value={r.reviewer_id} label="Reviewer identity" /> Review <Identifier value={r.record_id} label="Review ID" /></p><DataInspector value={{ original_prediction: r.original_prediction, human_label: r.human_label }} /></details>) : <p className="muted">No reviews yet.</p>}{historyNext && <Button disabled={busy} onClick={() => void loadHistory(true)}>Load earlier reviews</Button>}</div>}
            </div></section>}
          </div>
          <details className="annotation-analytics"><summary>Review activity & batch statistics</summary><div className="visualization-grid equal"><ChartPanel title="Batch progress" description={`Server batch totals · cycle ${batch.cycle_no}`}><SegmentBar data={[{ label: 'Reviewed', value: batch.reviewed_count }, { label: 'Awaiting review', value: Math.max(0, batch.sample_count - batch.reviewed_count), color: 4 }]} unit="samples" /><p className="muted">Reviewing includes accepted, corrected, rejected, and skipped decisions.</p></ChartPanel><ChartPanel title="Review decisions" description={`${tasks.length} samples in this batch; latest review per sample.`}><BarChart data={[...new Set(tasks.flatMap(item => item.latest_review ? [item.latest_review.decision] : []))].map(decision => ({ label: decision.replaceAll('_', ' '), value: tasks.filter(item => item.latest_review?.decision === decision).length }))} unit="Samples" emptyMessage="Save a review to see the decisions made on this batch." /><p className="muted">These decisions measure reviewer activity. Independent audit quality is not recorded by this flow.</p></ChartPanel></div></details>
        </>}
        {campaign.snapshots.length > 0 && <ChartPanel title="Approved snapshot growth" description="Cumulative approved items in immutable snapshots, by closed cycle."><LineChart series={[{ name: 'Approved snapshot items', points: campaign.snapshots.map(snapshot => ({ x: snapshot.cycle_no, y: snapshot.item_count })) }]} xLabel="Closed cycle" yLabel="Cumulative approved items" /></ChartPanel>}
        <div className="detail-box"><h3>Approved snapshots</h3>{campaign.snapshots.length ? campaign.snapshots.map(s => <div className="snapshot-row" key={s.snapshot_id}><div><strong>Cycle {s.cycle_no} · {s.item_count} cumulative approved items</strong><span>Snapshot <Identifier value={s.snapshot_id} label="Snapshot ID" /> SHA-256 <Identifier value={s.manifest_digest} label="Snapshot SHA-256" /></span></div><div className="actions"><Button disabled={busy} onClick={() => void exportSnapshot(s)}>Export labels JSON</Button>{s.dataset_revision_id && <><a href={resourceHash('dataset-revision', s.dataset_revision_id)}>Inspect approved training revision</a><a href={handoffHash('training', 'dataset-revision', s.dataset_revision_id)}>Train this snapshot</a></>}</div></div>) : <p className="muted">Close a reviewed batch to create an immutable snapshot.</p>}</div>
        <Notice className="notice campaign-stage"><strong>Next stage: train this approved snapshot</strong><p>Train this snapshot starts guided fine-tuning on the approved labels without a file download and re-upload. Automatic draft, retrain, and next-batch orchestration stay off. The active drafting model stays pinned.</p><div className="actions"><a href="#training">Training runs</a><a href="#evaluation">Evaluation</a></div></Notice>
      </>}
    </div>
  </Card>;
}
