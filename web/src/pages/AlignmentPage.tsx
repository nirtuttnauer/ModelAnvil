import { Identifier } from '../components/Identifier';
import { Button, Dialog, Disclosure, FileInput, KeyValueList, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { ConfigFields, RecordListEditor, VerifierFields } from '../components/FormEditors';
import { alignmentFields, objectInput, preferenceFields, recordsInput } from '../components/form-data';
import { useDraft, DraftIndicator } from '../components/Draft';
import { DataInspector } from '../components/DataInspector';
import { useEffect, useId, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources, type RegisteredModel } from '../api/resources';
import { alignmentAction, createAlignmentPlan, preferencePairs, registerPreferences, type AlignmentRun, type PreferenceArtifact } from '../api/alignment';
import { ResourceState } from '../components/ResourceState';
import { statusLabel } from '../api/status';
import { BarChart, ChartPanel, LineChart } from '../components/Charts';
import { numericEntries } from '../components/chart-data';
import './ml-pages.css';

const algorithms = [['dpo', 'Direct preference optimization'], ['reward_model', 'Bradley–Terry reward model'], ['ppo_rlhf', 'PPO RLHF'], ['verifier_rl', 'Verifier guided RL']];
type ModelInput = RegisteredModel & { metadata?: { model_role?: string } };
interface StepBudget { policy_id: string; name: string; unit: string; enabled: boolean }

export function AlignmentPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const planFormId = useId(), pairsFormId = useId();
  const draft = useDraft('alignment', { setup: false as boolean, upload: false as boolean, algorithm: 'dpo', policy: '', reference: '', reward: '', dataset: '', heldOut: '', steps: '10', hyperparameters: '{"learning_rate":0.05}', verifier: '{"type":"exact_match"}', artifactName: '', pairsJson: '', stepBudgetId: '' });
  const [runs, setRuns] = useState<AlignmentRun[]>([]), [models, setModels] = useState<ModelInput[]>([]), [artifacts, setArtifacts] = useState<PreferenceArtifact[]>([]);
  const [stepBudgets, setStepBudgets] = useState<StepBudget[]>([]), [stepBudgetId, setStepBudgetId] = draft.field('stepBudgetId');
  const [loading, setLoading] = useState(true), [error, setError] = useState<string | null>(null), [retry, setRetry] = useState(0), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const [setup, setSetup] = draft.field('setup'), [upload, setUpload] = draft.field('upload'), [algorithm, setAlgorithm] = draft.field('algorithm');
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
      setRuns(current => [r, ...current]); setSelected(r.run_id); setSetup(false); setNotice('Alignment plan saved with verified preference bytes. Execute when ready.');
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
  async function importPairs(file: File | undefined) {
    if (!file) return;
    if (file.size > 256 * 1024) { setError('Preference files support at most 256 KiB.'); return; }
    try { const raw = await file.text(); preferencePairs(raw); setPairsJson(raw); } catch (error) { setError(errorMessage(error)); }
  }
  function modelSelect(title: string, value: string, change: (value: string) => void, required = false, rewardOnly = false) {
    const available = models.filter(m => rewardOnly ? m.metadata?.model_role === 'reward_model' : m.metadata?.model_role !== 'reward_model');
    return <Select label={title} required={required} disabled={busy} value={value} onChange={e => change(e.target.value)}><option value="">{required ? 'Select a model version' : 'None'}</option>{available.map(m => <option key={m.id} value={m.id}>{m.model_name} · r{m.revision_no}</option>)}</Select>;
  }
  function artifactSelect(title: string, value: string, change: (value: string) => void) {
    return <Select label={title} required disabled={busy} value={value} onChange={e => change(e.target.value)}><option value="">Select committed preference bytes</option>{artifacts.map(a => <option key={a.artifact_id} value={a.artifact_id}>{a.name} · {a.row_count} pairs</option>)}</Select>;
  }
  const run = runs.find(r => r.run_id === selected) || runs[0];
  const runLabel = (id: string) => `Alignment run ${runs.findIndex(item => item.run_id === id) + 1}`;
  const recordedMetrics = numericEntries(run?.latest_metrics);
  const focusedMetric = recordedMetrics.find(m => m.label === metricKey) || recordedMetrics.find(m => ['loss', 'policy loss', 'reward margin'].includes(m.label)) || recordedMetrics.find(m => m.label !== 'step' && m.label !== 'cpu seconds') || recordedMetrics[0];
  const metric = focusedMetric?.label.replaceAll(' ', '_');
  const points = (run?.metrics_history || []).flatMap((entry, index) => typeof entry[metric || ''] === 'number' ? [{ x: typeof entry.step === 'number' ? entry.step : index + 1, y: entry[metric || ''] as number }] : []);
  const modelName = (id: number | null | undefined) => { const m = models.find(model => model.id === id); return m ? `${m.model_name} · r${m.revision_no}` : id == null ? 'Not configured' : 'Model unavailable'; };
  const artifactName_ = (id: string | null | undefined, fallback: string) => artifacts.find(item => item.artifact_id === id)?.name || fallback;

  return <div className="ml-page">
    <Section title="Alignment runs" description="Train pinned CPU character models from preference pairs." actions={<>
      <Select aria-label="Alignment run to visualize" value={run?.run_id || ''} onChange={e => setSelected(e.target.value)}>
        <option value="" disabled>Select an alignment run</option>{runs.map(r => <option key={r.run_id} value={r.run_id}>{runLabel(r.run_id)} · {r.algorithm} · {statusLabel(r.status)}</option>)}
      </Select>
      <Button type="button" variant="primary" disabled={loading || busy} onClick={() => setSetup(true)}>New alignment plan</Button>
      <Button type="button" disabled={loading || busy} onClick={() => setUpload(true)}>Register preference pairs</Button>
    </>}>
      <ResourceState loading={loading && !runs.length} error={error} onRetry={() => setRetry(v => v + 1)} />
      {notice && <Notice tone="success" role="status">{notice}</Notice>}
      {!loading && !error && !runs.length && <EmptyState title="No alignment runs yet" description="Register preference pairs, then create an alignment plan." />}
      {run && <div className="ml-run">
        <div className="ml-run-head"><h3>{runLabel(run.run_id)}</h3><StatusBadge status={run.status} />{run.output_model_version && <span className="muted">Candidate: {modelName(run.output_model_version)}</span>}</div>
        <p className="muted">{run.execution_capabilities?.reason || 'Bounded CPU character execution supports four alignment recipes. Candidate weights require independent evaluation.'}</p>
        <div className="ml-progress"><span>Committed steps</span><strong>{run.current_step} / {run.total_steps}</strong><progress value={run.current_step} max={run.total_steps || 1} aria-label="Alignment committed steps" /></div>
        <div data-ui="actions">
          <Button type="button" variant="primary" disabled={busy || !run.execution_capabilities?.can_execute} onClick={() => void execute('execute')}>{busy ? 'Updating alignment…' : 'Execute CPU alignment'}</Button>
          {['pending', 'running'].includes(run.status) && <Button type="button" disabled={cancelBusy} onClick={() => void execute('cancel')}>{cancelBusy ? 'Cancelling alignment…' : 'Cancel alignment'}</Button>}
          <Button type="button" variant="quiet" disabled={busy || loading} onClick={() => setRetry(v => v + 1)}>Refresh alignment runs</Button>
        </div>
        <KeyValueList columns={2} items={[
          { label: 'Algorithm', value: algorithms.find(([key]) => key === run.algorithm)?.[1] || run.algorithm },
          { label: 'Policy model', value: modelName(run.policy_model_version) },
          { label: 'Reference model', value: modelName(run.reference_model_version) },
          { label: 'Reward model', value: modelName(run.reward_model_version) },
          { label: 'Training pairs', value: artifactName_(run.train_dataset_artifact, 'Training artifact') },
          { label: 'Held-out pairs', value: artifactName_(run.held_out_dataset_artifact, 'Held-out artifact') },
          { label: 'Stop reason', value: run.stop_reason || 'None' },
          { label: 'Run ID', value: <Identifier value={run.run_id} label="Run ID" display="code" /> },
        ]} />
        <ChartPanel title={points.length ? 'Recorded optimizer history' : 'Latest metric snapshot'} description={run ? `${runLabel(run.run_id)} · ${run.algorithm}` : 'Metrics appear after execution.'} action={recordedMetrics.length > 0 && <Select aria-label="Alignment metric to visualize" value={focusedMetric?.label || ''} onChange={e => setMetricKey(e.target.value)}>{recordedMetrics.map(m => <option key={m.label}>{m.label}</option>)}</Select>}>
          {points.length ? <LineChart series={[{ name: focusedMetric?.label || 'Metric', points }]} yLabel={focusedMetric?.label} /> : <BarChart data={focusedMetric ? [focusedMetric] : []} unit={focusedMetric?.label || 'Recorded value'} emptyMessage="No numeric alignment metrics have been recorded. Pending plans have no measured preference scores." />}
        </ChartPanel>
        {run.execution_evidence && <p className="ml-footnote">{run.execution_evidence.source}</p>}
        <Disclosure summary="Details" variant="quiet">
          <p className="muted">Training manifest <Identifier value={run.dataset_manifest_digest} label="Training manifest digest" display="code" /> · Held-out manifest <Identifier value={run.held_out_validation_digest} label="Held-out validation digest" display="code" /></p>
          <DataInspector value={{ policy_model_record: run.policy_model_version, reference_model_record: run.reference_model_version, reward_model_record: run.reward_model_version, train_dataset_artifact: run.train_dataset_artifact, held_out_dataset_artifact: run.held_out_dataset_artifact, training_manifest: run.dataset_manifest_digest, validation_manifest: run.held_out_validation_digest, execution_pins: run.execution_pins, hyperparameters: run.hyperparameters, verifier: run.verifier_spec, output_model_version: run.output_model_version, latest_metrics: run.latest_metrics }} />
        </Disclosure>
      </div>}
    </Section>
    <Section title="History" description="Configuration, execution state and recorded stop reasons.">
      {!loading && !error && !runs.length && <p className="muted">No alignment runs yet.</p>}
      {!!runs.length && <div className="table-scroll" tabIndex={0}><RecordTable>
        <thead><tr><th>Run</th><th>Algorithm</th><th>State</th><th>Progress</th><th>Stop reason</th></tr></thead>
        <tbody>{runs.map(r => <tr key={r.run_id} aria-selected={run?.run_id === r.run_id || undefined}>
          <td><Button type="button" variant="quiet" size="sm" onClick={() => setSelected(r.run_id)}>{runLabel(r.run_id)}</Button></td>
          <td>{r.algorithm}</td><td><StatusBadge status={r.status} /></td><td>{r.current_step}/{r.total_steps}</td><td>{r.stop_reason || 'None'}</td>
        </tr>)}</tbody>
      </RecordTable></div>}
    </Section>
    <Dialog title="New alignment plan" description="Pin the models, preference bytes and optimizer settings for a bounded CPU run." open={setup} onClose={() => setSetup(false)} size="lg"
      footer={<><Button type="button" disabled={busy} onClick={() => setSetup(false)}>Cancel</Button><Button form={planFormId} type="submit" variant="primary" disabled={busy || !policy || !dataset || !heldOut || dataset === heldOut}>Create alignment configuration</Button></>}>
      <form id={planFormId} data-ui="form" onSubmit={create}>
        <DraftIndicator draft={draft} disabled={busy} />
        {error && setup && <Notice tone="error" role="alert">{error}</Notice>}
        <div data-ui="field-grid">
          <Select label="Algorithm" disabled={busy} value={algorithm} onChange={e => setAlgorithm(e.target.value)} options={algorithms.map(([value, label]) => ({ value, label }))} />
          <TextControl label="Total steps" required disabled={busy} type="number" min="1" max="100" value={steps} onChange={e => setSteps(e.target.value)} />
          {modelSelect('Policy model version', policy, setPolicy, true)}
          {modelSelect('Reference model version', reference, setReference, ['dpo', 'ppo_rlhf'].includes(algorithm))}
          {algorithm === 'ppo_rlhf' && modelSelect('Trained reward model version', reward, setReward, true, true)}
          {artifactSelect('Training preference artifact', dataset, setDataset)}
          {artifactSelect('Held-out preference artifact', heldOut, setHeldOut)}
          <Select label="Alignment step budget" disabled={busy} required={stepBudgets.length > 1} value={stepBudgetId} onChange={e => setStepBudgetId(e.target.value)}>
            <option value="">{stepBudgets.length ? 'Choose a training step budget' : 'No enabled training step policy'}</option>{stepBudgets.map(b => <option key={b.policy_id} value={b.policy_id}>{b.name} · training_steps</option>)}
          </Select>
        </div>
        <ConfigFields title="Optimizer settings" fields={alignmentFields(algorithm)} value={hyperparameters} onChange={setHyperparameters} disabled={busy} />
        {algorithm === 'verifier_rl' && <VerifierFields value={verifier} onChange={setVerifier} disabled={busy} />}
        <p className="muted">CPU execution supports 1–100 steps. Learning rate 0.000001–0.2; DPO beta 0.001–1. PPO needs a trained reward model with the same tokenizer.</p>
      </form>
    </Dialog>
    <Dialog title="Register preference pairs" description="Commit prompt, preferred and rejected responses as an immutable artifact." open={upload} onClose={() => setUpload(false)} size="lg"
      footer={<><Button type="button" disabled={busy} onClick={() => setUpload(false)}>Cancel</Button><Button form={pairsFormId} type="submit" variant="primary" disabled={busy}>Commit preference artifact</Button></>}>
      <form id={pairsFormId} data-ui="form" onSubmit={register}>
        <DraftIndicator draft={draft} disabled={busy} />
        {error && upload && <Notice tone="error" role="alert">{error}</Notice>}
        <div data-ui="field-grid">
          <TextControl label="Preference artifact name" required maxLength={200} disabled={busy} value={artifactName} onChange={e => setArtifactName(e.target.value)} />
          <FileInput label="Import preference file" hint="JSON, up to 256 KiB." accept="application/json,.json" disabled={busy} onChange={e => void importPairs(e.target.files?.[0])} />
        </div>
        <RecordListEditor title="Preference pairs" itemName="Preference pair" fields={preferenceFields} maximum={32} value={pairsJson} onChange={setPairsJson} disabled={busy} description="Write a prompt and compare the preferred and rejected responses." />
        <p className="muted">Register 1–32 unique pairs. Responses support up to 32 characters; prompt plus response up to 62. Use a separate artifact with disjoint held-out prompts.</p>
      </form>
    </Dialog>
  </div>;
}
