import { Select, TextControl, Disclosure } from '../ui';
import { Identifier } from '../Identifier';
import { ModelHardwareFit } from '../ModelHardwareFit';
import { PreparedDatasetPreview } from '../TrainingDatasetPreview';
import { ResourcePicker } from '../ResourcePicker';
import { resourceHash } from '../../api/resource-routes';
import { workerHardware } from '../../api/model-hardware';
import type { useDraft } from '../Draft';
import type { useHardwareInventory } from '../useHardwareInventory';
import type { TrainingConfiguration } from '../../api/training-workspace';
import type { BudgetPolicy, DatasetRevision, ModelVersion, Runner, Tokenizer, WorkerPool } from '../../api/training';
import { ContinuedCorpusBuilder } from '../ContinuedCorpusBuilder';
import { useState } from 'react';

/** Every input of a run, editing the same draft as the wizard. */
export function AdvancedTrainingForm({ draft, tokenizers, models, datasetRevisions, pools, policies, runners, loading, busy, hardware, referenceRuntime, token, refreshKey }: {
  draft: ReturnType<typeof useDraft<TrainingConfiguration>>; tokenizers: Tokenizer[]; models: ModelVersion[]; datasetRevisions: DatasetRevision[]; pools: WorkerPool[];
  policies: BudgetPolicy[]; runners: Runner[]; loading: boolean; busy: boolean; hardware: ReturnType<typeof useHardwareInventory>; referenceRuntime: boolean; token: string; refreshKey: number;
}) {
  const [mode, setMode] = draft.field('mode'), [recipe, setRecipe] = draft.field('recipe');
  const [tokenizer, setTokenizer] = draft.field('tokenizer'), [base, setBase] = draft.field('base');
  const [selectedDataset, setSelectedDataset] = draft.field('selectedDataset'), [selectedPool, setSelectedPool] = draft.field('selectedPool');
  const [selectedPolicy, setSelectedPolicy] = draft.field('selectedPolicy'), [runner, setRunner] = draft.field('runner');
  const [seed, setSeed] = draft.field('seed'), [learningRate, setLearningRate] = draft.field('learningRate'), [validationInterval, setValidationInterval] = draft.field('validationInterval');
  const [, setModelName] = draft.field('modelName');
  const [, setPreset] = draft.field('preset'), [, setSteps] = draft.field('steps');
  const [corpusOpen, setCorpusOpen] = useState(false);
  const selectedModel = models.find(model => String(model.id) === base);
  const capability = selectedModel?.capabilities?.train;
  const registeredRevision = datasetRevisions.find(revision => String(revision.id) === selectedDataset);
  const worker = mode === 'worker';
  return <div className="training-advanced">
    <h2 className="training-full">Model, data and compute</h2>
    <Select label="Execution" value={mode} onChange={e => { setMode(e.target.value); setRecipe('full_sft'); setSelectedPool(''); setSelectedPolicy(''); setRunner(''); }}
      options={[{ value: 'worker', label: 'Local worker' }, { value: 'simulation', label: 'Synthetic run' }]} />
    <Select label="Training method" value={recipe} onChange={e => setRecipe(e.target.value)}>
      <option value="full_sft">Full fine-tuning</option>
      {worker && <option value="lora_adapter">LoRA adapter (GPU)</option>}
      {worker && <option value="qlora_adapter">QLoRA adapter, 4-bit (Apple GPU)</option>}
      {worker && <option value="continued_pretraining">Continued pretraining (GPU)</option>}
      {!worker && <><option value="lora_adapter">LoRA adapter</option><option value="continued_pretraining">Continued pretraining</option><option value="scratch_pretraining">Train from scratch</option></>}
    </Select>
    <Select label="Tokenizer version" required value={tokenizer} onChange={e => setTokenizer(e.target.value)} hint={<a href="#models">Register tokenizers and model versions in Models.</a>}>
      <option value="">Select a tokenizer</option>
      {tokenizers.map(t => <option key={t.tokenizer_id} value={t.id}>{t.name} · r{t.revision_no}{t.vocabulary_size ? ` (vocab ${t.vocabulary_size})` : ''}</option>)}
    </Select>
    {recipe !== 'scratch_pretraining' && <ResourcePicker label="Base model version" loading={loading} disabled={busy} required value={base} onChange={value => { setBase(value); setModelName(''); }}
      options={models.map(m => ({ value: String(m.id), id: m.model_version_id, name: m.model_name, revision: m.revision_no, state: m.state,
        href: resourceHash('model-version', m.model_version_id), description: m.capabilities?.train.reason,
        unavailable: worker && (!m.capabilities?.train.eligible || !m.capabilities.train.recipes.includes(recipe)) ? m.capabilities?.train.reason || 'This model does not support the selected training method.' : undefined }))} />}
    {base && worker && <div className="training-full"><ModelHardwareFit memory={selectedModel?.capabilities?.memory_requirements}
      targets={hardware.workers.filter(w => !selectedPool || String(w.pool) === selectedPool).map(w => workerHardware(w, hardware.reportedAt))}
      compatible={!capability || capability.eligible && capability.recipes.includes(recipe)}
      reason={capability?.eligible && !capability.recipes.includes(recipe) ? 'This model does not support the selected training method.' : capability?.reason} headingLevel={3} />
      {hardware.error && <p className="muted" role="status">Hardware inventory unavailable: {hardware.error}</p>}</div>}
    <ResourcePicker label="Dataset version" action={registeredRevision && <Identifier value={registeredRevision.manifest_digest} label="Dataset manifest digest" />} loading={loading} disabled={busy} required={worker} value={selectedDataset} onChange={setSelectedDataset}
      options={datasetRevisions.map(d => ({ value: String(d.id), id: d.revision_id, name: d.dataset_name || 'Dataset', revision: d.revision_no, state: d.state, description: `${d.row_count ?? 'Unknown'} examples`, href: resourceHash('dataset-revision', d.revision_id) }))} />
    {worker && recipe === 'continued_pretraining' && <Disclosure summary="Build a continued-pretraining corpus" variant="quiet" open={corpusOpen} onToggle={event => setCorpusOpen(event.currentTarget.open)}>{corpusOpen && <ContinuedCorpusBuilder key={refreshKey} token={token} revisions={datasetRevisions.map(d => ({ id: d.id, revision_id: d.revision_id, dataset_name: d.dataset_name, revision_no: d.revision_no, metadata: d.metadata as { preparation_kind?: string } | undefined }))} onPublished={id => { setSelectedDataset(String(id)); setPreset('custom'); setSteps('3'); }} />}</Disclosure>}
    {worker && registeredRevision && <div className="training-full"><PreparedDatasetPreview key={`${registeredRevision.revision_id}-${refreshKey}`} revisionId={registeredRevision.revision_id} token={token} /></div>}
    <Select label="Worker pool" disabled={!worker} required={worker} value={selectedPool} onChange={e => setSelectedPool(e.target.value)}>
      <option value="">Select a worker pool</option>
      {pools.map(p => <option key={p.id} value={p.id}>{p.name} ({p.queue_name || 'default queue'})</option>)}
    </Select>
    <Select label="Budget" disabled={!worker} required={worker} value={selectedPolicy} onChange={e => setSelectedPolicy(e.target.value)}>
      <option value="">Select a training-step budget</option>
      {policies.map(p => <option key={p.policy_id} value={p.policy_id} disabled={p.allowance !== undefined && Number(p.allowance.remaining_amount) <= 0}>{p.name} · {p.allowance?.remaining_amount ?? 'remaining unknown'} of {p.limit_amount} {p.unit}</option>)}
    </Select>
    {worker && <Select label="Training runner" required value={runner} onChange={e => setRunner(e.target.value)}>
      <option value="">Select a runtime manifest</option>
      {runners.map(r => <option key={r.manifest_id} value={r.id}>{r.name}</option>)}
    </Select>}
    <TextControl label="Initialization seed" disabled={worker} required type="number" min="0" max="2147483647" step="1" value={seed} onChange={e => setSeed(e.target.value)} />
    {worker && referenceRuntime && <>
      <TextControl label="Learning rate" type="number" min="0.000001" max="0.2" step="any" value={learningRate} placeholder="Runtime default" onChange={e => setLearningRate(e.target.value)} />
      <TextControl label="Validation interval" hint="0 disables validation." required type="number" min="0" max="1000" value={validationInterval} onChange={e => setValidationInterval(e.target.value)} />
    </>}
  </div>;
}
