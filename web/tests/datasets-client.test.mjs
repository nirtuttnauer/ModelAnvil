import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const moduleUrl = new URL('../src/api/datasets.ts', import.meta.url);
const token = '[REDACTED]';
const artifactId = '11111111-1111-4111-8111-111111111111';
const datasetId = '22222222-2222-4222-8222-222222222222';
const revisionId = '33333333-3333-4333-8333-333333333333';
const content = '{"schema_version":"1","sample":{"text":"Example"}}\n';
const file = () => new File([content], 'samples.jsonl', { type: 'application/x-ndjson' });
const sha256 = createHash('sha256').update(content).digest('hex');
const artifact = { artifact_id: artifactId, state: 'committed', sha256, byte_size: file().size };
const dataset = {
  dataset_id: datasetId, name: 'Sample dataset', description: '', current_revision: null,
  metadata: {}, created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z',
};
const revision = {
  revision_id: revisionId, dataset: 17, revision_no: 1, schema_version: '1',
  manifest_digest: sha256, manifest_artifact: 24, recipe_digest: sha256,
  source_snapshots: [], row_count: 1, state: 'published',
  published_at: '2026-10-10T00:00:00Z', metadata: {},
};
async function client() {
  assert.ok(existsSync(moduleUrl), 'dataset client feature must exist before importing it');
  const exports = await import(moduleUrl.href);
  assert.equal(typeof exports.prepareUploadedDataset, 'function', 'prepareUploadedDataset must be exported');
  return exports;
}
const response = (body, status) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
function successFetch(inspect = () => {}) {
  const calls = [];
  const bodies = [{ ...artifact, state: 'staging' }, artifact, dataset, revision];
  const statuses = [201, 200, 201, 201];
  return {
    calls,
    fetchImpl: async (url, init) => {
      const index = calls.length;
      calls.push({ url, init });
      await inspect(index, url, init);
      assert.ok(index < 4, 'must not make extra requests');
      return response(bodies[index], statuses[index]);
    },
  };
}

const invalidInputs = [
  ['empty name', { name: '' }], ['blank name', { name: '  ' }],
  ['overlong name', { name: 'x'.repeat(201) }],
  ['empty token', { token: '' }], ['blank token', { token: '  ' }],
  ['token with header control characters', { token: 'invalid\r\nheader' }],
  ['missing file', { file: undefined }], ['empty file', { file: new File([], 'empty.jsonl') }],
  ['oversize file', { file: new File([new Uint8Array(16 * 1024 * 1024 + 1)], 'large.jsonl') }],
  ['non-UTF-8 file', { file: new File([new Uint8Array([0xff])], 'invalid.jsonl') }],
  ['fractional validation percentage', { validationPercent: 1.5 }],
  ['fractional test percentage', { testPercent: 1.5 }],
  ['negative validation percentage', { validationPercent: -1 }],
  ['negative test percentage', { testPercent: -1 }],
  ['NaN percentage', { testPercent: NaN }], ['infinite percentage', { validationPercent: Infinity }],
  ['sum of 100', { validationPercent: 50, testPercent: 50 }],
  ['sum over 100', { validationPercent: 99, testPercent: 10 }],
  ['non-string split seed', { splitSeed: 1 }],
  ['overlong split seed', { splitSeed: 'x'.repeat(1025) }],
];
for (const [label, overrides] of invalidInputs) {
  test(`refuses ${label} before any request`, async () => {
    const { prepareUploadedDataset } = await client();
    let calls = 0;
    await assert.rejects(prepareUploadedDataset({
      file: file(), name: dataset.name, token, ...overrides,
      fetchImpl: async () => { calls++; throw new Error('unexpected network request'); },
    }), /required|16 MiB|UTF-8|integer|percent|split seed|header|characters/i);
    assert.equal(calls, 0);
  });
}

test('explicit split settings preserve zero percentages and the exact string seed', async () => {
  const { prepareUploadedDataset } = await client();
  const harness = successFetch((index, _url, init) => {
    if (index === 3) assert.deepEqual(JSON.parse(init.body), {
      input_artifact_id: artifactId, split_seed: ' 007 ', validation_percent: 0, test_percent: 0,
    });
  });
  await prepareUploadedDataset({ file: file(), name: dataset.name, token,
    splitSeed: ' 007 ', validationPercent: 0, testPercent: 0, fetchImpl: harness.fetchImpl });
});

