import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { build } from 'rolldown';
import { fileURLToPath } from 'node:url';
const bundle = await build({ input: fileURLToPath(new URL('../src/api/client.ts', import.meta.url)), output: { format: 'cjs' }, write: false });
const compiled = bundle.output.find(item => item.type === 'chunk').code;
function fixture(picker = true) {
  const calls = []; const destination = {}; const stream = { pipeTo: async (...args) => calls.push({ stream: args }) };
  const module = { exports: {} };
  const window = { location: { origin: 'https://workspace.example' }, ...(picker ? { showSaveFilePicker: async options => { calls.push({ picker: options }); return { createWritable: async () => destination }; } } : {}) };
  vm.runInNewContext(compiled, { module, exports: module.exports, window, Headers, URL, fetch: async (path, init) => { calls.push({ path, init }); return { ok: true, status: 200, body: stream, blob() { throw Error('Large files must never become a Blob.'); } }; } });
  return { api: module.exports, calls, destination };
}
test('full artifact export pipes the authorized response directly to disk and forwards cancellation', async () => {
  const f = fixture(); const controller = new AbortController(); f.api.setActiveProjectId('project-1');
  await f.api.saveArtifact('artifact-1', 'complete.tar.gz', 'secret', controller.signal);
  assert.equal(f.calls[0].picker.suggestedName, 'complete.tar.gz');
  assert.equal(f.calls[1].path, '/api/v1/artifacts/artifact-1/download/');
  assert.equal(f.calls[1].init.headers.get('Authorization'), 'Bearer secret');
  assert.equal(f.calls[1].init.headers.get('X-Project-ID'), 'project-1');
  assert.equal(f.calls[1].init.redirect, 'error');
  assert.equal(f.calls[2].stream[0], f.destination);
  assert.equal(f.calls[2].stream[1].signal, controller.signal);
});
test('missing save picker refuses before fetching and describes the streaming API fallback', async () => {
  const f = fixture(false); await assert.rejects(f.api.saveArtifact('id', 'file', 'token'), /authenticated client/); assert.equal(f.calls.length, 0);
});
