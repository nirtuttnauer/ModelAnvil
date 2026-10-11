import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { build } from 'rolldown';

// Execute the actual page handlers with controlled React hooks and deferred API responses.
const bundle = await build({ input: fileURLToPath(new URL('../src/pages/DatasetBankPage.tsx', import.meta.url)), external: () => true, output: { format: 'cjs' }, write: false });
const compiled = bundle.output.find(item => item.type === 'chunk').code;
const source = { id: 'qualified-source', name: 'Verified source', category: 'text', source_kind: 'repository', description: 'Real source', source_url: 'https://example.org', modalities: ['text'], use_cases: ['training'], license: 'MIT', eligibility: 'eligible', download_enabled: true, acquisition_available: true, pinned_revision: 'abcdef', size_bytes: 42, is_size_measured: true };
const policy = { policy_id: 'policy-1', name: 'Bank records', unit: 'bank_acquisition_records', currency: '', enabled: true };
const acquisition = { snapshot_id: 'snapshot-1', source_id: source.id, state: 'failed', verified_records: 1, planned_records: 2, transferred_bytes: 21, planned_bytes: 42, revision_id: null, revision_no: null, row_count: null, failures: [], job: null };
const published = { ...acquisition, state: 'ready', verified_records: 2, transferred_bytes: 42, revision_id: 'revision-1', revision_no: 1, row_count: 2 };
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }

function fixture({ policies = [], policyId = '', estimate = '', existing = null, budgetLoading = false, budgetError = null, bankSource = source, allowShareAlike = false, downloadScope = 'sample', storageQuota = '' } = {}) {
  let stateIndex = 0, callbacks = 0;
  const effects = [], calls = [], resourceCalls = [], writes = [], first = deferred(), second = deferred();
  // Hook slots represent a loaded catalog and the requested budget configuration.
  const states = { 1: [bankSource], 2: false, 8: existing ? { [source.id + (downloadScope === 'full' ? ':full' : '')]: existing } : {}, 9: policies, 10: budgetLoading, 11: budgetError, 13: policyId, 14: estimate, 15: allowShareAlike ? bankSource.id : '', 16: downloadScope, 17: storageQuota };
  const jsx = (type, props) => ({ type, props });
  const React = {
    useState(initial) { const index = stateIndex++; return [Object.hasOwn(states, index) ? states[index] : initial, value => writes.push({ index, value })]; },
    useRef(value) { return { current: value }; }, useEffect(effect) { effects.push(effect); },
    createElement(type, props, ...children) { return jsx(type, { ...props, children }); },
  };
  const module = { exports: {} };
  vm.runInNewContext(compiled, { module, exports: module.exports, AbortController, console, require(name) {
    if (name === 'react') return React;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name.endsWith('/api/resources')) return { allResources(path, token, signal) { resourceCalls.push({ path, token, signal }); return Promise.resolve(policies); } };
    if (name.endsWith('/api/client')) return { apiRequest(path, token, init) {
      calls.push({ path, token, init });
      if (path.endsWith('/sources/')) return Promise.resolve({ sources: [bankSource] });
      return calls.filter(call => !call.path.endsWith('/sources/')).length === 1 ? first.promise : second.promise;
    }, errorMessage: error => error.message };
    return new Proxy({}, { get: (_, key) => key });
  } });
  const tree = module.exports.DatasetBankPage({ token: 'same-token', onImportSuccess() { callbacks++; } });
  const cleanups = effects.map(effect => effect());
  function find(node, text) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'button' && JSON.stringify(node.props.children).includes(text)) return node;
    for (const child of [node.props?.children].flat(Infinity)) { const found = find(child, text); if (found) return found; }
  }
  return { calls, resourceCalls, writes, first, second, button: text => { const button = find(tree, text); assert.ok(button, text); return button; }, click: text => { const button = find(tree, text); assert.ok(button, text); button.props.onClick(); }, unmount: () => cleanups.forEach(cleanup => cleanup?.()), callbacks: () => callbacks };
}