function fetchWithOverride(stage, replacement) {
  const calls = [];
  const bodies = [{ ...artifact, state: 'staging' }, artifact, dataset, revision];
  const statuses = [201, 200, 201, 201];
  return {
    calls,
    fetchImpl: async (url, init) => {
      const index = calls.length;
      calls.push({ url, init });
      return index === stage ? replacement() : response(bodies[index], statuses[index]);
    },
  };
}
for (const stage of [0, 1, 2, 3]) {
  test(`HTTP failure at step ${stage + 1} stops immediately with a sanitized status`, async () => {
    const { prepareUploadedDataset } = await client();
    const harness = fetchWithOverride(stage, () => response({ detail: 'sensitive-server-body' }, 403));
    await assert.rejects(prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl }), error => {
      assert.equal(error.name, 'DatasetClientError');
      assert.match(error.message, /HTTP 403/);
      assert.equal(error.status, 403);
      assert.doesNotMatch(error.message, /sensitive-server-body/);
      return true;
    });
    assert.equal(harness.calls.length, stage + 1, 'must not retry, continue, or delete');
  });
  test(`network failure at step ${stage + 1} does not expose exception details`, async () => {
    const { prepareUploadedDataset } = await client();
    const harness = fetchWithOverride(stage, () => { throw new Error('sensitive-network-details'); });
    await assert.rejects(prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl }), error => {
      assert.equal(error.name, 'DatasetClientError');
      assert.match(error.message, /network|redirect/i);
      assert.doesNotMatch(error.message, /sensitive-network-details/);
      return true;
    });
    assert.equal(harness.calls.length, stage + 1);
  });
  test(`unexpected success status at step ${stage + 1} is refused`, async () => {
    const { prepareUploadedDataset } = await client();
    const bodies = [{ ...artifact, state: 'staging' }, artifact, dataset, revision];
    const harness = fetchWithOverride(stage, () => response(bodies[stage], 202));
    await assert.rejects(prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl }), /HTTP 202/);
    assert.equal(harness.calls.length, stage + 1);
  });
}

const invalidResponses = [
  ['registration URL injection', 0, { ...artifact, state: 'staging', artifact_id: '../outside?secret=1' }],
  ['registration state', 0, artifact],
  ['registration digest', 0, { ...artifact, state: 'staging', sha256: '0'.repeat(64) }],
  ['registration size', 0, { ...artifact, state: 'staging', byte_size: artifact.byte_size + 1 }],
  ['upload identifier', 1, { ...artifact, artifact_id: datasetId }],
  ['uncommitted upload', 1, { ...artifact, state: 'staging' }],
  ['upload digest', 1, { ...artifact, sha256: '0'.repeat(64) }],
  ['upload size', 1, { ...artifact, byte_size: artifact.byte_size + 1 }],
  ['dataset URL injection', 2, { ...dataset, dataset_id: 'https://example.invalid/' }],
  ['dataset current revision business UUID', 2, { ...dataset, current_revision: revisionId }],
  ['revision UUID', 3, { ...revision, revision_id: 'invalid' }],
  ['revision dataset business UUID', 3, { ...revision, dataset: datasetId }],
  ['revision manifest business UUID', 3, { ...revision, manifest_artifact: artifactId }],
  ['negative row count', 3, { ...revision, row_count: -1 }],
  ['unpublished revision', 3, { ...revision, state: 'draft' }],
  ['missing publication time', 3, { ...revision, published_at: null }],
  ['missing metadata', 3, { ...revision, metadata: null }],
  ['missing revision', 3, {}],
];
for (const [label, stage, body] of invalidResponses) {
  test(`refuses bad response: ${label}`, async () => {
    const { prepareUploadedDataset } = await client();
    const harness = fetchWithOverride(stage, () => response(body, stage === 1 ? 200 : 201));
    await assert.rejects(prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl }), /invalid|mismatch|published/i);
    assert.equal(harness.calls.length, stage + 1);
  });
}

test('invalid JSON response is sanitized', async () => {
  const { prepareUploadedDataset } = await client();
  const harness = fetchWithOverride(0, () => new Response('sensitive-not-json', { status: 201 }));
  await assert.rejects(prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl }), error => {
    assert.match(error.message, /invalid.*JSON/i);
    assert.doesNotMatch(error.message, /sensitive-not-json/);
    return true;
  });
  assert.equal(harness.calls.length, 1);
});
for (const status of [404, 405, 501]) {
  test(`prepare HTTP ${status} reports the unavailable backend capability`, async () => {
    const { prepareUploadedDataset } = await client();
    const harness = fetchWithOverride(3, () => response({}, status));
    await assert.rejects(prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl }), new RegExp(`HTTP ${status}.*unavailable`, 'i'));
    assert.equal(harness.calls.length, 4);
  });
}

