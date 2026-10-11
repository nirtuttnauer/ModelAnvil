import test from 'node:test';
import assert from 'node:assert/strict';
import { questionInput, uploadOcrImage } from '../src/api/specialists.ts';

test('visual questions preserve typed labels and ordinal order and reject ambiguous options', () => {
  assert.deepEqual(questionInput('choice', 'Department?', 'billing: invoices\ntechnical: outages'), {
    type: 'choice', instructions: 'Department?', criteria: { billing: 'invoices', technical: 'outages' },
  });
  assert.deepEqual(questionInput('score', 'Urgency?', 'low\nmedium\nhigh').criteria, ['low','medium','high']);
  assert.deepEqual(questionInput('noul', 'Refund?', ''), { type: 'noul', instructions: 'Refund?' });
  assert.deepEqual(Object.keys(questionInput('choice', 'Question?', '__proto__: first\nother: second').criteria), ['__proto__','other']);
  for (const options of ['one', 'a: first\na: second', 'a:\nb: second', Array(9).fill('x').join('\n')]) {
    assert.throws(() => questionInput('choice', 'Question?', options));
  }
});

test('OCR upload sends original bytes and refuses oversized or unsupported files before the request', async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, init });
    return new Response(JSON.stringify({ artifact_id: 'image-id' }), { status: 201 });
  };
  try {
    const bytes = new Uint8Array([137,80,78,71,13,10,26,10]);
    const file = new File([bytes], 'receipt.png', { type: 'image/png' });
    const c = new AbortController();
    assert.equal((await uploadOcrImage('test-token', file, c.signal)).artifact_id, 'image-id');
    assert.equal(requests[0].url, '/api/v1/specialists/upload-image/');
    assert.equal(requests[0].init.signal, c.signal);
    assert.equal(requests[0].init.headers.get('Authorization'), 'Bearer test-token');
    assert.deepEqual(new Uint8Array(await requests[0].init.body.get('file').arrayBuffer()), bytes);
    await assert.rejects(uploadOcrImage('test-token', new File(['x'], 'x.pdf', { type: 'application/pdf' })));
    await assert.rejects(uploadOcrImage('test-token', new File([new Uint8Array(8 * 1024**2 + 1)], 'x.png', { type: 'image/png' })));
    assert.equal(requests.length, 1);
  } finally { globalThis.fetch = original; }
});
