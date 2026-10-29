import test from 'node:test';
import assert from 'node:assert/strict';
import { downloadModelExport, EXPORT_BUFFER_LIMIT, exportBytes } from '../src/api/model-export.ts';
import { setActiveProjectId } from '../src/api/client.ts';
const native = { format: 'native', extension: 'zip', label: 'Safetensors', description: '' };
const json = { format: 'json', extension: 'json', label: 'Manifest', description: '' };

async function fixture(response, options, run) {
  const original = { window: globalThis.window, fetch: globalThis.fetch, document: globalThis.document, create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  const calls = [], saved = [], updates = []; let aborted = false;
  globalThis.window = { location: { origin: 'http://localhost' }, ...(options.picker === false ? {} : { showSaveFilePicker: async value => {
    calls.push({ picker: value }); return { createWritable: async () => new WritableStream({ write: chunk => saved.push(chunk), abort: () => { aborted = true; } }) };
  } }) };
  globalThis.fetch = async (path, init) => { calls.push({ path, init }); return response; };
  const link = { click() { calls.push({ download: this.download }); }, remove() {} };
  globalThis.document = { body: { append() {} }, createElement: () => link };
  URL.createObjectURL = blob => { calls.push({ blob }); return 'blob:export'; }; URL.revokeObjectURL = () => {};
  try { await run({ calls, saved, updates, aborted: () => aborted, controller: new AbortController() }); }
  finally { globalThis.window = original.window; globalThis.fetch = original.fetch; globalThis.document = original.document; URL.createObjectURL = original.create; URL.revokeObjectURL = original.revoke; setActiveProjectId(null); }
}
function response(headers = {}) {
  return new Response(new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array([1, 2])); controller.enqueue(new Uint8Array([3, 4])); controller.close(); } }), { headers: { 'Content-Type': 'application/zip', 'Content-Length': '4', ...headers } });
}
test('model exports stream to disk with scoped authorization, real byte progress and no Blob', async () => {
  await fixture(response(), {}, async f => {
    setActiveProjectId('exact-project');
    const result = await downloadModelExport('run-id', native, 'secret', f.controller.signal, update => f.updates.push(update));
    assert.equal(result, 'saved'); assert.equal(f.calls[0].picker.suggestedName, 'modelanvil-run-id-native.zip');
    assert.equal(f.calls[1].path, '/api/v1/training-runs/run-id/download/?export_format=native');
    assert.equal(f.calls[1].init.headers.get('Authorization'), 'Bearer secret'); assert.equal(f.calls[1].init.headers.get('X-Project-ID'), 'exact-project');
    assert.equal(f.calls[1].init.signal, f.controller.signal); assert.equal(f.calls[1].init.redirect, 'error');
    assert.deepEqual(f.saved.map(chunk => [...chunk]), [[1, 2], [3, 4]]);
    assert.deepEqual(f.updates.filter(p => p.phase === 'downloading').map(p => p.received), [0, 2, 4]);
    assert.equal(f.updates.at(-1).phase, 'complete'); assert.equal(f.calls.some(call => call.blob), false);
  });
});
test('unknown and encoded response sizes stay indeterminate', async () => {
  for(const headers of [{ 'Content-Length': '' }, { 'Content-Encoding': 'gzip' }]) {
    await fixture(response(headers), {}, async f => {
      await downloadModelExport('run', native, 'token', f.controller.signal, update => f.updates.push(update));
      assert.ok(f.updates.every(update => update.total === null)); assert.equal(f.updates.at(-1).received, 4);
    });
  }
});
test('small JSON exports use the browser download fallback and the selected filename', async () => {
  await fixture(response({ 'Content-Type': 'application/json' }), { picker: false }, async f => {
    assert.equal(await downloadModelExport('run', { ...json, method: 'POST' }, 'token', f.controller.signal, update => f.updates.push(update)), 'browser');
    assert.equal(f.calls.find(call => call.path).init.method, 'POST');
    assert.equal(f.calls.find(call => call.download).download, 'modelanvil-run-json.json');
    assert.equal(f.calls.find(call => call.blob).blob.type, 'application/json');
    assert.equal(f.updates.at(-1).phase, 'complete');
  });
});
test('oversized known and unknown downloads refuse before a memory buffer grows', async () => {
  const oversized = new Response(new ReadableStream({ start(c) { c.enqueue({ byteLength: EXPORT_BUFFER_LIMIT + 1 }); c.close(); } }), { headers: { 'Content-Type': 'application/zip' } });
  for(const res of [response({ 'Content-Length': String(EXPORT_BUFFER_LIMIT + 1) }), oversized]) {
    await fixture(res, { picker: false }, async f => {
      await assert.rejects(downloadModelExport('run', native, 'token', f.controller.signal, update => f.updates.push(update)), /256 MiB/);
      assert.equal(f.updates.some(p => p.phase === 'complete'), false); assert.equal(f.calls.some(call => call.blob), false);
    });
  }
});
test('cancellation aborts the file stream and never reports completion', async () => {
  await fixture(response(), {}, async f => {
    await assert.rejects(downloadModelExport('run', native, 'token', f.controller.signal, update => {
      f.updates.push(update); if(update.received > 0) f.controller.abort();
    }), e => e.name === 'AbortError');
    assert.equal(f.aborted(), true); assert.equal(f.updates.some(p => p.phase === 'complete'), false);
  });
});
test('wrong formats and server errors never create a completed export', async () => {
  for(const res of [response({ 'Content-Type': 'text/html' }), new Response('failure', { status: 503 })]) {
    await fixture(res, {}, async f => {
      await assert.rejects(downloadModelExport('run', native, 'token', f.controller.signal, update => f.updates.push(update)), /selected export format|HTTP 503/);
      assert.equal(f.saved.length, 0); assert.equal(f.updates.some(p => p.phase === 'complete'), false);
    });
  }
  await fixture(response(), {}, async f => {
    f.controller.abort(); await assert.rejects(downloadModelExport('run', native, 'token', f.controller.signal, () => {}), e => e.name === 'AbortError');
    assert.equal(f.calls.some(call => call.path), false);
  });
});
test('byte labels keep actual binary units visible', () => {
  assert.equal(exportBytes(0), '0 B'); assert.equal(exportBytes(1024), '1.0 KiB'); assert.equal(exportBytes(1024**2), '1.0 MiB'); assert.equal(exportBytes(1024**3), '1.00 GiB');
});

