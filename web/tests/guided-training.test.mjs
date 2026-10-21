import test from 'node:test';
import assert from 'node:assert/strict';
import { authHeaders, apiRequest, setActiveProjectId } from '../src/api/client.ts';
import { streamCompletion } from '../src/api/inference.ts';
import { guidedLaunch, guidedPlan, readGuidedValue } from '../src/api/guided-training.ts';

test('browser sessions use CSRF and keep credentials out of Authorization', async () => {
  const priorDocument = globalThis.document; const priorFetch = globalThis.fetch;
  globalThis.document = { cookie: 'csrftoken=test-csrf; other=value' };
  try {
    assert.equal(authHeaders('session').get('Authorization'), null);
    setActiveProjectId('project');
    globalThis.fetch = async (path, init) => {
      assert.equal(init.headers.get('X-CSRFToken'), 'test-csrf');
      assert.equal(init.headers.get('X-Project-ID'), 'project');
      assert.equal(init.headers.get('Authorization'), null);
      return new Response('{}', { status: 200 });
    };
    await apiRequest('/api/v1/fine-tuning/setup/', 'session', { method: 'POST', body: '{}' });
    assert.equal(authHeaders('mkv_existing').get('Authorization'), 'Bearer mkv_existing');
  } finally { globalThis.document = priorDocument; globalThis.fetch = priorFetch; setActiveProjectId(null); }
});

test('guided launch pins the published revision and refuses invalid step counts', () => {
  const inputs = { execution_mode: 'worker', recipe_type: 'full_sft', base_model_version: 3, tokenizer_version: 4 };
  const revision = { id: 7 };
  assert.deepEqual(guidedLaunch(inputs, revision, 3), { ...inputs, dataset_revision: 7, total_steps: 3 });
  for (const count of [0, 3001, 1.2, NaN]) assert.throws(() => guidedLaunch(inputs, revision, count));
  assert.throws(() => guidedLaunch(inputs, { id: -1 }, 3));
  assert.equal(readGuidedValue('{broken'), null);
});

test('recommended training covers all train examples three times and excludes held-out data', () => {
  const revision = { id: 7, row_count: 1000, metadata: { split_counts: { train: 800, validation: 100, test: 100 } } };
  const plan = guidedPlan(revision);
  assert.equal(plan.steps, 2400);
  assert.equal(plan.trainingExamples, 800);
  assert.equal(guidedLaunch({}, revision, plan.steps).total_steps, 2400);
  assert.equal(guidedPlan({ metadata: { split_counts: { train: 10, validation: 1, test: 1 } } }).steps, 30);
  assert.ok(guidedPlan(revision, true).minutesHigh > plan.minutesHigh);
  assert.equal(guidedPlan({ metadata: { split_counts: { train: 48, validation: 6, test: 6 } } }, true).steps, 288);
  assert.equal(guidedPlan({ metadata: { split_counts: { train: 100 } } }, true).epochs, 3);
});


test('chat streaming authenticates cookie sessions with CSRF', async () => {
  const priorDocument = globalThis.document;
  globalThis.document = { cookie: 'csrftoken=stream-csrf' };
  try {
    const event = 'data: ' + JSON.stringify({ id: 'chatcmpl-' + 'a'.repeat(32), choices: [{ delta: { content: 'hello' }, finish_reason: 'stop' }], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } }) + '\n\ndata: [DONE]\n\n';
    let output = '';
    await streamCompletion('session', { model: 'model', messages: [{ role: 'user', content: 'Hi' }] }, new AbortController().signal,
      text => { output += text; }, () => {}, async (path, init) => {
        assert.equal(init.headers.get('Authorization'), null);
        assert.equal(init.headers.get('X-CSRFToken'), 'stream-csrf');
        return new Response(event, { headers: { 'Content-Type': 'text/event-stream' } });
      });
    assert.equal(output, 'hello');
  } finally { globalThis.document = priorDocument; }
});
