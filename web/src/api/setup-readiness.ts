import type { RegisteredModelVersion, TokenizerVersion } from './resources';

export interface SetupPool { id: number; name: string; status: string }
export interface SetupBudget { policy_id: string; name: string; enabled: boolean; unit: string; currency: string; limit_amount: string }
export interface SetupDataset { state: string; manifest_digest: string; manifest_artifact: string | null; row_count: number }
export interface SetupWorker { pool: number; status: string; slots: number; capabilities: { training_runtime?: string; memory_bytes?: number } }
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
    worker.pool === pool.id && worker.status === 'available' && worker.slots > 0 && data.runners.some(runner => {
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