test('budgeted acquisition sends selected policy and exact positive decimal reservation', async () => {
  const f = fixture({ policies: [policy], policyId: policy.policy_id, estimate: '12.345678' });
  assert.equal(f.resourceCalls[0].path, '/api/v1/budget-policies/');
  assert.ok(f.resourceCalls[0].signal instanceof AbortSignal);
  f.click('Acquire to workspace'); f.first.resolve({ status: 'approved' }); await flush();
  assert.equal(f.calls.at(-1).path, '/api/v1/dataset-bank/sources/qualified-source/acquisitions/');
  assert.deepEqual(JSON.parse(f.calls.at(-1).init.body), { budget_policy_id: policy.policy_id, estimated_amount: '12.345678' });
  assert.equal(f.calls.at(-1).init.signal, f.calls.at(-2).init.signal);
  f.second.resolve(published); await flush(); assert.equal(f.callbacks(), 1);
  assert.deepEqual(f.writes.at(-1), { index: 6, value: null });
});

test('no enabled policy permits an unbudgeted acquisition', async () => {
  const f = fixture(); f.click('Acquire to workspace'); f.first.resolve({ status: 'approved' }); await flush();
  assert.deepEqual(JSON.parse(f.calls.at(-1).init.body), {}); f.unmount();
});

test('required budget selection and invalid estimates block launch before preflight', () => {
  const cases = [{ policyId: '', estimate: '1' }, { policyId: 'stale-policy', estimate: '1' }, ...['', '0', '-1', 'NaN', 'Infinity', '1e3', '0.0000001', '1000000000000000000.0'].map(estimate => ({ policyId: policy.policy_id, estimate }))];
  for (const config of cases) {
    const f = fixture({ policies: [policy], ...config });
    assert.equal(f.button('Acquire to workspace').props.disabled, true);
    f.click('Acquire to workspace'); assert.equal(f.calls.some(call => call.path.includes('/preflight/')), false); f.unmount();
  }
});

test('unverified budget policies disable launch and resume with a retry on failure', () => {
  for (const budgetState of [{ budgetLoading: true }, { budgetError: 'Access denied' }]) {
    const launch = fixture(budgetState); assert.equal(launch.button('Acquire to workspace').props.disabled, true); launch.click('Acquire to workspace'); assert.equal(launch.calls.length, 1);
    const resume = fixture({ ...budgetState, existing: acquisition }); assert.equal(resume.button('Resume transfer').props.disabled, true); resume.click('Resume transfer'); assert.equal(resume.calls.length, 1);
    if (budgetState.budgetError) assert.ok(resume.button('Retry budget policies'));
    launch.unmount(); resume.unmount();
  }
});

test('resume includes the required budget payload; refresh remains available without budget selection', async () => {
  const f = fixture({ policies: [policy], policyId: policy.policy_id, estimate: '2', existing: acquisition });
  f.click('Resume transfer'); assert.equal(f.calls.at(-1).path, '/api/v1/dataset-bank/acquisitions/snapshot-1/resume/');
  assert.deepEqual(JSON.parse(f.calls.at(-1).init.body), { budget_policy_id: policy.policy_id, estimated_amount: '2' }); f.first.resolve(acquisition); await flush();
  const refresh = fixture({ policies: [policy], budgetError: 'Budget unavailable', existing: acquisition }); refresh.click('Refresh transfer'); assert.equal(refresh.calls.at(-1).path, '/api/v1/dataset-bank/acquisitions/snapshot-1/'); refresh.unmount();
});