test('DPO adapter downloads use the scoped alignment endpoint and reject unsupported formats', async () => {
  await fixture(response(), {}, async f => {
    await assert.rejects(downloadModelExport('dpo-id', native, 'token', f.controller.signal, () => {}, 'alignment-runs'), /Unsupported/);
    await downloadModelExport('dpo-id', { ...native, format: 'adapter' }, 'token', f.controller.signal, () => {}, 'alignment-runs');
    assert.equal(f.calls.find(call => call.path).path, '/api/v1/alignment-runs/dpo-id/download/?export_format=adapter');
    assert.equal(f.saved.length, 2);
  });
});

test('prepared merged and Q8 exports retain the scoped disk download path', async () => {
  for (const format of ['merged', 'gguf-q8']) {
    await fixture(response(), {}, async f => {
      await downloadModelExport('run-id', { ...native, format }, 'token', f.controller.signal, () => {});
      assert.equal(f.calls.find(v => v.path).path, `/api/v1/training-runs/run-id/download/?export_format=${format}`);
      assert.equal(f.calls[0].picker.suggestedName, `modelanvil-run-id-${format}.zip`);
    });
  }
});

test('reviewed exports bind the exact evaluation without changing raw export URLs', async () => {
  await fixture(response(), {}, async f => {
    await downloadModelExport('training', native, 'token', f.controller.signal, () => {}, 'training-runs', 'evaluation/id');
    assert.equal(f.calls.find(call => call.path).path, '/api/v1/training-runs/training/download/?export_format=native&evaluation_run=evaluation%2Fid');
  });
});
