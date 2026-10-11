import { useEffect, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { allResources, downloadJson, type RegisteredModel } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import { BarChart, ChartPanel, LineChart, SegmentBar } from '../components/Charts';
import './data-workspace.css';

interface Review { record_id: string; revision_no: number; decision: string; reviewer_id: string; human_label: { label?: unknown }; original_prediction: unknown; created_at: string }
interface Task { task_id: string; sample_ref: string; status: string; content: Record<string, unknown> & { draft_prediction?: { predicted_label?: unknown; model_version_id?: string } }; latest_review: Review | null }
interface Batch { batch_id: string; cycle_no: number; status: string; sample_count: number; reviewed_count: number; approved_count: number; drafting_model_id: string | null }
interface Snapshot { snapshot_id: string; cycle_no: number; item_count: number; manifest_digest: string }
interface Campaign {
  campaign_id: string; name: string; status: string; seed_mode: string; current_cycle: number; max_cycles: number;
  budget_limit_dollars: number; accumulated_cost_dollars: number; active_model_id: string | null;
  label_schema: { kind: string; classes: string[] }; rubric: { guidelines_text: string } | null;
  batches: Batch[]; snapshots: Snapshot[];
}
const sampleExample = '[\n  {"id": "sample-001", "text": "Your source text here"}\n]';
function initialLabel(task: Task): string {
  const label = task.latest_review?.human_label.label ?? task.content.draft_prediction?.predicted_label;
  return label === undefined ? '' : typeof label === 'string' ? label : JSON.stringify(label, null, 2);
}

export function AnnotationPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [campaignId, setCampaignId] = useState(() => new URLSearchParams(window.location.hash.split('?')[1]).get('campaign') || '');
  const [batchId, setBatchId] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState('');
  const [taskNext, setTaskNext] = useState<string | null>(null);
  const [history, setHistory] = useState<Review[] | null>(null);
  const [historyNext, setHistoryNext] = useState<string | null>(null);
  const [label, setLabel] = useState('');
  const [loading, setLoading] = useState(true);
  const [queueLoading, setQueueLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const [queueRetry, setQueueRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState(false);
  const [name, setName] = useState('');
  const [kind, setKind] = useState('classification');
  const [classes, setClasses] = useState('positive, negative');
  const [guidelines, setGuidelines] = useState('');
  const [seed, setSeed] = useState('manual');
  const [model, setModel] = useState('');
  const [cycles, setCycles] = useState('3');
  const [budget, setBudget] = useState('100');
  const [auditRefs, setAuditRefs] = useState('');
  const [samples, setSamples] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [queueFilter, setQueueFilter] = useState('all');
  const campaign = campaigns.find(c => c.campaign_id === campaignId);
  const batch = campaign?.batches.find(b => b.batch_id === batchId);
  const task = tasks.find(t => t.task_id === taskId);
  const canReview = campaign?.status === 'active' && batch?.status !== 'closed';

  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(null); setCampaigns([]); setModels([]);
    Promise.all([allResources<Campaign>('/api/v1/labeling-campaigns/', token, controller.signal), allResources<RegisteredModel>('/api/v1/model-versions/', token, controller.signal)])
      .then(([c, m]) => { if (!controller.signal.aborted) { setCampaigns(c); setModels(m); } })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refreshKey, retry]);

  useEffect(() => {
    if (!campaign) { setBatchId(''); return; }
    setBatchId(current => campaign.batches.some(b => b.batch_id === current) ? current : [...campaign.batches].sort((a, b) => b.cycle_no - a.cycle_no)[0]?.batch_id || '');
  }, [campaign]);

  useEffect(() => {
    const controller = new AbortController(); setTasks([]); setTaskId(''); setTaskNext(null); setHistory(null);
    if (!batchId) return () => controller.abort();
    setQueueLoading(true);
    apiPage<Task>(`/api/v1/labeling-batches/${batchId}/tasks/`, token, controller.signal)
      .then(page => { if (!controller.signal.aborted) { setTasks(page.results); setTaskNext(page.next || null); setTaskId(page.results.find(t => !t.latest_review)?.task_id || page.results[0]?.task_id || ''); } })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setQueueLoading(false); });
    return () => controller.abort();
  }, [batchId, token, refreshKey, queueRetry]);

  useEffect(() => { setLabel(task ? initialLabel(task) : ''); setHistory(null); setHistoryNext(null); }, [task]);

  async function mutate<T>(path: string, body: unknown, success: (result: T) => void) {
    setBusy(true); setError(null); setNotice('');
    try { success(await apiRequest<T>(path, token, { method: 'POST', body: JSON.stringify(body) })); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  function updateCampaign(value: Campaign) { setCampaigns(current => current.map(c => c.campaign_id === value.campaign_id ? value : c)); }
  function selectCampaign(id: string) { setCampaignId(id); setError(null); setNotice(''); setImportOpen(false); window.history.replaceState(null, '', `#annotation${id ? `?campaign=${id}` : ''}`); }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    await mutate<Campaign>('/api/v1/labeling-campaigns/', {
      name, kind, classes: kind === 'classification' ? classes.split(',').map(v => v.trim()).filter(Boolean) : [],
      guidelines, seed_mode: seed, drafting_model_id: seed === 'existing_model' ? model : null,
      max_cycles: Number(cycles), budget_limit_dollars: Number(budget), audit_sample_refs: auditRefs.split('\n').map(v => v.trim()).filter(Boolean),
    }, c => { setCampaigns(current => [c, ...current]); selectCampaign(c.campaign_id); setSetup(false); setName(''); setNotice('Campaign created. Add a source batch to begin review.'); });
  }
  async function importBatch(e: React.FormEvent) {
    e.preventDefault(); if (!campaign) return;
    let parsed: unknown;
    try { parsed = JSON.parse(samples); if (!Array.isArray(parsed)) throw new Error('Provide a JSON array of samples.'); }
    catch (e) { setError(errorMessage(e)); return; }
    await mutate<Batch>(`/api/v1/labeling-campaigns/${campaign.campaign_id}/batches/`, { samples: parsed }, b => {
      updateCampaign({ ...campaign, batches: [...campaign.batches, b] }); setBatchId(b.batch_id); setSamples(''); setImportOpen(false); setNotice(`Cycle ${b.cycle_no} opened with ${b.sample_count} samples.`);
    });
  }
  async function review(decision: string) {
    if (!task || !campaign || !batch) return;
    let value: unknown = label;
    if (decision !== 'skipped' && decision !== 'rejected' && ['ner_span', 'rubric_scoring'].includes(campaign.label_schema.kind)) {
      try { value = JSON.parse(label); } catch { setError('The label must contain valid JSON.'); return; }
    }
    await mutate<Task>(`/api/v1/annotation-tasks/${task.task_id}/review/`, {
      decision, human_label: ['skipped', 'rejected'].includes(decision) ? {} : { label: value }, expected_revision: (task.latest_review?.revision_no || 0) + 1,
    }, updated => {
      setTasks(current => current.map(t => t.task_id === updated.task_id ? updated : t));
      updateCampaign({ ...campaign, batches: campaign.batches.map(b => b.batch_id === batch.batch_id ? { ...b, reviewed_count: b.reviewed_count + (task.latest_review ? 0 : 1) } : b) });
      setTaskId(tasks.find(t => t.task_id !== task.task_id && !t.latest_review)?.task_id || task.task_id);
      setNotice(`Review saved for ${task.sample_ref}.`);
    });
  }
  async function closeBatch() {
    if (!campaign || !batch) return;
    await mutate<Snapshot>(`/api/v1/labeling-batches/${batch.batch_id}/close/`, {}, s => {
      setNotice(`Cycle ${s.cycle_no} closed. Immutable cumulative snapshot: ${s.item_count} approved items.`);
      setRetry(v => v + 1); setQueueRetry(v => v + 1);
    });
  }
  async function loadMoreTasks() {
    if (!taskNext || !batchId) return;
    setBusy(true); setError(null);
    try { const page = await apiPage<Task>(nextPagePath(taskNext, `/api/v1/labeling-batches/${batchId}/tasks/`), token); setTasks(current => [...current, ...page.results]); setTaskNext(page.next || null); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function loadHistory(more = false) {
    if (!task) return;
    setBusy(true); setError(null);
    try {
      const path = `/api/v1/annotation-tasks/${task.task_id}/history/`;
      const page = await apiPage<Review>(more && historyNext ? nextPagePath(historyNext, path) : path, token);
      setHistory(current => more ? [...current || [], ...page.results] : page.results); setHistoryNext(page.next || null);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function exportSnapshot(snapshot: Snapshot) {
    setBusy(true); setError(null);
    try { await downloadJson(`/api/v1/annotation-snapshots/${snapshot.snapshot_id}/export/`, token, `labels-cycle-${snapshot.cycle_no}.json`); }
    catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const visibleTasks = tasks.filter(t => queueFilter === 'all' || (queueFilter === 'pending' ? !t.latest_review : !!t.latest_review));

  return <section className="panel annotation-page">
    <div className="panel-title"><div><h2>Annotation review</h2><p>Review source evidence, refine labels, and freeze approved snapshots.</p></div><button className="primary" disabled={loading || busy} onClick={() => setSetup(v => !v)}>{setup ? 'Close setup' : 'New campaign'}</button></div>
    <div className="panel-body">
      <ResourceState loading={loading} error={error} onRetry={() => { setRetry(v => v + 1); setQueueRetry(v => v + 1); }} />
      {notice && <div className="notice success" role="status">{notice}</div>}
      <ol className="flow-steps" aria-label="Labeling workflow"><li>1. Set up campaign</li><li>2. Add source batch</li><li>3. Review labels</li><li>4. Close & export</li></ol>
      {setup && <form className="form-grid" onSubmit={create}>
        <label>Campaign name<input required maxLength={180} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Label schema<select value={kind} onChange={e => setKind(e.target.value)}><option value="classification">Classification</option><option value="text_generation">Text response</option><option value="preference_ranking">Preference ranking</option><option value="ner_span">NER spans (JSON)</option><option value="rubric_scoring">Rubric scoring (JSON)</option></select></label>
        {kind === 'classification' && <label className="full-width">Class labels, separated by commas<input required value={classes} onChange={e => setClasses(e.target.value)} /></label>}
        <label>Seed mode<select value={seed} onChange={e => setSeed(e.target.value)}><option value="manual">Manual labeling</option><option value="existing_model">Review imported model drafts</option></select></label>
        {seed === 'existing_model' && <label>Drafting model version<select required value={model} onChange={e => setModel(e.target.value)}><option value="">Select a pinned version</option>{models.map(m => <option key={m.id} value={m.model_version_id}>{m.model_name} · r{m.revision_no}</option>)}</select></label>}
        <label>Cycle limit<input type="number" min="1" max="100" required value={cycles} onChange={e => setCycles(e.target.value)} /></label>
        <label>Budget ceiling (USD)<input type="number" min="0" max="1000000" step="0.01" required value={budget} onChange={e => setBudget(e.target.value)} /></label>
        <label className="full-width">Review guidelines<textarea rows={3} value={guidelines} onChange={e => setGuidelines(e.target.value)} /></label>
        <label className="full-width">Protected audit sample IDs (one per line)<textarea rows={2} value={auditRefs} onChange={e => setAuditRefs(e.target.value)} placeholder="These IDs will be excluded from source batches." /></label>
        <p className="muted full-width">Imported drafts must carry the selected model version ID. Automatic model inference and retraining are not connected yet. The budget ceiling records campaign intent; this review flow incurs no executor spend.</p>
        <div className="actions full-width"><button className="primary" disabled={busy || (seed === 'existing_model' && !model)}>{busy ? 'Creating…' : 'Create campaign'}</button></div>
      </form>}
      {!loading && !error && !campaigns.length && !setup && <div className="empty-state"><h3>Start your first labeling campaign</h3><p>Create a label schema and review guidelines, then import samples from your source pool.</p><button onClick={() => setSetup(true)}>Set up labeling</button></div>}
      {!!campaigns.length && <label className="campaign-picker">Campaign<select value={campaignId} disabled={busy} onChange={e => selectCampaign(e.target.value)}><option value="">Select a campaign</option>{campaigns.map(c => <option key={c.campaign_id} value={c.campaign_id}>{c.name} · {c.status} · cycle {c.current_cycle}/{c.max_cycles}</option>)}</select></label>}
      {campaign && <>
        <div className="campaign-summary"><div><h3>{campaign.name} <span className={`state state-${campaign.status}`}>{campaign.status}</span></h3><p>{campaign.label_schema.kind.replaceAll('_', ' ')} · {campaign.seed_mode === 'manual' ? 'Manual seed' : 'Imported model drafts'} · {campaign.current_cycle}/{campaign.max_cycles} cycles closed</p><small>Recorded spend ${campaign.accumulated_cost_dollars.toFixed(2)} / ${campaign.budget_limit_dollars.toFixed(2)} ceiling</small></div>
          <div className="actions">{['active', 'paused'].includes(campaign.status) && <button disabled={busy} onClick={() => void mutate<Campaign>(`/api/v1/labeling-campaigns/${campaign.campaign_id}/lifecycle/`, { transition: campaign.status === 'paused' ? 'resume' : 'pause' }, updateCampaign)}>{campaign.status === 'paused' ? 'Resume campaign' : 'Pause campaign'}</button>}
          <button className="primary" disabled={busy || campaign.status !== 'active' || campaign.batches.some(b => b.status !== 'closed')} onClick={() => setImportOpen(v => !v)}>{importOpen ? 'Close import' : 'Add source batch'}</button></div>
        </div>
        {importOpen && <form className="form-grid" onSubmit={importBatch}><label className="full-width">Source samples (JSON array)<textarea required rows={8} value={samples} onChange={e => setSamples(e.target.value)} placeholder={sampleExample} /></label><p className="muted full-width">Up to 500 samples per cycle. Each needs a unique id and text, prompt, input, or candidate_a content. Protected audit IDs, evaluation splits, and reused inputs are rejected.{campaign.active_model_id && <> Imported draft_prediction must include predicted_label and model_version_id: <code>{campaign.active_model_id}</code>.</>}</p><button className="primary" disabled={busy || !samples.trim()}>Open review batch</button></form>}
        {!!campaign.batches.length && <label className="campaign-picker">Batch<select value={batchId} disabled={busy} onChange={e => setBatchId(e.target.value)}>{[...campaign.batches].sort((a, b) => b.cycle_no - a.cycle_no).map(b => <option key={b.batch_id} value={b.batch_id}>Cycle {b.cycle_no} · {b.status} · {b.reviewed_count}/{b.sample_count} reviewed</option>)}</select></label>}
        {batch && <>
          <div className="actions queue-summary"><strong>{batch.reviewed_count} / {batch.sample_count} reviewed</strong><progress value={batch.reviewed_count} max={batch.sample_count || 1} aria-label="Batch review progress" /><span className={`state state-${batch.status}`}>{batch.status}</span>{batch.status !== 'closed' && <button className="primary" disabled={busy || !canReview || batch.reviewed_count !== batch.sample_count} onClick={() => void closeBatch()}>Close batch & freeze snapshot</button>}</div>
          <p className="muted">Closing freezes approved labels. Rejected and skipped samples are excluded. Later cycles append to the cumulative snapshot.</p>
          <ResourceState loading={queueLoading} />
          <div className="annotation-workspace premium-review-workspace">
            <section className="review-queue"><h3>Review queue</h3><label>Show samples<select value={queueFilter} onChange={e => setQueueFilter(e.target.value)}><option value="all">All loaded samples</option><option value="pending">Awaiting review</option><option value="reviewed">Reviewed</option></select></label>
              {visibleTasks.map(t => <button disabled={busy} key={t.task_id} className={`queue-item ${taskId === t.task_id ? 'selected' : ''}`} onClick={() => setTaskId(t.task_id)}><strong>{t.sample_ref}</strong><span>{t.latest_review ? t.latest_review.decision.replaceAll('_', ' ') : t.status}</span></button>)}
              {!queueLoading && !visibleTasks.length && <p className="muted">No matching samples loaded.</p>}{taskNext && <button disabled={busy} onClick={() => void loadMoreTasks()}>Load more samples</button>}
            </section>
            {task && <section className="review-editor"><div className="annotation-source"><div className="annotation-section-title"><span className="badge">SOURCE CONTENT</span><h3>Sample {task.sample_ref}</h3></div>{campaign.rubric && <details open><summary>Review guidelines</summary><p className="preserve-lines">{campaign.rubric.guidelines_text}</p></details>}
              <div className="annotation-source-blocks">{Object.entries(task.content).filter(([key]) => key !== 'draft_prediction').map(([key, value]) => <article className="annotation-content-block" key={key}><span className="badge">{key.replaceAll('_', ' ')}</span>{typeof value === 'string' ? <p className="preserve-lines">{value}</p> : <pre>{JSON.stringify(value, null, 2)}</pre>}</article>)}</div>
              {task.content.draft_prediction && <details open><summary>Original imported prediction</summary><pre>{JSON.stringify(task.content.draft_prediction, null, 2)}</pre></details>}
              </div><div className="annotation-decision"><h3>Review annotation</h3><p className="muted">{campaign.label_schema.kind.replaceAll('_', ' ')} · revision {(task.latest_review?.revision_no || 0) + 1}</p>
              {['classification', 'preference_ranking'].includes(campaign.label_schema.kind) ? <fieldset className="annotation-label-options" disabled={busy || !canReview}><legend>Human label</legend>{(campaign.label_schema.kind === 'classification' ? campaign.label_schema.classes : ['candidate_a', 'candidate_b', 'tie', 'abstain']).map(value => <label className={`annotation-label-option ${label === value ? 'selected' : ''}`} key={value}><input type="radio" name={`label-${task.task_id}`} value={value} checked={label === value} onChange={() => setLabel(value)} /><span>{value.replaceAll('_', ' ')}</span></label>)}</fieldset> : <label>Human label<textarea disabled={busy || !canReview} rows={7} value={label} onChange={e => setLabel(e.target.value)} /></label>}
              {canReview && <div className="actions"><button className="primary" disabled={busy || !label.trim()} onClick={() => void review('corrected')}>Save label</button>{task.content.draft_prediction && <button disabled={busy || label !== initialLabel({ ...task, latest_review: null })} onClick={() => void review('accepted_without_edit')}>Accept draft</button>}<button disabled={busy} onClick={() => void review('rejected')}>Reject sample</button><button disabled={busy} onClick={() => void review('skipped')}>Skip sample</button></div>}
              {!canReview && <p className="muted">{batch.status === 'closed' ? 'This batch is closed. Labels and history are immutable.' : 'Resume the campaign to continue reviewing.'}</p>}
              <button disabled={busy} onClick={() => void loadHistory()}>View review history</button>{history && <div className="review-history"><h4>Review history</h4>{history.length ? history.map(r => <details key={r.record_id}><summary>Revision {r.revision_no} · {r.decision.replaceAll('_', ' ')} · {new Date(r.created_at).toLocaleString()}</summary><p>Reviewer: {r.reviewer_id}</p><pre>{JSON.stringify({ original_prediction: r.original_prediction, human_label: r.human_label }, null, 2)}</pre></details>) : <p className="muted">No reviews yet.</p>}{historyNext && <button disabled={busy} onClick={() => void loadHistory(true)}>Load earlier reviews</button>}</div>}
            </div></section>}
          </div>
          <div className="visualization-grid equal"><ChartPanel title="Batch progress" description={`Server batch totals · cycle ${batch.cycle_no}`}><SegmentBar data={[{ label: 'Reviewed', value: batch.reviewed_count }, { label: 'Awaiting review', value: Math.max(0, batch.sample_count - batch.reviewed_count), color: 4 }]} unit="samples" /><p className="muted">Reviewing includes accepted, corrected, rejected, and skipped decisions.</p></ChartPanel><ChartPanel title="Review decisions" description={`${tasks.length} loaded tasks${taskNext ? ' · more pages available' : ''}; latest review per sample.`}><BarChart data={[...new Set(tasks.flatMap(item => item.latest_review ? [item.latest_review.decision] : []))].map(decision => ({ label: decision.replaceAll('_', ' '), value: tasks.filter(item => item.latest_review?.decision === decision).length }))} unit="Loaded samples" emptyMessage="Save a review to see the decisions made on loaded samples." /><p className="muted">These decisions measure reviewer activity. Independent audit quality is not recorded by this flow.</p></ChartPanel></div>
        </>}
        {campaign.snapshots.length > 0 && <ChartPanel title="Approved snapshot growth" description="Cumulative approved items in immutable snapshots, by closed cycle."><LineChart series={[{ name: 'Approved snapshot items', points: campaign.snapshots.map(snapshot => ({ x: snapshot.cycle_no, y: snapshot.item_count })) }]} xLabel="Closed cycle" yLabel="Cumulative approved items" /></ChartPanel>}
        <div className="detail-box"><h3>Approved snapshots</h3>{campaign.snapshots.length ? campaign.snapshots.map(s => <div className="snapshot-row" key={s.snapshot_id}><div><strong>Cycle {s.cycle_no} · {s.item_count} cumulative approved items</strong><small className="id-text">SHA-256 {s.manifest_digest}</small></div><button disabled={busy} onClick={() => void exportSnapshot(s)}>Export labels JSON</button></div>) : <p className="muted">Close a reviewed batch to create an immutable snapshot.</p>}</div>
        <div className="notice campaign-stage"><strong>Next stage: train & qualify a candidate</strong><p>Automatic campaign training, held-out qualification, promotion, and rollback are not connected to an executor yet. Use the exported approved snapshot as training input. The active drafting model stays pinned.</p><div className="actions"><a href="#training">Training runs</a><a href="#evaluation">Evaluation</a></div></div>
      </>}
    </div>
  </section>;
}