test('prepare validation failure reports no publication and does not continue', async () => {
  const { prepareUploadedDataset } = await client();
  const harness = fetchWithOverride(3, () => response({ detail: 'sensitive-validation-body' }, 400));
  await assert.rejects(prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl }), /HTTP 400.*validation.*no revision/i);
  assert.equal(harness.calls.length, 4);
});

async function listingClient() {
  const exports = await client();
  assert.equal(typeof exports.loadDatasetFirstPages, 'function', 'safe first-page listing feature must exist');
  return exports;
}

test('listing fetches only fixed first-page paths and never follows supplied next URLs', async () => {
  const { loadDatasetFirstPages } = await listingClient();
  const calls = [];
  const page = results => ({ count: 200, next: 'https://untrusted.invalid/?cursor=1', previous: null, results });
  const result = await loadDatasetFirstPages({ token, fetchImpl: async (url, init) => {
    calls.push(url);
    assert.equal(init.method, 'GET');
    assert.equal(init.redirect, 'error');
    assert.equal(new Headers(init.headers).get('Authorization'), `Bearer ${token}`);
    return response(page(url === '/api/v1/datasets/' ? [dataset] : [revision]), 200);
  } });
  assert.deepEqual(calls, ['/api/v1/datasets/', '/api/v1/dataset-revisions/']);
  assert.deepEqual(result.datasets.results, [dataset]);
  assert.deepEqual(result.revisions.results, [revision]);
  assert.equal(result.datasets.count, 200, 'reported server count is not the fetched row count');
  assert.equal(result.datasets.results.length, 1);
});

test('listing stops after its first failed request', async () => {
  const { loadDatasetFirstPages } = await listingClient();
  let calls = 0;
  await assert.rejects(loadDatasetFirstPages({ token, fetchImpl: async () => {
    calls++; return response({ detail: 'sensitive-list-body' }, 401);
  } }), /Dataset listing: HTTP 401/);
  assert.equal(calls, 1);
});

test('listing refuses an empty token without network access', async () => {
  const { loadDatasetFirstPages } = await listingClient();
  let calls = 0;
  await assert.rejects(loadDatasetFirstPages({ token: '', fetchImpl: async () => { calls++; return response({}, 200); } }), /token is required/i);
  assert.equal(calls, 0);
});

const invalidPages = [
  ['unpaginated response', []],
  ['negative count', { count: -1, next: null, previous: null, results: [] }],
  ['fractional count', { count: 0.5, next: null, previous: null, results: [] }],
  ['missing results', { count: 1, next: null, previous: null }],
  ['invalid row', { count: 1, next: null, previous: null, results: [{}] }],
  ['count less than rows', { count: 0, next: null, previous: null, results: [dataset] }],
  ['non-string next', { count: 0, next: 1, previous: null, results: [] }],
];
for (const [label, page] of invalidPages) {
  test(`listing refuses ${label}`, async () => {
    const { loadDatasetFirstPages } = await listingClient();
    let calls = 0;
    await assert.rejects(loadDatasetFirstPages({ token, fetchImpl: async () => { calls++; return response(page, 200); } }), /invalid.*page/i);
    assert.equal(calls, 1);
  });
}

test('empty dataset and revision pages are real empty results', async () => {
  const { loadDatasetFirstPages } = await listingClient();
  const page = { count: 0, next: null, previous: null, results: [] };
  const result = await loadDatasetFirstPages({ token, fetchImpl: async () => response(page, 200) });
  assert.deepEqual(result, { datasets: page, revisions: page });
});

test('real cursor pages do not require or invent a total count', async () => {
  const { loadDatasetFirstPages } = await listingClient();
  const result = await loadDatasetFirstPages({ token, fetchImpl: async url => response({
    next: null, previous: null, results: url === '/api/v1/datasets/' ? [dataset] : [revision],
  }, 200) });
  assert.deepEqual(result.datasets.results, [dataset]);
  assert.deepEqual(result.revisions.results, [revision]);
  assert.equal(Object.hasOwn(result.datasets, 'count'), false);
});

