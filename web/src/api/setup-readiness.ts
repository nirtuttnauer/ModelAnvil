import type { RegisteredModelVersion, TokenizerVersion } from './resources';

export interface SetupPool { id: number; name: string; status: string }
export interface SetupBudget { policy_id: string; name: string; enabled: boolean; unit: string; currency: string; limit_amount: string }
export interface SetupDataset { state: string; manifest_digest: string; manifest_artifact: string | null; row_count: number }
export interface SetupWorker { pool: number; status: string; slots: number; connection_state?: string; capabilities: { training_runtime?: string; memory_bytes?: number } }
export interface SetupRunner {
  enabled: boolean;
  compatibility: { contract_digest?: string };
  manifest: { resources?: { memory_bytes?: number }; capabilities?: Array<{ kind: string; architectures?: string[] }> };
}
export type SetupModel = RegisteredModelVersion & { artifact_manifest_id?: string };

export function setupReadiness(data: {
  datasets: SetupDataset[]; tokenizers: TokenizerVersion[]; models: SetupModel[];
  pools: SetupPool[]; workers: SetupWorker[]; budgets: SetupBudget[]; runners: SetupRunner[];
}) {
  const tokenizers = data.tokenizers.filter(t => t.vocabulary_size > 0);
  const models = data.models.filter(m => m.state !== 'retired' && !!m.artifact_manifest_id && tokenizers.some(t => t.id === m.tokenizer));
  const readyPools = data.pools.filter(pool => pool.status === 'active' && data.workers.some(worker =>
    worker.pool === pool.id && worker.connection_state === 'connected' && worker.status === 'available' && worker.slots > 0 && data.runners.some(runner => {
      const contract = runner.compatibility?.contract_digest;
      const memory = runner.manifest?.resources?.memory_bytes;
      return runner.enabled && !!contract && worker.capabilities?.training_runtime === contract &&
        typeof memory === 'number' && memory > 0 && typeof worker.capabilities?.memory_bytes === 'number' && worker.capabilities?.memory_bytes >= memory &&
        Array.isArray(runner.manifest?.capabilities) && runner.manifest.capabilities.some(c => c.kind === 'train' && c.architectures?.some(a => models.some(m => m.architecture_ref === a)));
    })));
  return {
    datasetCount: data.datasets.filter(d => d.state === 'published' && /^[a-f0-9]{64}$/.test(d.manifest_digest) && !!d.manifest_artifact && d.row_count > 0).length,
    tokenizerCount: tokenizers.length, modelVersionCount: models.length, workerPoolCount: readyPools.length,
    budgetPolicyCount: data.budgets.filter(b => b.enabled && b.unit === 'training_steps' && !b.currency && Number.isFinite(Number(b.limit_amount)) && Number(b.limit_amount) > 0).length,
    firstTokenizerName: tokenizers[0]?.name, firstModelName: models[0]?.model_name,
  };
}

export interface SetupReadinessState {
  hasConnection: boolean;
  datasetCount: number; tokenizerCount: number; modelVersionCount: number; workerPoolCount: number; budgetPolicyCount: number;
  firstTokenizerName?: string; firstModelName?: string;
  compute: { available: boolean; message: string } | null;
}

export type SetupItemId = 'connection' | 'project' | 'dataset' | 'model' | 'compute' | 'budget';
export interface SetupItem {
  id: SetupItemId; title: string; detail: string; ready: boolean;
  action: { kind: 'connection' | 'project' | 'page'; page?: 'Training' | 'Datasets' | 'Models' | 'Infrastructure' | 'Budgets'; label: string };
}

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? '' : 's'}`;

/** One ordered list of prerequisites with one next action each. Model, compute and budget point at the
 *  training wizard, which provisions them; only a computer that cannot train points at Infrastructure. */
export function setupItems(state: SetupReadinessState | null, activeProject: { name: string } | null, hasToken: boolean): SetupItem[] {
  const r: SetupReadinessState = state ?? { hasConnection: false, datasetCount: 0, tokenizerCount: 0, modelVersionCount: 0, workerPoolCount: 0, budgetPolicyCount: 0, compute: null, firstTokenizerName: undefined, firstModelName: undefined };
  const modelReady = r.modelVersionCount > 0 && r.tokenizerCount > 0;
  const computeReady = r.workerPoolCount > 0 || r.compute?.available === true;
  const computeBlocked = !!r.compute && !r.compute.available && r.workerPoolCount === 0;
  return [
    { id: 'connection', title: 'Connection', ready: r.hasConnection, detail: r.hasConnection ? 'API key verified' : 'Connect a workspace API key', action: { kind: 'connection', label: hasToken ? 'Switch key' : 'Connect workspace' } },
    { id: 'project', title: 'Project', ready: !!activeProject, detail: activeProject ? activeProject.name : 'Create a project to scope your work', action: { kind: 'project', label: 'Create project' } },
    { id: 'dataset', title: 'Dataset', ready: r.datasetCount > 0, detail: r.datasetCount > 0 ? plural(r.datasetCount, 'published dataset version') : 'Add your examples in the training wizard', action: { kind: 'page', page: 'Training', label: 'Add examples' } },
    { id: 'model', title: 'Model', ready: modelReady, detail: modelReady ? `${r.firstModelName ?? 'Model'} with weights and tokenizer` : 'The wizard downloads a pretrained model for you', action: { kind: 'page', page: 'Training', label: 'Choose a model' } },
    { id: 'compute', title: 'Compute', ready: computeReady, detail: computeReady ? (r.compute?.available ? 'This computer is ready to train' : plural(r.workerPoolCount, 'pool') + ' with an available worker') : computeBlocked ? r.compute!.message : 'Set up when training starts', action: computeBlocked ? { kind: 'page', page: 'Infrastructure', label: 'Set up compute' } : { kind: 'page', page: 'Training', label: 'Start training' } },
    { id: 'budget', title: 'Budget', ready: r.budgetPolicyCount > 0, detail: r.budgetPolicyCount > 0 ? plural(r.budgetPolicyCount, 'training-step budget') : 'Reserved automatically when training starts', action: { kind: 'page', page: 'Training', label: 'Start training' } },
  ];
}
