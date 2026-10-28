import test from 'node:test';
import assert from 'node:assert/strict';
import { apiRequest, apiPage, nextPagePath } from '../src/api/client.ts';
const token = 'test-only-key';
const originalFetch = globalThis.fetch;
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
async function withFetch(fetchImpl, run) { globalThis.fetch = fetchImpl; try { await run(); } finally { globalThis.fetch = originalFetch; } }

test('job submission carries auth, JSON, idempotency key, and refuses redirects', async () => {
  const job = { job_id: 'test-job', status: 'queued' };
  await withFetch(async (url, init) => {
    assert.equal(url, '/api/v1/jobs/');
    assert.equal(init.method, 'POST');
    assert.equal(init.redirect, 'error');
    assert.equal(init.headers.get('Authorization'), `Bearer ${token}`);
    assert.equal(init.headers.get('Content-Type'), 'application/json');
    assert.equal(init.headers.get('Idempotency-Key'), 'stable-retry-key');
    assert.deepEqual(JSON.parse(init.body), { name: 'Test job', pool: 1 });
    return json(job, 201);
  }, async () => assert.deepEqual(await apiRequest('/api/v1/jobs/', token, { method: 'POST', headers: { 'Idempotency-Key': 'stable-retry-key' }, body: JSON.stringify({ name: 'Test job', pool: 1 }) }), job));
});

test('cancellation keeps desired and observed states from accepted server result', async () => {
  const accepted = { status: 'running', desired_action: 'cancel' };
  await withFetch(async (url, init) => { assert.equal(url, '/api/v1/jobs/job-id/cancel/'); assert.equal(init.method, 'POST'); return json(accepted, 202); }, async () => {
    assert.deepEqual(await apiRequest('/api/v1/jobs/job-id/cancel/', token, { method: 'POST', body: '{}' }), accepted);
  });
});

test('401 and 403 have actionable errors and suppress arbitrary response bodies', async () => {
  for (const status of [401, 403]) await withFetch(async () => json({ detail: 'PRIVATE BODY' }, status), async () => {
    await assert.rejects(apiRequest('/api/v1/models/', token), e => { assert.equal(e.status, status); assert.doesNotMatch(e.message, /PRIVATE BODY/); assert.match(e.message, status === 401 ? /Authentication.*API key/ : /permission/); return true; });
  });
});

test('validation errors preserve useful field detail', async () => {
  await withFetch(async () => json({ error: { message: 'Validation failed.', details: [{ path: 'pool', message: 'Invalid pool.' }] } }, 400), async () => {
    await assert.rejects(apiRequest('/api/v1/jobs/', token), /pool: Invalid pool/);
  });
});

test('general validation errors show repair guidance without internal root paths', async () => {
  await withFetch(async () => json({ error: { message: 'Validation failed.', details: [{ path: '(root)', message: 'Example 1: response must contain nonempty text.' }] } }, 400), async () => {
    await assert.rejects(apiRequest('/api/v1/fine-tuning/preview/', token), error => {
      assert.match(error.message, /Example 1: response must contain nonempty text/);
      assert.doesNotMatch(error.message, /\(root\)/);
      return true;
    });
  });
});

test('invalid credentials or non-API paths never send a request', async () => {
  let calls = 0;
  await withFetch(async () => { calls++; return json({}); }, async () => {
    for (const path of ['https://outside.invalid/api/v1/jobs/', '//outside.invalid/api/v1/jobs/', '/other/', '/api/v1/jobs/#secret']) await assert.rejects(apiRequest(path, token), /Invalid API path/);
    await assert.rejects(apiRequest('/api/v1/jobs/', '  '), /API key/);
    assert.equal(calls, 0);
  });
});

test('pagination discards proxy host and fetches only the known resource', async () => {
  const path = nextPagePath('http://api:8000/api/v1/jobs/?cursor=opaque%3D', '/api/v1/jobs/');
  assert.equal(path, '/api/v1/jobs/?cursor=opaque%3D');
  await withFetch(async url => { assert.equal(url, path); return json({ results: [], next: null }); }, async () => assert.deepEqual(await apiPage(path, token), { results: [], next: null }));
  for (const next of ['https://evil.invalid/other/?cursor=1', '/api/v1/jobs/?token=secret', '/api/v1/jobs/#fragment', 'https://user:password@host/api/v1/jobs/']) assert.throws(() => nextPagePath(next, '/api/v1/jobs/'), /Invalid pagination/);
});

test('server errors and non-JSON responses remain sanitized', async () => {
  await withFetch(async () => new Response('<html>private traceback</html>', { status: 500 }), async () => await assert.rejects(apiRequest('/api/v1/models/', token), /HTTP 500/));
  await withFetch(async () => new Response('not-json'), async () => await assert.rejects(apiRequest('/api/v1/models/', token), /invalid JSON/));
});

test('malformed resource lists and aborted requests do not look empty or successful', async () => {
  await withFetch(async () => json({ detail: 'wrong shape' }), async () => await assert.rejects(apiPage('/api/v1/models/', token), /invalid resource list/));
  await withFetch(async () => { throw new DOMException('Aborted', 'AbortError'); }, async () => await assert.rejects(apiRequest('/api/v1/models/', token), e => e.name === 'AbortError'));
});

test('model archive download scopes credentials and rejects unsafe paths and response formats', async () => {
  const { apiDownload, setActiveProjectId } = await import('../src/api/client.ts');
  setActiveProjectId('archive-project');
  try {
    await withFetch(async (url, init) => {
      assert.equal(url, '/api/v1/training-runs/run/download/');
      assert.equal(init.headers.get('Authorization'), `Bearer ${token}`);
      assert.equal(init.headers.get('X-Project-ID'), 'archive-project');
      assert.equal(init.redirect, 'error');
      return new Response('verified archive bytes', { headers: { 'Content-Type': 'application/zip' } });
    }, async () => assert.equal(await (await apiDownload('/api/v1/training-runs/run/download/', token)).text(), 'verified archive bytes'));
    await withFetch(async () => json({}), async () => await assert.rejects(apiDownload('/api/v1/training-runs/run/download/', token), /model archive/));
    await assert.rejects(apiDownload('https://outside.invalid/api/v1/download/', token), /Invalid API path/);
  } finally { setActiveProjectId(null); }
});