test('a draft revision is inspectable in the separate listing, never treated as published', async () => {
  const { loadDatasetFirstPages } = await listingClient();
  const draft = { ...revision, state: 'draft', published_at: null };
  const result = await loadDatasetFirstPages({ token, fetchImpl: async url => response({
    count: 1, next: null, previous: null,
    results: url === '/api/v1/datasets/' ? [{ ...dataset, current_revision: 42 }] : [draft],
  }, 200) });
  assert.equal(result.datasets.results[0].current_revision, 42);
  assert.equal(result.revisions.results[0].state, 'draft');
});

test('listing accepts the real nullable fields of an unprepared draft revision', async () => {
  const { loadDatasetFirstPages } = await listingClient();
  const draft = { ...revision, state: 'draft', published_at: null,
    row_count: null, manifest_artifact: null, recipe_digest: '' };
  const result = await loadDatasetFirstPages({ token, fetchImpl: async url => response({
    count: 1, next: null, previous: null,
    results: url === '/api/v1/datasets/' ? [dataset] : [draft],
  }, 200) });
  assert.deepEqual(result.revisions.results, [draft]);
});

test('dataset page integration surface exists and typechecks with existing React dependencies', () => {
  const pageUrl = new URL('../src/pages/DatasetsPage.tsx', import.meta.url);
  const cssUrl = new URL('../src/pages/datasets.css', import.meta.url);
  assert.ok(existsSync(pageUrl), 'DatasetsPage must exist before checking the integration surface');
  assert.ok(existsSync(cssUrl), 'scoped dataset styles must exist');
  const source = readFileSync(pageUrl, 'utf8');
  assert.match(source, /export function DatasetsPage/);
  assert.match(source, /token: string/);
  assert.match(source, /refreshKey\?: number/);
  assert.doesNotMatch(source, /dangerouslySetInnerHTML|localStorage|sessionStorage/);
  assert.match(source, /<table/);
  assert.match(source, /<label/);
  assert.match(source, /Supported upload format/);
  const result = spawnSync(process.execPath, [
    'node_modules/typescript/bin/tsc', '--ignoreConfig', '--noEmit', '--target', 'ES2022',
    '--module', 'ESNext', '--moduleResolution', 'Bundler', '--jsx', 'react-jsx', '--strict',
    '--noUnusedLocals', '--noUnusedParameters', '--allowImportingTsExtensions', '--skipLibCheck',
    'src/pages/DatasetsPage.tsx', 'src/api/datasets.ts', 'src/vite-env.d.ts',
  ], { cwd: new URL('..', import.meta.url), encoding: 'utf8' });
  assert.equal(result.status, 0, `isolated dataset UI typecheck failed:\n${result.stdout}\n${result.stderr}`);
});

test('upload hashes real file bytes, uses safe requests, and returns a published revision', async () => {
  const { prepareUploadedDataset } = await client();
  const harness = successFetch(async (index, url, init) => {
    assert.equal(init.method, 'POST');
    assert.equal(init.redirect, 'error');
    assert.equal(new Headers(init.headers).get('Authorization'), `Bearer ${token}`);
    if (index === 0) {
      assert.equal(url, '/api/v1/artifacts/');
      const body = JSON.parse(init.body);
      assert.deepEqual({ ...body, object_key: 'generated' }, {
        storage_location_id: 'local', object_key: 'generated', sha256,
        byte_size: file().size, media_type: 'application/x-ndjson',
      });
      assert.match(body.object_key, /^inputs\/[0-9a-f-]{36}\.jsonl$/);
    } else if (index === 1) {
      assert.equal(url, `/api/v1/artifacts/${artifactId}/upload/`);
      assert.ok(init.body instanceof FormData);
      assert.equal(new Headers(init.headers).has('Content-Type'), false);
      assert.equal(await init.body.get('file').text(), content);
      assert.deepEqual([...init.body.keys()], ['file']);
    } else if (index === 2) {
      assert.equal(url, '/api/v1/datasets/');
      assert.deepEqual(JSON.parse(init.body), { name: dataset.name });
    } else {
      assert.equal(url, `/api/v1/datasets/${datasetId}/prepare/`);
      assert.deepEqual(JSON.parse(init.body), {
        input_artifact_id: artifactId, split_seed: '0', validation_percent: 10, test_percent: 10,
      });
    }
  });
  const result = await prepareUploadedDataset({ file: file(), name: dataset.name, token, fetchImpl: harness.fetchImpl });
  assert.deepEqual(result, { artifact, dataset, revision });
  assert.equal(harness.calls.length, 4);
  assert.equal(result.revision.dataset, 17, 'integer FKs must not be treated as business UUIDs');
});
