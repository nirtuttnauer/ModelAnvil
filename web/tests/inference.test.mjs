import test from 'node:test';
import assert from 'node:assert/strict';
import { streamCompletion } from '../src/api/inference.ts';
import { setActiveProjectId } from '../src/api/client.ts';

const event = value => `data: ${typeof value === 'string' ? value : JSON.stringify(value)}\n\n`;
function response(parts) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({ start(controller) {
    for (const part of parts) controller.enqueue(encoder.encode(part));
    controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
}

test('token streaming handles split events, Unicode, usage and scoped authentication', async () => {
  setActiveProjectId('project-one');
  try {
    const bytes = event({ choices: [{ delta: { content: 'שלום' } }] }) + event({ choices: [], usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 } }) + event('[DONE]');
    let text = '', usage;
    await streamCompletion('key', { model: 'model-id', messages: [] }, new AbortController().signal,
      value => { text += value; }, value => { usage = value; }, async (url, init) => {
        assert.equal(url, '/api/v1/inference/chat/completions');
        assert.equal(init.headers.get('Authorization'), 'Bearer key');
        assert.equal(init.headers.get('X-Project-ID'), 'project-one');
        assert.equal(init.redirect, 'error');
        assert.equal(JSON.parse(init.body).stream, true);
        return response([bytes.slice(0, 18), bytes.slice(18, 85), bytes.slice(85)]);
      });
    assert.equal(text, 'שלום'); assert.equal(usage.total_tokens, 5);
  } finally { setActiveProjectId(null); }
});

test('truncated streams, server errors and unexpected response formats remain failures', async () => {
  const call = fetchImpl => streamCompletion('key', {}, new AbortController().signal, () => {}, () => {}, fetchImpl);
  await assert.rejects(call(async () => response([event({ choices: [{ delta: { content: 'partial' } }] })])), /before completion/);
  await assert.rejects(call(async () => response([event({ error: { message: 'Model failed' } })])), /Model failed/);
  await assert.rejects(call(async () => new Response('{}', { headers: { 'Content-Type': 'application/json' } })), /token stream/);
  await assert.rejects(call(async () => new Response(JSON.stringify({ error: { message: 'Denied' } }), { status: 403, headers: { 'Content-Type': 'application/json' } })), /Denied/);
});
