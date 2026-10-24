import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'rolldown';
import { fileURLToPath } from 'node:url';

const bundled = await build({ input: fileURLToPath(new URL('../src/api/alignment.ts', import.meta.url)), output: { format: 'esm' }, write: false });
const code = bundled.output.find(item => item.type === 'chunk').code;
const client = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const artifact = '80000000-0000-4000-8000-000000000001';
const held = '80000000-0000-4000-8000-000000000002';
const run = '30000000-0000-4000-8000-000000000010';
const pair = { prompt: 'Say a', chosen: 'a', rejected: 'b' };

test('preference parser preserves exact text and refuses malformed, duplicate, or unbounded pairs', () => {
  assert.deepEqual(client.preferencePairs(JSON.stringify([pair])), [pair]);
  const spaced = { ...pair, chosen: ' a ' };
  assert.deepEqual(client.preferencePairs(JSON.stringify([spaced])), [spaced]);
  for (const raw of ['invalid', '{}', '[]', JSON.stringify([pair, pair]), JSON.stringify([{ ...pair, prompt: ' ' }]), JSON.stringify([{ ...pair, chosen: 'b' }]), JSON.stringify([{ ...pair, chosen: 'a'.repeat(33) }]), JSON.stringify([{ ...pair, prompt: 'a'.repeat(62) }]), JSON.stringify(Array.from({ length: 33 }, (_, i) => ({ ...pair, prompt: String(i) })))]) assert.throws(() => client.preferencePairs(raw));
});

test('actual client pins preference UUIDs, submits exact registration and propagates abort signals', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return new Response(JSON.stringify({ run_id: run, status: 'completed' }), { status: 200 }); };
  try {
    const controller = new AbortController();
    await client.registerPreferences('test-key', 'Human pairs', [pair], controller.signal);
    const plan = { algorithm: 'dpo', policy_model_version: 1, reference_model_version: 2, reward_model_version: null, train_dataset_artifact: artifact, held_out_dataset_artifact: held, total_steps: 4, hyperparameters: { learning_rate: 0.05 }, verifier_spec: {} };
    await client.createAlignmentPlan('test-key', plan, controller.signal);
    await client.alignmentAction('test-key', run, 'execute', controller.signal);
    await client.alignmentAction('test-key', run, 'cancel', controller.signal);
    assert.deepEqual(calls.map(c => c.path), ['/api/v1/alignment-runs/register-preferences/', '/api/v1/alignment-runs/', `/api/v1/alignment-runs/${run}/execute/`, `/api/v1/alignment-runs/${run}/cancel/`]);
    assert.deepEqual(JSON.parse(calls[0].init.body), { name: 'Human pairs', samples: [pair] });
    assert.deepEqual(JSON.parse(calls[1].init.body), plan);
    assert.equal(JSON.parse(calls[1].init.body).dataset_manifest_digest, undefined);
    for (const call of calls) { assert.equal(call.init.signal, controller.signal); assert.equal(call.init.method, 'POST'); assert.equal(call.init.headers.get('Authorization'), 'Bearer test-key'); }
    for (const total_steps of [0, 101, 1.5, NaN]) assert.throws(() => client.createAlignmentPlan('test-key', { ...plan, total_steps }));
    assert.throws(() => client.createAlignmentPlan('test-key', { ...plan, held_out_dataset_artifact: artifact }));
    assert.throws(() => client.alignmentAction('test-key', '../another-resource', 'cancel'));
    assert.equal(calls.length, 4);
  } finally { globalThis.fetch = original; }
});

test('backend refusal is surfaced without treating it as completion', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Only pending plans can execute.' }), { status: 400 });
  try { await assert.rejects(client.alignmentAction('test-key', run, 'execute'), error => error.status === 400 && /pending/.test(error.message)); }
  finally { globalThis.fetch = original; }
});

test('GRPO preference parsing preserves protected source groups and rejects malformed IDs', () => {
  const grouped = { ...pair, source_group_id: 'public-source:one' };
  assert.deepEqual(client.preferencePairs(JSON.stringify([grouped])), [grouped]);
  for (const source_group_id of ['', ' ', 3, 'x'.repeat(129)]) {
    assert.throws(() => client.preferencePairs(JSON.stringify([{ ...pair, source_group_id }])));
  }
});

test('explicit checkpoint takeover uses the bounded resume action and rejects arbitrary actions', async () => {
  const original = globalThis.fetch; const calls = [];
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return new Response(JSON.stringify({ run_id: run, status: 'completed' }), { status: 200 }); };
  try {
    await client.alignmentAction('test-key', run, 'resume');
    assert.equal(calls[0].path, `/api/v1/alignment-runs/${run}/resume/`);
    assert.equal(calls[0].init.body, '{}');
    assert.throws(() => client.alignmentAction('test-key', run, '../cancel'));
    assert.equal(calls.length, 1);
  } finally { globalThis.fetch = original; }
});

test('Apple GPU DPO requires a separate regression set and at most twenty steps', async () => {
  const original = globalThis.fetch; const calls = [];
  globalThis.fetch = async (path, init) => { calls.push({ path, body: JSON.parse(init.body) }); return new Response('{}'); };
  try {
    const plan = { algorithm: 'dpo', worker_pool: 7, policy_model_version: 1, reference_model_version: 1,
      reward_model_version: null, train_dataset_artifact: artifact, held_out_dataset_artifact: held,
      regression_dataset_artifact: '80000000-0000-4000-8000-000000000003', total_steps: 3, hyperparameters: {}, verifier_spec: {} };
    for (const changes of [{ total_steps: 21 }, { algorithm: 'orpo' }, { regression_dataset_artifact: null },
        { regression_dataset_artifact: held }]) assert.throws(() => client.createAlignmentPlan('test-key', { ...plan, ...changes }));
    await client.createAlignmentPlan('test-key', plan);
    await client.registerPreferences('test-key', 'Reviewed labels', [pair], undefined, true);
    assert.deepEqual(calls[0].body, plan);
    assert.equal(calls[1].body.labels_reviewed, true);
    assert.equal(calls.length, 2);
  } finally { globalThis.fetch = original; }
});

test('pretrained CPU RLOO pins learned reward and separate resource budgets', async () => {
  const original = globalThis.fetch; const calls = [];
  globalThis.fetch = async (path, init) => { calls.push(JSON.parse(init.body)); return new Response('{}'); };
  try {
    const plan = { algorithm: 'rloo', worker_pool: 9, policy_model_version: 1, reference_model_version: 1,
      reward_model_version: 4, train_dataset_artifact: artifact, held_out_dataset_artifact: held,
      regression_dataset_artifact: '80000000-0000-4000-8000-000000000003', total_steps: 2,
      hyperparameters: { budget_policy_id: 'steps', scoring_budget_policy_id: 'scores', rollout_budget_policy_id: 'tokens' }, verifier_spec: {} };
    await client.createAlignmentPlan('test-key', plan);
    assert.deepEqual(calls, [plan]);
    for (const changes of [{ total_steps: 21 }, { regression_dataset_artifact: artifact }])
      assert.throws(() => client.createAlignmentPlan('test-key', { ...plan, ...changes }));
  } finally { globalThis.fetch = original; }
});