test('unmount aborts preflight and budget loading, blocks later queueing and duplicate clicks', async () => {
  const f = fixture(); f.click('Acquire to workspace'); f.click('Acquire to workspace'); assert.equal(f.calls.filter(call => call.path.includes('/preflight/')).length, 1);
  const signal = f.calls.at(-1).init.signal; f.unmount(); const writes = f.writes.length;
  assert.equal(signal.aborted, true); assert.equal(f.resourceCalls[0].signal.aborted, true);
  f.first.resolve({ status: 'approved' }); await flush(); assert.equal(f.calls.some(call => call.path.includes('/acquisitions/')), false); assert.equal(f.writes.length, writes); assert.equal(f.callbacks(), 0);
});

test('late acquisition and refresh responses cannot change state or call publication callback after unmount', async () => {
  const f = fixture(); f.click('Acquire to workspace'); f.first.resolve({ status: 'approved' }); await flush(); f.unmount(); const writes = f.writes.length;
  f.second.resolve(published); await flush(); assert.equal(f.writes.length, writes); assert.equal(f.callbacks(), 0);
  const refresh = fixture({ existing: acquisition }); refresh.click('Refresh transfer'); refresh.unmount(); const before = refresh.writes.length;
  refresh.first.resolve(published); await flush(); assert.equal(refresh.writes.length, before); assert.equal(refresh.callbacks(), 0);
});


test('share-alike acquisition remains blocked until explicit opt-in and carries that choice through preflight and launch', async () => {
  const bankSource = { ...source, eligibility: 'opt_in_required', license: 'CC-BY-SA-4.0' };
  const blocked = fixture({ bankSource });
  assert.equal(blocked.button('Acquire to workspace').props.disabled, true);
  blocked.click('Acquire to workspace');
  assert.equal(blocked.calls.some(call => call.path.includes('/preflight/')), false);
  blocked.unmount();
  const allowed = fixture({ bankSource, allowShareAlike: true });
  assert.equal(allowed.button('Acquire to workspace').props.disabled, false);
  allowed.click('Acquire to workspace');
  assert.deepEqual(JSON.parse(allowed.calls.at(-1).init.body), { project_policy: { allow_share_alike: true } });
  allowed.first.resolve({ status: 'approved' }); await flush();
  assert.deepEqual(JSON.parse(allowed.calls.at(-1).init.body), { project_policy: { allow_share_alike: true } });
  allowed.second.resolve(published); await flush();
  assert.equal(allowed.callbacks(), 1);
});


test('complete releases send full scope and twice the exact measured file bytes', async () => {
  const bankSource = { ...source, full_acquisition_available: true, full_acquisition: { pinned_revision: 'full', measured_selected_bytes: 123456789, record_limit: 3 } };
  const f = fixture({ bankSource, downloadScope: 'full' }); f.click('Acquire to workspace');
  const body = { download_scope: 'full', project_policy: { max_storage_quota_bytes: 246913578 } };
  assert.deepEqual(JSON.parse(f.calls.at(-1).init.body), body);
  f.first.resolve({ status: 'approved' }); await flush();
  assert.deepEqual(JSON.parse(f.calls.at(-1).init.body), body);
  f.second.resolve({ ...acquisition, download_scope: 'full' }); await flush();
  const write = f.writes.findLast(write => write.index === 8);
  assert.equal(write.value({})[source.id + ':full'].download_scope, 'full');
  f.unmount();
});

test('full releases refuse unqualified sources and insufficient or fractional storage allowances', () => {
  const bankSource = { ...source, full_acquisition_available: true, full_acquisition: { measured_selected_bytes: 100, record_limit: 1 } };
  for (const storageQuota of ['100', '200.1', '-1', 'NaN']) {
    const f = fixture({ bankSource, downloadScope: 'full', storageQuota });
    assert.equal(f.button('Acquire to workspace').props.disabled, true);
    f.click('Acquire to workspace'); assert.equal(f.calls.length, 1); f.unmount();
  }
  const f = fixture({ downloadScope: 'full' }); assert.equal(f.button('Acquire to workspace').props.disabled, true); f.unmount();
});
