import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources, type RegisteredModel } from '../api/resources';
import { alignmentAction, createAlignmentPlan, preferencePairs, registerPreferences, type AlignmentRun, type PreferenceArtifact } from '../api/alignment';
import { ResourceState } from '../components/ResourceState';
import { BarChart, ChartPanel, ChartEmpty, EventTimeline, LineChart } from '../components/Charts';
import { numericEntries } from '../components/chart-data';
import './ml-pages.css';

const algorithms = [['dpo', 'Direct preference optimization'], ['reward_model', 'Bradley–Terry reward model'], ['ppo_rlhf', 'PPO RLHF'], ['verifier_rl', 'Verifier guided RL']];
type ModelInput = RegisteredModel & { metadata?: { model_role?: string } };
interface StepBudget { policy_id: string; name: string; unit: string; enabled: boolean }
function objectJson(raw: string, label: string): Record<string, unknown> {
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw new Error(`${label} must contain valid JSON.`); }
  if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error(`${label} must be a JSON object.`);
  return value as Record<string, unknown>;
}

export function AlignmentPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [runs, setRuns] = useState<AlignmentRun[]>([]), [models, setModels] = useState<ModelInput[]>([]), [artifacts, setArtifacts] = useState<PreferenceArtifact[]>([]);
  const [stepBudgets, setStepBudgets] = useState<StepBudget[]>([]), [stepBudgetId, setStepBudgetId] = useState('');
  const [loading, setLoading] = useState(true), [error, setError] = useState<string | null>(null), [retry, setRetry] = useState(0), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [setup, setSetup] = useState(false), [upload, setUpload] = useState(false), [algorithm, setAlgorithm] = useState('dpo');
  const [policy, setPolicy] = useState(''), [reference, setReference] = useState(''), [reward, setReward] = useState(''), [dataset, setDataset] = useState(''), [heldOut, setHeldOut] = useState('');
  const [steps, setSteps] = useState('10'), [hyperparameters, setHyperparameters] = useState('{"learning_rate":0.05}'), [verifier, setVerifier] = useState('{"type":"exact_match"}');
  const [selected, setSelected] = useState(''), [metricKey, setMetricKey] = useState(''), [artifactName, setArtifactName] = useState(''), [pairsJson, setPairsJson] = useState('');
  const [executingId, setExecutingId] = useState(''), [cancelBusy, setCancelBusy] = useState(false);
  const actionRequest = useRef<AbortController | null>(null);
  const cancelRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setRuns([]); setModels([]); setArtifacts([]); setStepBudgets([]); setNotice('');
    Promise.all([allResources<AlignmentRun>('/api/v1/alignment-runs/', token, c.signal), allResources<ModelInput>('/api/v1/model-versions/', token, c.signal), allResources<PreferenceArtifact>('/api/v1/alignment-runs/preference-artifacts/', token, c.signal), allResources<StepBudget>('/api/v1/budget-policies/', token, c.signal)])
      .then(([r, m, a, budgets]) => { if (!c.signal.aborted) { setRuns(r); setModels(m); setArtifacts(a); const active = budgets.filter(b => b.enabled && b.unit === 'training_steps'); setStepBudgets(active); setStepBudgetId(current => active.some(b => b.policy_id === current) ? current : active.length === 1 ? active[0].policy_id : ''); } })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, refreshKey, retry]);
  useEffect(() => { setSelected(''); setPolicy(''); setReference(''); setReward(''); setDataset(''); setHeldOut(''); setStepBudgetId(''); setBusy(false); setExecutingId(''); setCancelBusy(false); return () => { actionRequest.current?.abort(); actionRequest.current = null; cancelRequest.current?.abort(); cancelRequest.current = null; }; }, [token]);
  useEffect(() => {
    if (!executingId) return;
    const c = new AbortController();
    let pending = false;
    const interval = window.setInterval(async () => {
      if (pending || c.signal.aborted) return;
      pending = true;
      try { const updated = await apiRequest<AlignmentRun>(`/api/v1/alignment-runs/${executingId}/`, token, { signal: c.signal }); if (!c.signal.aborted) setRuns(current => current.map(r => r.run_id === updated.run_id ? updated : r)); }
      catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
      finally { pending = false; }
    }, 1000);
    return () => { c.abort(); window.clearInterval(interval); };
  }, [executingId, token]);
  async function act(work: (signal: AbortSignal) => Promise<void>) {
    if (actionRequest.current) return;
    const c = new AbortController(); actionRequest.current = c; setBusy(true); setError(null); setNotice('');
    try { await work(c.signal); } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
    finally { if (!c.signal.aborted && actionRequest.current === c) { actionRequest.current = null; setBusy(false); } }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    await act(async signal => {
      const params = objectJson(hyperparameters, 'Hyperparameters');
      if (stepBudgetId) params.budget_policy_id = stepBudgetId;
      if (stepBudgets.length > 1 && !params.budget_policy_id) throw new Error('Select an alignment step budget.');
      const r = await createAlignmentPlan(token, { algorithm, policy_model_version: Number(policy), reference_model_version: reference ? Number(reference) : null, reward_model_version: reward ? Number(reward) : null, train_dataset_artifact: dataset, held_out_dataset_artifact: heldOut, total_steps: Number(steps), hyperparameters: params, verifier_spec: objectJson(verifier, 'Verifier specification') }, signal);
      if (signal.aborted) return;
      setRuns(current => [r, ...current]); setSelected(r.run_id); setSetup(false); setNotice('Alignment plan saved with verified preference bytes. Execute when ready.');
    });
  }
  async function register(e: React.FormEvent) {
    e.preventDefault();
    await act(async signal => {
      const artifact = await registerPreferences(token, artifactName, preferencePairs(pairsJson), signal);
      if (signal.aborted) return;
      setArtifacts(current => [artifact, ...current]); setUpload(false); setArtifactName(''); setPairsJson(''); setNotice(`Preference artifact “${artifact.name}” committed. Select separate training and held-out inputs.`);
    });
  }
  async function execute(action: 'execute' | 'cancel') {
    if (!run || (action === 'execute' && !run.execution_capabilities?.can_execute)) return;
    if (action === 'cancel') {
      if (cancelRequest.current) return;
      const c = new AbortController(); cancelRequest.current = c; setCancelBusy(true); setError(null);
      try { const updated = await alignmentAction(token, run.run_id, 'cancel', c.signal); if (!c.signal.aborted) { setRuns(current => current.map(r => r.run_id === updated.run_id ? updated : r)); setNotice(updated.execution_evidence?.level === 'fixture' ? 'Demo alignment cancelled with fictional Storybook results.' : `Alignment ${updated.status}. Committed steps remain available.`); } }
      catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); }
      finally { if (!c.signal.aborted && cancelRequest.current === c) { cancelRequest.current = null; setCancelBusy(false); } }
      return;
    }
    if (actionRequest.current) return;
    setExecutingId(run.run_id);
    await act(async signal => {
      const updated = await alignmentAction(token, run.run_id, action, signal);
      if (signal.aborted) return;
      setExecutingId('');
      setRuns(current => current.map(r => r.run_id === updated.run_id ? updated : r));
      const demo = updated.execution_evidence?.level === 'fixture';
      setNotice(demo ? `Demo alignment ${updated.status} with fictional Storybook results.` : `Alignment ${updated.status}: ${updated.current_step} steps committed${updated.output_model_version ? '; candidate weights registered' : ''}.`);
      if (updated.output_model_version) {
        const refreshed = await allResources<ModelInput>('/api/v1/model-versions/', token, signal);
        if (!signal.aborted) setModels(refreshed);
      }
    });
    if (actionRequest.current === null) setExecutingId('');
  }
  function modelSelect(title: string, value: string, change: (value: string) => void, required = false, rewardOnly = false) {
    const available = models.filter(m => rewardOnly ? m.metadata?.model_role === 'reward_model' : m.metadata?.model_role !== 'reward_model');
    return <label>{title}<select required={required} disabled={busy} value={value} onChange={e => change(e.target.value)}><option value="">{required ? 'Select a model version' : 'None'}</option>{available.map(m => <option key={m.id} value={m.id}>{m.model_name} · r{m.revision_no}</option>)}</select></label>;
  }
  function artifactSelect(title: string, value: string, change: (value: string) => void) {
    return <label>{title}<select required disabled={busy} value={value} onChange={e => change(e.target.value)}><option value="">Select committed preference bytes</option>{artifacts.map(a => <option key={a.artifact_id} value={a.artifact_id}>{a.name} · {a.row_count} pairs · {a.sha256.slice(0, 10)}</option>)}</select></label>;
  }
  const run = runs.find(r => r.run_id === selected) || runs[0];
  const recordedMetrics = numericEntries(run?.latest_metrics);
  const focusedMetric = recordedMetrics.find(m => m.label === metricKey) || recordedMetrics.find(m => ['loss', 'policy loss', 'reward margin'].includes(m.label)) || recordedMetrics.find(m => m.label !== 'step' && m.label !== 'cpu seconds') || recordedMetrics[0];
  const metric = focusedMetric?.label.replaceAll(' ', '_');
  const points = (run?.metrics_history || []).flatMap((entry, index) => typeof entry[metric || ''] === 'number' ? [{ x: typeof entry.step === 'number' ? entry.step : index + 1, y: entry[metric || ''] as number }] : []);
  const modelName = (id: number | null | undefined) => { const m = models.find(model => model.id === id); return m ? `${m.model_name} · r${m.revision_no}` : id == null ? 'Not configured' : `Model record #${id}`; };
  return <section className="panel ml-page ml-main-panel ml-alignment"><div className="panel-title"><div><span className="ml-eyebrow">DEVELOP / ALIGNMENT</span><h2>Alignment lab</h2><p>Train pinned CPU character models from preference pairs and inspect measured optimizer steps.</p></div><div className="actions"><button disabled={loading || busy} onClick={() => setUpload(v => !v)}>{upload ? 'Close preferences' : 'Register preference pairs'}</button><button className="primary" disabled={loading || busy} onClick={() => setSetup(v => !v)}>{setup ? 'Close setup' : 'New alignment plan'}</button></div></div><div className="panel-body">
    <div className="ml-stat-strip" aria-label="Alignment summary"><div><span>Alignment runs</span><strong>{loading ? '—' : runs.length}</strong><small>Recorded plans and results</small></div><div><span>Active runs</span><strong>{loading ? '—' : runs.filter(r => ['pending', 'running'].includes(r.status)).length}</strong><small>Pending or running</small></div><div><span>Preference artifacts</span><strong>{loading ? '—' : artifacts.length}</strong><small>Committed inputs</small></div><div><span>Selected progress</span><strong>{run ? `${run.current_step} / ${run.total_steps}` : '—'}</strong><small>Committed steps</small></div></div>
    <p className="notice">{run?.execution_capabilities?.reason || 'Bounded CPU character execution supports four alignment recipes. Candidate weights require independent evaluation.'}</p>
    {run?.execution_evidence && <p className="muted">{run.execution_evidence.source}</p>}
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />{notice && <p className="notice success" role="status">{notice}</p>}
    {upload && <form className="form-grid" onSubmit={register}><label>Preference artifact name<input required maxLength={200} disabled={busy} value={artifactName} onChange={e => setArtifactName(e.target.value)} /></label><label>Load preference JSON file<input type="file" accept="application/json,.json" disabled={busy} onChange={async e => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 256 * 1024) { setError('Preference files support at most 256 KiB.'); return; } try { const raw = await file.text(); preferencePairs(raw); setPairsJson(raw); } catch (error) { setError(errorMessage(error)); } }} /></label><label className="full-width">Preference pairs JSON<textarea required rows={6} disabled={busy} value={pairsJson} placeholder={'[{"prompt":"Say a","chosen":"a","rejected":"b"}]'} onChange={e => setPairsJson(e.target.value)} /></label><p className="muted full-width">Register 1–32 unique pairs. Responses support up to 32 characters; prompt plus response supports 62. Create a separate artifact with disjoint held-out prompts. Execution checks every character against the model vocabulary.</p><button className="primary" disabled={busy}>Commit preference artifact</button></form>}
    {setup && <form className="form-grid" onSubmit={create}><label>Algorithm<select disabled={busy} value={algorithm} onChange={e => setAlgorithm(e.target.value)}>{algorithms.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>{modelSelect('Policy model version', policy, setPolicy, true)}{modelSelect('Reference model version', reference, setReference, ['dpo', 'ppo_rlhf'].includes(algorithm))}{algorithm === 'ppo_rlhf' && modelSelect('Trained reward model version', reward, setReward, true, true)}{artifactSelect('Training preference artifact', dataset, setDataset)}{artifactSelect('Held-out preference artifact', heldOut, setHeldOut)}<label>Total steps<input required disabled={busy} type="number" min="1" max="100" value={steps} onChange={e => setSteps(e.target.value)} /></label><label>Alignment step budget<select disabled={busy} required={stepBudgets.length > 1} value={stepBudgetId} onChange={e => setStepBudgetId(e.target.value)}><option value="">{stepBudgets.length ? 'Choose a training step budget' : 'No enabled training step policy'}</option>{stepBudgets.map(b => <option key={b.policy_id} value={b.policy_id}>{b.name} · training_steps</option>)}</select></label><label className="full-width">Hyperparameters (JSON)<textarea disabled={busy} rows={3} value={hyperparameters} onChange={e => setHyperparameters(e.target.value)} /></label>{algorithm === 'verifier_rl' && <label className="full-width">Verifier specification (JSON)<textarea disabled={busy} required rows={3} value={verifier} onChange={e => setVerifier(e.target.value)} /></label>}<p className="muted full-width">The server computes digests from committed preference bytes. CPU execution supports 1–100 steps. Learning rate: 0.000001–0.2; DPO beta: 0.001–1. PPO requires a trained reward model with the same tokenizer. The selected training_steps policy reserves the configured step count and settles only committed steps.</p><button className="primary" disabled={busy || !policy || !dataset || !heldOut || dataset === heldOut}>Create alignment configuration</button></form>}
    <div className="ml-section-heading"><div><span className="ml-eyebrow">PREFERENCE OPTIMIZATION</span><h3>Recorded alignment metrics</h3><p>Selected measurements and committed step history, without inferred scores.</p></div><label>Inspect run<select aria-label="Alignment run to visualize" value={run?.run_id || ''} onChange={e => setSelected(e.target.value)}><option value="" disabled>Select an alignment run</option>{runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 8)} · {r.algorithm} · {r.status}</option>)}</select></label></div>
    {run && <div className="actions"><button className="primary" disabled={busy || !run.execution_capabilities?.can_execute} onClick={() => void execute('execute')}>{busy ? 'Updating alignment…' : 'Execute CPU alignment'}</button>{['pending', 'running'].includes(run.status) && <button disabled={cancelBusy} onClick={() => void execute('cancel')}>{cancelBusy ? 'Cancelling alignment…' : 'Cancel alignment'}</button>}<button disabled={busy || loading} onClick={() => setRetry(v => v + 1)}>Refresh alignment runs</button>{run.output_model_version && <span className="muted">Candidate: {modelName(run.output_model_version)}</span>}</div>}
    <div className="visualization-grid"><ChartPanel title={points.length ? 'Recorded optimizer history' : 'Latest metric snapshot'} description={run ? `${run.algorithm} · ${run.run_id.slice(0, 8)}` : 'Metrics appear after execution.'} action={recordedMetrics.length > 0 && <select aria-label="Alignment metric to visualize" value={focusedMetric?.label || ''} onChange={e => setMetricKey(e.target.value)}>{recordedMetrics.map(m => <option key={m.label}>{m.label}</option>)}</select>}>{points.length ? <LineChart series={[{ name: focusedMetric?.label || 'Metric', points }]} yLabel={focusedMetric?.label} /> : <BarChart data={focusedMetric ? [focusedMetric] : []} unit={focusedMetric?.label || 'Recorded value'} emptyMessage="No numeric alignment metrics have been recorded. Pending plans have no measured preference scores." />}</ChartPanel><ChartPanel title="Pinned execution inputs" description="Model versions, preference bytes, and output candidate.">{run ? <><EventTimeline events={[{ label: 'Policy model', detail: modelName(run.policy_model_version), status: 'completed' }, { label: 'Reference model', detail: modelName(run.reference_model_version), status: run.reference_model_version == null ? 'pending' : 'completed' }, { label: 'Reward model', detail: modelName(run.reward_model_version), status: run.reward_model_version == null ? 'pending' : 'completed' }, { label: 'Training / held-out bytes', detail: `${run.dataset_manifest_digest.slice(0, 12)} / ${run.held_out_validation_digest.slice(0, 12)}`, status: run.train_dataset_artifact && run.held_out_dataset_artifact ? 'completed' : 'pending' }]} /><div className="ml-run-progress"><span>Committed steps</span><strong>{run.current_step} / {run.total_steps}</strong><progress value={run.current_step} max={run.total_steps || 1} aria-label="Alignment committed steps" /></div></> : <ChartEmpty message="Configure an alignment run to inspect pinned models and preference artifacts." />}</ChartPanel></div>
    <div className="ml-section-heading"><div><h3>Alignment history</h3><p>Configuration, execution state, and recorded stop reasons.</p></div></div>{!loading && !error && !runs.length && <p className="muted">No alignment runs yet.</p>}{!!runs.length && <div className="table-scroll" tabIndex={0}><table className="resource-table"><thead><tr><th>Run</th><th>Algorithm</th><th>State</th><th>Progress</th><th>Stop reason</th></tr></thead><tbody>{runs.map(r => <tr key={r.run_id} className={run?.run_id === r.run_id ? 'ml-selected-row' : undefined}><td><button className="text-button" onClick={() => setSelected(r.run_id)}>{r.run_id.slice(0, 8)}</button></td><td>{r.algorithm}</td><td><span className={`state state-${r.status}`}>{r.status}</span></td><td>{r.current_step}/{r.total_steps}</td><td>{r.stop_reason || '—'}</td></tr>)}</tbody></table></div>}{selected && run && <div className="detail-box"><div className="actions"><h3>Alignment {run.run_id.slice(0, 8)}</h3><button onClick={() => setSelected('')}>Close details</button></div><pre tabIndex={0} role="region" aria-label="Alignment execution details">{JSON.stringify({ policy_model_record: run.policy_model_version, reference_model_record: run.reference_model_version, reward_model_record: run.reward_model_version, train_dataset_artifact: run.train_dataset_artifact, held_out_dataset_artifact: run.held_out_dataset_artifact, training_manifest: run.dataset_manifest_digest, validation_manifest: run.held_out_validation_digest, execution_pins: run.execution_pins, hyperparameters: run.hyperparameters, verifier: run.verifier_spec, output_model_version: run.output_model_version, latest_metrics: run.latest_metrics }, null, 2)}</pre></div>}
  </div></section>;
}
