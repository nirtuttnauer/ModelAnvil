import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field, Notice, RecordTable, WorkspaceTabs } from '../components/ui';
import { RunDetailHeader } from '../components/RunHistory';
import { ResourcePicker } from '../components/ResourcePicker';
import { resourceHash } from '../api/resource-routes';
import { ConfigFields, RecordListEditor, VerifierFields } from '../components/FormEditors';
import { alignmentFields, objectInput, preferenceFields, recordsInput } from '../components/form-data';
import { useDraft, DraftStatus } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
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


export function AlignmentPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const draft = useDraft('alignment', { setup: false as boolean, upload: false as boolean, algorithm: 'dpo', policy: '', reference: '', reward: '', dataset: '', heldOut: '', steps: '10', hyperparameters: '{"learning_rate":0.05}', verifier: '{"type":"exact_match"}', artifactName: '', pairsJson: '', stepBudgetId: '' });
  const [runs, setRuns] = useState<AlignmentRun[]>([]), [models, setModels] = useState<ModelInput[]>([]), [artifacts, setArtifacts] = useState<PreferenceArtifact[]>([]);
  const [stepBudgets, setStepBudgets] = useState<StepBudget[]>([]), [stepBudgetId, setStepBudgetId] = draft.field('stepBudgetId');
  const [loading, setLoading] = useState(true), [error, setError] = useState<string | null>(null), [retry, setRetry] = useState(0), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [setup, setSetup] = draft.field('setup'), [upload, setUpload] = draft.field('upload'), [algorithm, setAlgorithm] = draft.field('algorithm');
  const [tab, setTab] = useState<'setup' | 'run' | 'history'>('run');
  const [policy, setPolicy] = draft.field('policy'), [reference, setReference] = draft.field('reference'), [reward, setReward] = draft.field('reward'), [dataset, setDataset] = draft.field('dataset'), [heldOut, setHeldOut] = draft.field('heldOut');
  const [steps, setSteps] = draft.field('steps'), [hyperparameters, setHyperparameters] = draft.field('hyperparameters'), [verifier, setVerifier] = draft.field('verifier');
  const [selected, setSelected] = useState(''), [metricKey, setMetricKey] = useState(''), [artifactName, setArtifactName] = draft.field('artifactName'), [pairsJson, setPairsJson] = draft.field('pairsJson');
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
  useEffect(() => { setSelected('');  setBusy(false); setExecutingId(''); setCancelBusy(false); return () => { actionRequest.current?.abort(); actionRequest.current = null; cancelRequest.current?.abort(); cancelRequest.current = null; }; }, [token]);
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
      const params = objectInput(hyperparameters);
      if (stepBudgetId) params.budget_policy_id = stepBudgetId;
      if (stepBudgets.length > 1 && !params.budget_policy_id) throw new Error('Select an alignment step budget.');
      const r = await createAlignmentPlan(token, { algorithm, policy_model_version: Number(policy), reference_model_version: reference ? Number(reference) : null, reward_model_version: reward ? Number(reward) : null, train_dataset_artifact: dataset, held_out_dataset_artifact: heldOut, total_steps: Number(steps), hyperparameters: params, verifier_spec: { type: 'exact_match', ...objectInput(verifier) } }, signal);
      if (signal.aborted) return;
      setRuns(current => [r, ...current]); setSelected(r.run_id); setSetup(false); setTab('run'); setNotice('Alignment plan saved with verified preference bytes. Execute when ready.');
    });
  }
  async function register(e: React.FormEvent) {
    e.preventDefault();
    await act(async signal => {
      const artifact = await registerPreferences(token, artifactName, preferencePairs(JSON.stringify(recordsInput(pairsJson, preferenceFields, 32))), signal);
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
    return <ResourcePicker label={title} value={value} onChange={change} required={required} disabled={busy} loading={loading} placeholder={required ? 'Select an exact revision' : 'None'} options={available.map(m => ({ value: String(m.id), id: m.model_version_id, name: m.model_name, revision: m.revision_no, state: m.state, href: resourceHash('model-version', m.model_version_id) }))} />;
  }
  function artifactSelect(title: string, value: string, change: (value: string) => void) {
    return <div><label>{title}<select required disabled={busy} value={value} onChange={e => change(e.target.value)}><option value="">Select committed preference bytes</option>{artifacts.map(a => <option key={a.artifact_id} value={a.artifact_id}>{a.name} · {a.row_count} pairs</option>)}</select></label>{value && <Identifier value={artifacts.find(a => a.artifact_id === value)?.sha256} label={`${title} SHA-256`} />}</div>;
  }
  const run = runs.find(r => r.run_id === selected) || runs[0];
  const runLabel = (id: string) => `Alignment run ${runs.findIndex(item => item.run_id === id) + 1}`;
  const recordedMetrics = numericEntries(run?.latest_metrics);
  const focusedMetric = recordedMetrics.find(m => m.label === metricKey) || recordedMetrics.find(m => ['loss', 'policy loss', 'reward margin'].includes(m.label)) || recordedMetrics.find(m => m.label !== 'step' && m.label !== 'cpu seconds') || recordedMetrics[0];
  const metric = focusedMetric?.label.replaceAll(' ', '_');
  const points = (run?.metrics_history || []).flatMap((entry, index) => typeof entry[metric || ''] === 'number' ? [{ x: typeof entry.step === 'number' ? entry.step : index + 1, y: entry[metric || ''] as number }] : []);
  const modelName = (id: number | null | undefined) => { const m = models.find(model => model.id === id); return m ? `${m.model_name} · r${m.revision_no}` : id == null ? 'Not configured' : 'Model unavailable'; };
  return <><div className="page-actions"><Button disabled={loading || busy} onClick={() => { if (tab === 'setup' && upload) setUpload(false); else { setTab('setup'); setUpload(true); } }}>{tab === 'setup' && upload ? 'Close preferences' : 'Register preference pairs'}</Button><Button className="primary" disabled={loading || busy} onClick={() => { if (tab === 'setup' && setup) setSetup(false); else { setTab('setup'); setSetup(true); } }}>{tab === 'setup' && setup ? 'Close setup' : 'New alignment plan'}</Button></div><Card className="panel ml-page ml-main-panel ml-alignment"><div className="panel-body">
    <div className="ml-stat-strip" aria-label="Alignment summary"><div><span>Alignment runs</span><strong>{loading ? '—' : runs.length}</strong><small>Recorded plans and results</small></div><div><span>Active runs</span><strong>{loading ? '—' : runs.filter(r => ['pending', 'running'].includes(r.status)).length}</strong><small>Pending or running</small></div><div><span>Preference artifacts</span><strong>{loading ? '—' : artifacts.length}</strong><small>Committed inputs</small></div><div><span>Selected progress</span><strong>{run ? `${run.current_step} / ${run.total_steps}` : '—'}</strong><small>Committed steps</small></div></div>
    <Notice as="p" className="notice">{run?.execution_capabilities?.reason || 'Bounded CPU character execution supports four alignment recipes. Candidate weights require independent evaluation.'}</Notice>
    {run?.execution_evidence && <p className="muted">{run.execution_evidence.source}</p>}
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />{notice && <Notice as="p" tone="success" className="notice success" role="status">{notice}</Notice>}
    <WorkspaceTabs label="Alignment workspace" value={tab} onChange={setTab} tabs={[{ value: 'setup', label: 'Setup' }, { value: 'run', label: 'Run' }, { value: 'history', label: 'History' }]}>
    <div hidden={tab !== 'setup'}>
    {upload && <form className="form-grid" onSubmit={register}><DraftStatus draft={draft} disabled={busy} /><label>Preference artifact name<Field required maxLength={200} disabled={busy} value={artifactName} onChange={e => setArtifactName(e.target.value)} /></label><label>Import preference file<input type="file" accept="application/json,.json" disabled={busy} onChange={async e => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 256 * 1024) { setError('Preference files support at most 256 KiB.'); return; } try { const raw = await file.text(); preferencePairs(raw); setPairsJson(raw); } catch (error) { setError(errorMessage(error)); } }} /></label><RecordListEditor title="Preference pairs" itemName="Preference pair" fields={preferenceFields} maximum={32} value={pairsJson} onChange={setPairsJson} disabled={busy} description="Write a prompt and compare the preferred and rejected responses." /><p className="muted full-width">Register 1–32 unique pairs. Responses support up to 32 characters; prompt plus response supports 62. Create a separate artifact with disjoint held-out prompts. Execution checks every character against the model vocabulary.</p><Button className="primary" disabled={busy}>Commit preference artifact</Button></form>}
    {setup && <form className="form-grid" onSubmit={create}><DraftStatus draft={draft} disabled={busy} /><label>Algorithm<select disabled={busy} value={algorithm} onChange={e => setAlgorithm(e.target.value)}>{algorithms.map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select></label>{modelSelect('Policy model version', policy, setPolicy, true)}{modelSelect('Reference model version', reference, setReference, ['dpo', 'ppo_rlhf'].includes(algorithm))}{algorithm === 'ppo_rlhf' && modelSelect('Trained reward model version', reward, setReward, true, true)}{artifactSelect('Training preference artifact', dataset, setDataset)}{artifactSelect('Held-out preference artifact', heldOut, setHeldOut)}<label>Total steps<Field required disabled={busy} type="number" min="1" max="100" value={steps} onChange={e => setSteps(e.target.value)} /></label><label>Alignment step budget<select disabled={busy} required={stepBudgets.length > 1} value={stepBudgetId} onChange={e => setStepBudgetId(e.target.value)}><option value="">{stepBudgets.length ? 'Choose a training step budget' : 'No enabled training step policy'}</option>{stepBudgets.map(b => <option key={b.policy_id} value={b.policy_id}>{b.name} · training_steps</option>)}</select></label><ConfigFields title="Optimizer settings" fields={alignmentFields(algorithm)} value={hyperparameters} onChange={setHyperparameters} disabled={busy} />{algorithm === 'verifier_rl' && <VerifierFields value={verifier} onChange={setVerifier} disabled={busy} />}<p className="muted full-width">The server computes digests from committed preference bytes. CPU execution supports 1–100 steps. Learning rate: 0.000001–0.2; DPO beta: 0.001–1. PPO requires a trained reward model with the same tokenizer. The selected training_steps policy reserves the configured step count and settles only committed steps.</p><Button className="primary" disabled={busy || !policy || !dataset || !heldOut || dataset === heldOut}>Create alignment configuration</Button></form>}
    </div>
    <div hidden={tab !== 'run'}>
    <div className="ml-section-heading"><div><span className="ml-eyebrow">PREFERENCE OPTIMIZATION</span><h3>Recorded alignment metrics</h3><p>Selected measurements and committed step history, without inferred scores.</p></div><label>Inspect run<select aria-label="Alignment run to visualize" value={run?.run_id || ''} onChange={e => setSelected(e.target.value)}><option value="" disabled>Select an alignment run</option>{runs.map(r => <option key={r.run_id} value={r.run_id}>{runLabel(r.run_id)} · {r.algorithm} · {r.status}</option>)}</select></label></div>
    {run && <div className="actions"><Button className="primary" disabled={busy || !run.execution_capabilities?.can_execute} onClick={() => void execute('execute')}>{busy ? 'Updating alignment…' : 'Execute CPU alignment'}</Button>{['pending', 'running'].includes(run.status) && <Button disabled={cancelBusy} onClick={() => void execute('cancel')}>{cancelBusy ? 'Cancelling alignment…' : 'Cancel alignment'}</Button>}<Button disabled={busy || loading} onClick={() => setRetry(v => v + 1)}>Refresh alignment runs</Button>{run.output_model_version && <span className="muted">Candidate: {modelName(run.output_model_version)}</span>}</div>}
    <div className="visualization-grid"><ChartPanel title={points.length ? 'Recorded optimizer history' : 'Latest metric snapshot'} description={run ? `${runLabel(run.run_id)} · ${run.algorithm}` : 'Metrics appear after execution.'} action={recordedMetrics.length > 0 && <select aria-label="Alignment metric to visualize" value={focusedMetric?.label || ''} onChange={e => setMetricKey(e.target.value)}>{recordedMetrics.map(m => <option key={m.label}>{m.label}</option>)}</select>}>{points.length ? <LineChart series={[{ name: focusedMetric?.label || 'Metric', points }]} yLabel={focusedMetric?.label} /> : <BarChart data={focusedMetric ? [focusedMetric] : []} unit={focusedMetric?.label || 'Recorded value'} emptyMessage="No numeric alignment metrics have been recorded. Pending plans have no measured preference scores." />}</ChartPanel><ChartPanel title="Pinned execution inputs" description="Model versions, preference bytes, and output candidate.">{run ? <><EventTimeline events={[{ label: 'Policy model', detail: modelName(run.policy_model_version), status: 'completed' }, { label: 'Reference model', detail: modelName(run.reference_model_version), status: run.reference_model_version == null ? 'pending' : 'completed' }, { label: 'Reward model', detail: modelName(run.reward_model_version), status: run.reward_model_version == null ? 'pending' : 'completed' }, { label: 'Training / held-out bytes', detail: `${artifacts.find(item => item.artifact_id === run.train_dataset_artifact)?.name || 'Training artifact'} / ${artifacts.find(item => item.artifact_id === run.held_out_dataset_artifact)?.name || 'Held-out artifact'}`, status: run.train_dataset_artifact && run.held_out_dataset_artifact ? 'completed' : 'pending' }]} /><p className="muted">Training manifest <Identifier value={run.dataset_manifest_digest} label="Training manifest digest" /> · Held-out manifest <Identifier value={run.held_out_validation_digest} label="Held-out validation digest" /></p><div className="ml-run-progress"><span>Committed steps</span><strong>{run.current_step} / {run.total_steps}</strong><progress value={run.current_step} max={run.total_steps || 1} aria-label="Alignment committed steps" /></div></> : <ChartEmpty message="Configure an alignment run to inspect pinned models and preference artifacts." />}</ChartPanel></div>
    </div>
    <div hidden={tab !== 'history'}>
    <div className="ml-section-heading"><div><h3>Alignment history</h3><p>Configuration, execution state, and recorded stop reasons.</p></div></div>{!loading && !error && !runs.length && <p className="muted">No alignment runs yet.</p>}{!!runs.length && <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table"><thead><tr><th>Run</th><th>Algorithm</th><th>State</th><th>Progress</th><th>Stop reason</th></tr></thead><tbody>{runs.map(r => <tr key={r.run_id} className={run?.run_id === r.run_id ? 'ml-selected-row' : undefined}><td><Button className="text-button" onClick={() => setSelected(r.run_id)}>{runLabel(r.run_id)}</Button> <Identifier value={r.run_id} label="Run ID" /></td><td>{r.algorithm}</td><td><Badge className={`state state-${r.status}`}>{r.status}</Badge></td><td>{r.current_step}/{r.total_steps}</td><td>{r.stop_reason || '—'}</td></tr>)}</tbody></RecordTable></div>}    {selected && run && <div className="detail-box"><RunDetailHeader title={runLabel(run.run_id)} id={run.run_id} status={run.status} onClose={() => setSelected('')} /><DataInspector value={{ policy_model_record: run.policy_model_version, reference_model_record: run.reference_model_version, reward_model_record: run.reward_model_version, train_dataset_artifact: run.train_dataset_artifact, held_out_dataset_artifact: run.held_out_dataset_artifact, training_manifest: run.dataset_manifest_digest, validation_manifest: run.held_out_validation_digest, execution_pins: run.execution_pins, hyperparameters: run.hyperparameters, verifier: run.verifier_spec, output_model_version: run.output_model_version, latest_metrics: run.latest_metrics }} title="Alignment execution details" /></div>}
    </div>
  </WorkspaceTabs></div></Card></>;
}
