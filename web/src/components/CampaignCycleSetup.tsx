import { useEffect, useState } from 'react';
import { allResources } from '../api/resources';
import { errorMessage } from '../api/client';
import { Field } from './ui';

export interface CampaignCycleConfig {
  base_model_version: string; runner_manifest: number; training_pool: number; training_budget: string;
  evaluation_suite: string; evaluation_pool: number; evaluation_budget: string;
  steps_per_cycle: number; max_training_steps: number; max_evaluation_cases: number; max_tokens: number; min_accuracy: number;
}
export const emptyCycle: CampaignCycleConfig = { base_model_version: '', runner_manifest: 0, training_pool: 0, training_budget: '', evaluation_suite: '', evaluation_pool: 0, evaluation_budget: '', steps_per_cycle: 10, max_training_steps: 30, max_evaluation_cases: 100, max_tokens: 8, min_accuracy: 0.7 };
interface Options {
  models: { model_version_id: string; model_name: string; revision_no: number; architecture_ref: string }[];
  runners: { id: number; name: string; enabled: boolean }[];
  pools: { id: number; name: string; status: string }[];
  policies: { policy_id: string; name: string; enabled: boolean; unit: string; currency: string }[];
  suites: { suite_version_id: string; suite_name?: string; suite: number; revision_no: number; protected_role: string }[];
}
export function CampaignCycleSetup({ token, value, onChange }: { token: string; value: CampaignCycleConfig; onChange: (value: CampaignCycleConfig) => void }) {
  const [options, setOptions] = useState<Options | null>(null), [error, setError] = useState('');
  useEffect(() => {
    const c = new AbortController();
    Promise.all([allResources<Options['models'][number]>('/api/v1/model-versions/', token, c.signal),
      allResources<Options['runners'][number]>('/api/v1/runner-manifests/', token, c.signal),
      allResources<Options['pools'][number]>('/api/v1/worker-pools/', token, c.signal),
      allResources<Options['policies'][number]>('/api/v1/budget-policies/', token, c.signal),
      allResources<Options['suites'][number]>('/api/v1/evaluation-suite-versions/', token, c.signal)])
      .then(([models, runners, pools, policies, suites]) => { if (!c.signal.aborted) setOptions({ models, runners, pools, policies, suites }); })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => c.abort();
  }, [token]);
  function field<K extends keyof CampaignCycleConfig>(name: K, next: CampaignCycleConfig[K]) { onChange({ ...value, [name]: next }); }
  return <fieldset className="full-width annotation-setup-section"><legend>Reviewed training and qualification</legend>
    <p>Closing a reviewed batch queues real CPU training. Check the cycle after training to queue protected evaluation. Only candidates that meet the accuracy gate and match or improve the baseline become the next drafting model. Source groups reserved for evaluation stay out of training.</p>
    <p>Costs in currency are unmeasured. Training steps and evaluation cases have separate hard caps and budget policies; this mode makes no dollar-cost guarantee.</p>
    {error && <p role="alert">{error}</p>}{!options && !error && <p role="status">Loading cycle resources…</p>}
    <div className="form-grid">
      <label>Training base model<select required value={value.base_model_version} onChange={e => field('base_model_version', e.target.value)}><option value="">Select a CPU character model</option>{options?.models.filter(m => m.architecture_ref === 'modelanvil.cpu-character-sft.v1').map(m => <option key={m.model_version_id} value={m.model_version_id}>{m.model_name} · r{m.revision_no}</option>)}</select></label>
      <label>Training runner<select required value={value.runner_manifest || ''} onChange={e => field('runner_manifest', Number(e.target.value))}><option value="">Select an enabled runner</option>{options?.runners.filter(r => r.enabled).map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      {(['training', 'evaluation'] as const).map(stage => <label key={stage}>{stage === 'training' ? 'Training worker pool' : 'Evaluation worker pool'}<select required value={value[`${stage}_pool`] || ''} onChange={e => field(`${stage}_pool`, Number(e.target.value))}><option value="">Select an active pool</option>{options?.pools.filter(p => p.status === 'active').map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>)}
      {(['training', 'evaluation'] as const).map(stage => <label key={stage}>{stage === 'training' ? 'Training step budget' : 'Evaluation case budget'}<select required value={value[`${stage}_budget`]} onChange={e => field(`${stage}_budget`, e.target.value)}><option value="">Select a quantity budget</option>{options?.policies.filter(p => p.enabled && !p.currency && p.unit === (stage === 'training' ? 'training_steps' : 'evaluation_cases')).map(p => <option key={p.policy_id} value={p.policy_id}>{p.name}</option>)}</select></label>)}
      <label>Protected evaluation suite<select required value={value.evaluation_suite} onChange={e => field('evaluation_suite', e.target.value)}><option value="">Select a protected suite version</option>{options?.suites.filter(s => s.protected_role === 'protected_eval').map(s => <option key={s.suite_version_id} value={s.suite_version_id}>{s.suite_name || `Suite ${s.suite}`} · r{s.revision_no}</option>)}</select></label>
      {([['steps_per_cycle', 'Training steps per cycle', 1, 100], ['max_training_steps', 'Campaign training-step cap', 1, 10000], ['max_evaluation_cases', 'Campaign evaluation-case cap', 1, 10000], ['max_tokens', 'Generated tokens per audit case', 1, 32], ['min_accuracy', 'Minimum protected accuracy', 0, 1]] as const).map(([key, label, min, max]) => <label key={key}>{label}<Field required type="number" min={min} max={max} step={key === 'min_accuracy' ? 0.01 : 1} value={value[key]} onChange={e => field(key, Number(e.target.value))} /></label>)}
    </div>
  </fieldset>;
}
