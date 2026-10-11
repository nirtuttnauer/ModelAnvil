import test, { before, beforeEach, afterEach, after } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';
import { build } from 'rolldown';
import * as msw from 'msw';
import { setupServer } from 'msw/node';
import * as data from '../src/stories/data-fixtures.ts';
import * as ml from '../src/stories/ml-fixtures.ts';
import * as operations from '../src/stories/operations-fixtures.ts';
import * as workspace from '../src/stories/workspace-fixtures.ts';

// Bundle only the actual TS handler module; its external imports use the real MSW and shared fixture modules.
const bundle = await build({ input: fileURLToPath(new URL('../src/stories/demo-network.ts', import.meta.url)), external: () => true, output: { format: 'cjs' }, write: false });
const imports = { msw, './data-fixtures': data, './ml-fixtures': ml, './operations-fixtures': operations, './workspace-fixtures': workspace };
const module = { exports: {} };
const loggedErrors = [];
vm.runInNewContext(bundle.output.find(chunk => chunk.type === 'chunk').code, {
  module, exports: module.exports, URL,
  console: { ...console, error: message => loggedErrors.push(message) },
  require(name) { assert.ok(imports[name], `Unexpected demo handler import: ${name}`); return imports[name]; },
});
const { demoHandlers, demoRequests, resetDemoRequests } = module.exports;
let origin;
const originalLocation = Object.getOwnPropertyDescriptor(globalThis, 'location');
let forwarded = 0;
const canary = createServer((_request, response) => {
  forwarded++;
  response.writeHead(598, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify({ detail: 'Request escaped the demo network.' }));
});
const server = setupServer();
const jobId = '40000000-0000-4000-8000-000000000007';

before(async () => {
  // A loopback canary records any bypass; no request can reach the user's real API.
  await new Promise((resolve, reject) => { canary.once('error', reject); canary.listen(0, '127.0.0.1', resolve); });
  origin = `http://127.0.0.1:${canary.address().port}`;
  Object.defineProperty(globalThis, 'location', { configurable: true, value: new URL(origin) });
  server.listen({ onUnhandledFrame: 'error' });
});
beforeEach(() => {
  workspace.resetWorkspaceFixtures(); data.resetDataFixtures(); ml.resetMlFixtures(); operations.resetOperationsFixtures();
  resetDemoRequests(); loggedErrors.length = 0; forwarded = 0;
  server.resetHandlers(...demoHandlers());
});
afterEach(() => { assert.equal(forwarded, 0, 'Every exercised API request must be answered by the demo handler.'); });
after(async () => {
  server.close();
  canary.closeAllConnections();
  await new Promise((resolve, reject) => canary.close(error => error ? reject(error) : resolve()));
  if (originalLocation) Object.defineProperty(globalThis, 'location', originalLocation);
  else delete globalThis.location;
});
async function request(path, init) {
  const response = await fetch(new URL(path, origin), { ...init, signal: AbortSignal.timeout(3000) });
  return { status: response.status, body: await response.json() };
}
const post = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

test('the actual demo handler returns paginated synthetic data across the entire workspace', async () => {
  for (const path of ['/api/v1/models/', '/api/v1/datasets/', '/api/v1/jobs/', '/api/v1/worker-inventory/', '/api/v1/release-versions/', '/api/v1/audit/']) {
    const { status, body } = await request(`${path}?cursor=demo-only`);
    assert.equal(status, 200, path);
    assert.ok(Array.isArray(body.results) && body.results.length > 0, path);
    assert.equal(body.count, body.results.length);
    assert.equal(body.next, null); assert.equal(body.previous, null);
  }
  const detail = await request(`/api/v1/run-details/job/${jobId}/`);
  assert.equal(detail.body.evidence.production_qualified, false);
  assert.match(detail.body.evidence.source, /Synthetic Storybook fixture/);
  assert.equal(detail.body.observed.state, 'running');
  const costs = await request('/api/v1/usage-events/summary/');
  assert.deepEqual([...new Set(costs.body.usage_by_unit.map(row => row.currency))], ['USD', 'EUR']);
  assert.equal(demoRequests.length, 8);
  assert.ok(demoRequests.every(row => row.status === 200));
});

test('unknown API reads and writes fail closed with 501 and never pass through to a live server', async () => {
  for (const init of [undefined, post({ fixture: 'unknown write' })]) {
    const response = await request('/api/v1/not-a-demo-route/', init);
    assert.equal(response.status, 501);
    assert.equal(response.body.detail, 'No demo fixture for /api/v1/not-a-demo-route/');
  }
  assert.deepEqual(Array.from(demoRequests, row => row.status), [501, 501]);
  assert.equal(loggedErrors.length, 2);
});

