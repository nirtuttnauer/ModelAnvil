import test from 'node:test';
import assert from 'node:assert/strict';
import { setupReadiness } from '../src/api/setup-readiness.ts';

function fixture() {
  return {
    datasets: [{ state: 'published', manifest_digest: 'a'.repeat(64), manifest_artifact: 'verified-artifact', row_count: 20 }],
    tokenizers: [{ id: 1, vocabulary_size: 49152, name: 'Actual tokenizer' }],
    models: [{ id: 1, state: 'draft', tokenizer: 1, artifact_manifest_id: 'weights', architecture_ref: 'native-runtime', model_name: 'Pinned base' }],
    pools: [{ id: 1, status: 'active' }],
    workers: [{ pool: 1, status: 'available', slots: 1, capabilities: { training_runtime: 'exact-contract', memory_bytes: 8192 } }],
    budgets: [{ enabled: true, unit: 'training_steps', currency: '', limit_amount: '30.000000' }],
    runners: [{ enabled: true, compatibility: { contract_digest: 'exact-contract' }, manifest: { resources: { memory_bytes: 8192 }, capabilities: [{ kind: 'train', architectures: ['native-runtime'] }] } }],
  };
}

test('published data, recorded compatible weights, available matching worker and enabled step budget are counted', () => {
  const result = setupReadiness(fixture());
  for (const key of ['datasetCount', 'tokenizerCount', 'modelVersionCount', 'workerPoolCount', 'budgetPolicyCount']) assert.equal(result[key], 1);
});

test('drafts, metadata-only models, mismatched tokenizers, inactive or incompatible workers and disabled budgets remain incomplete', () => {
  const cases = [
    ['datasets', 'datasetCount', { state: 'draft' }], ['datasets', 'datasetCount', { manifest_artifact: null }],
    ['models', 'modelVersionCount', { artifact_manifest_id: '' }], ['models', 'modelVersionCount', { tokenizer: 2 }],
    ['pools', 'workerPoolCount', { status: 'inactive' }], ['workers', 'workerPoolCount', { slots: 0 }],
    ['workers', 'workerPoolCount', { status: 'offline' }], ['workers', 'workerPoolCount', { capabilities: { training_runtime: 'other-contract', memory_bytes: 8192 } }],
    ['workers', 'workerPoolCount', { capabilities: { training_runtime: 'exact-contract', memory_bytes: 4096 } }],
    ['runners', 'workerPoolCount', { enabled: false }], ['runners', 'workerPoolCount', { manifest: {} }],
    ['budgets', 'budgetPolicyCount', { enabled: false }], ['budgets', 'budgetPolicyCount', { unit: 'usd' }],
    ['budgets', 'budgetPolicyCount', { currency: 'USD' }], ['budgets', 'budgetPolicyCount', { limit_amount: '0' }],
  ];
  for (const [collection, key, override] of cases) {
    const data = fixture(); data[collection][0] = { ...data[collection][0], ...override };
    assert.equal(setupReadiness(data)[key], 0, JSON.stringify(override));
  }
  const empty = Object.fromEntries(Object.keys(fixture()).map(key => [key, []]));
  assert.equal(setupReadiness(empty).workerPoolCount, 0);
});
