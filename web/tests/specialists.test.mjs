import test from 'node:test';
import assert from 'node:assert/strict';
import { questionInput, queueSpecialist, uploadOcrImage } from '../src/api/specialists.ts';

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

test('durable admission preserves layout and typed inputs and requires explicit quota', async () => {
  const original = globalThis.fetch; const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({url, init});
    return new Response(JSON.stringify({request_id:'run',job_id:'job',status:'queued'}),{status:202});
  };
  try {
    const request = { model:'ocr', image_artifact:'source', layout_model:'layout', max_tokens:256 };
    await assert.rejects(queueSpecialist('token','ocr',request,'','policy'));
    await assert.rejects(queueSpecialist('token','ocr',request,'1',''));
    const signal = new AbortController().signal;
    assert.equal((await queueSpecialist('token','ocr',request,'7','policy',signal)).status,'queued');
    assert.equal(requests.length,1); assert.equal(requests[0].url,'/api/v1/specialists/jobs/');
    assert.equal(requests[0].init.signal,signal);
    const payload=JSON.parse(requests[0].init.body);
    assert.deepEqual(payload.request,request); assert.equal(payload.pool,7);
    assert.equal(payload.budget_policy,'policy'); assert.match(payload.idempotency_key,/^[a-f0-9-]{36}$/);
  } finally { globalThis.fetch=original; }
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
    await uploadOcrImage('test-token', new File(['%PDF-fixture'], 'scan.pdf', { type: 'application/pdf' }));
    assert.equal(await requests[1].init.body.get('file').text(),'%PDF-fixture');
    await assert.rejects(uploadOcrImage('test-token', new File(['x'], 'x.gif', { type: 'image/gif' })));
    await assert.rejects(uploadOcrImage('test-token', new File([new Uint8Array(8 * 1024**2 + 1)], 'x.png', { type: 'image/png' })));
    assert.equal(requests.length, 2);
  } finally { globalThis.fetch = original; }
});