test('demo create/cancel writes update only fixture records and reset restores all nested state', async () => {
  const initial = (await request('/api/v1/jobs/')).body;
  const created = await request('/api/v1/jobs/', post({ name: 'Session-only job', pool: 1, priority: 0, requirements: { slots: 1 }, payload: { fixture: 'Storybook only' } }));
  assert.equal(created.status, 200); assert.equal(created.body.priority, 0);
  assert.equal((await request('/api/v1/jobs/')).body.results.length, initial.results.length + 1);
  const queuedCancel = await request(`/api/v1/jobs/${created.body.job_id}/cancel/`, post({}));
  assert.equal(queuedCancel.body.status, 'cancelled');
  const runningCancel = await request(`/api/v1/jobs/${jobId}/cancel/`, post({}));
  assert.equal(runningCancel.body.status, 'running'); assert.equal(runningCancel.body.desired_action, 'cancel');
  const updatedDetail = (await request(`/api/v1/run-details/job/${jobId}/`)).body;
  assert.equal(updatedDetail.observed.state, 'running');
  assert.equal(updatedDetail.actions.cancel.requested, true);
  assert.equal(updatedDetail.actions.cancel.acknowledged, false);
  assert.equal(updatedDetail.actions.cancel.available, false);
  operations.operationsResponses['/api/v1/worker-inventory/'][0].capabilities.memory_gb = 999;
  operations.resetOperationsFixtures();
  assert.deepEqual((await request('/api/v1/jobs/')).body, initial);
  assert.equal((await request(`/api/v1/run-details/job/${jobId}/`)).body.desired.action, 'run');
  assert.equal((await request('/api/v1/worker-inventory/')).body.results[0].capabilities.memory_gb, 32);
  assert.equal((await request(`/api/v1/jobs/${created.body.job_id}/cancel/`, post({}))).status, 501);
});

test('every durable job link has a faithful detail and attempts projection', async () => {
  const jobs = (await request('/api/v1/jobs/')).body.results;
  for (const job of jobs) {
    const detail = await request(`/api/v1/run-details/job/${job.job_id}/`);
    assert.equal(detail.status, 200);
    assert.equal(detail.body.observed.state, job.status);
    assert.equal(detail.body.desired.action, job.desired_action);
    assert.equal(detail.body.observed.progress, null);
    assert.equal(detail.body.checkpoints, null);
    assert.deepEqual(detail.body.metrics.rows, []);
    assert.equal(detail.body.actions.resume.available, false);
    const attempts = await request(`/api/v1/run-details/job/${job.job_id}/attempts/`);
    assert.equal(attempts.status, 200);
    assert.equal(attempts.body.results.length, job.attempt_count);
    assert.ok(attempts.body.results.every(row => row.job_id === job.job_id));
  }
  const primary = jobs.find(row => row.job_id.endsWith('000001'));
  assert.equal(primary.status, 'succeeded');
  assert.equal(primary.updated_at, '2026-10-11T09:24:00Z');
});

test('empty stories clear resource collections while preserving workspace connection scope', async () => {
  server.resetHandlers(...demoHandlers('empty'));
  for (const path of ['/api/v1/jobs/', '/api/v1/models/', '/api/v1/datasets/', '/api/v1/audit/']) {
    const response = await request(path);
    assert.equal(response.status, 200);
    assert.deepEqual(response.body, { results: [], count: 0, next: null, previous: null });
  }
  assert.deepEqual((await request('/api/v1/dataset-bank/sources/')).body, { sources: [] });
  assert.equal((await request('/api/v1/health/')).body.status, 'ok');
  for (const path of ['/api/v1/tenants/', '/api/v1/projects/', '/api/v1/teams/']) assert.ok((await request(path)).body.results.length > 0);
});

test('error stories return explicit 503 for API reads and writes without mutating fixtures', async () => {
  const initial = structuredClone(operations.operationsResponses);
  server.resetHandlers(...demoHandlers('error'));
  for (const init of [undefined, post({ name: 'Must not be created', pool: 1 })]) {
    const response = await request('/api/v1/jobs/', init);
    assert.equal(response.status, 503);
    assert.equal(response.body.detail, 'Demo request failed. Try again.');
  }
  assert.deepEqual(operations.operationsResponses, initial);
  for (const path of ['/api/v1/health/', '/api/v1/projects/']) assert.equal((await request(path)).status, 200);
});
