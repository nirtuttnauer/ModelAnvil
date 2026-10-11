// Invoked only by isolated LiveServerTestCase fixtures. Never logs input or credentials.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { DatasetClientError, loadDatasetFirstPages, prepareUploadedDataset } from '../web/src/api/datasets.ts';

try {
  const input = JSON.parse(readFileSync(0, 'utf8'));
  const base = new URL(input.base);
  assert.equal(base.protocol, 'http:');
  assert.equal(base.hostname, '127.0.0.1');
  assert.equal(base.pathname, '/');
  assert.equal(base.search + base.hash + base.username + base.password, '');
  let requestCount = 0;
  const fetchImpl = async (path, init) => {
    assert.equal(typeof path, 'string');
    assert.match(path, /^\/api\/v1\/[a-z0-9/-]+\/$/);
    const target = new URL(path, base);
    assert.equal(target.origin, base.origin);
    requestCount++;
    return fetch(target, { ...init, signal: AbortSignal.timeout(10000) });
  };
  const options = { file: new File([input.raw], 'canonical.jsonl', { type: 'application/x-ndjson' }),
    name: input.name, token: input.token, splitSeed: 'http-fixture', fetchImpl };
  if (input.invalid) {
    await assert.rejects(prepareUploadedDataset(options), error => error instanceof DatasetClientError
      && error.step === 'Dataset preparation' && error.status === 400
      && !error.message.includes('PRIVATE_MARKER'));
    assert.equal(requestCount, 4);
    console.log(JSON.stringify({ state: 'refused', status: 400, request_count: requestCount }));
  } else {
    const result = await prepareUploadedDataset(options);
    const pages = await loadDatasetFirstPages({ token: input.token, fetchImpl });
    const dataset = pages.datasets.results.find(row => row.dataset_id === result.dataset.dataset_id);
    const revision = pages.revisions.results.find(row => row.revision_id === result.revision.revision_id);
    assert.ok(dataset && revision);
    assert.ok(Number.isInteger(dataset.current_revision));
    assert.equal(revision.state, 'published');
    assert.equal(revision.manifest_digest, result.revision.manifest_digest);
    const headers = { Authorization: `Bearer ${input.token}`, Accept: 'application/json' };
    const registryResponse = await fetchImpl('/api/v1/artifacts/', { headers, redirect: 'error' });
    assert.equal(registryResponse.status, 200);
    const registry = await registryResponse.json();
    const manifest = registry.results.find(row => row.sha256 === revision.manifest_digest
      && row.metadata.kind === 'prepared_dataset');
    assert.ok(manifest);
    assert.match(manifest.artifact_id, /^[0-9a-f]{8}-[0-9a-f-]{27}$/);
    const downloaded = await fetchImpl(`/api/v1/artifacts/${manifest.artifact_id}/download/`,
      { headers, redirect: 'error' });
    assert.equal(downloaded.status, 200);
    const bytes = Buffer.from(await downloaded.arrayBuffer());
    assert.equal(bytes.length, manifest.byte_size);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), revision.manifest_digest);
    const prepared = JSON.parse(bytes.toString('utf8'));
    const documents = input.raw.trimEnd().split('\n').map(line => JSON.parse(line));
    assert.deepEqual(prepared.rows, documents);
    assert.equal(prepared.row_count, documents.length);
    assert.equal(prepared.recipe_digest, revision.recipe_digest);
    const ids = Object.values(prepared.split_manifest).flat();
    assert.deepEqual(ids.toSorted(), documents.map(row => row.sample_id).toSorted());
    assert.equal(Object.values(prepared.split_manifest).filter(rows => rows.length > 0).length, 1);
    console.log(JSON.stringify({ state: revision.state, revision_id: revision.revision_id,
      row_count: revision.row_count, request_count: requestCount }));
  }
} catch (error) {
  // Assertions might contain raw response data; expose only client-owned safe errors.
  console.error(error instanceof DatasetClientError ? error.message : 'Dataset HTTP acceptance assertion failed.');
  process.exitCode = 1;
}
