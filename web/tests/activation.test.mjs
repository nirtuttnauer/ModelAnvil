import test from 'node:test';
import assert from 'node:assert/strict';
import { ActiveTime, startActivation } from '../src/api/activation.ts';
import { setActiveProjectId } from '../src/api/client.ts';

test('active time requires interactions, caps idle reading, and excludes hidden or unfocused intervals', () => {
  const clock = new ActiveTime(0, true);
  assert.equal(clock.sample(5000, true), 0);
  clock.interact(5000);
  assert.equal(clock.sample(10000, false), 5000);
  assert.equal(clock.sample(30000, true), 0);
  assert.equal(clock.sample(31000, true), 0);
  clock.interact(31000);
  assert.equal(clock.sample(61000, true), 15000);
  assert.equal(clock.sample(62000, true), 0);
});

test('measurement retries keep their event ID and cleanup keeps the original project without sending content', async () => {
  const names = ['window', 'document', 'sessionStorage', 'performance', 'fetch'];
  const previous = Object.fromEntries(names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const win = Object.assign(new EventTarget(), { location: { origin: 'http://localhost:15144' }, setInterval: () => 1, clearInterval: () => {} });
  const doc = Object.assign(new EventTarget(), { visibilityState: 'visible', hasFocus: () => true });
  const storage = new Map(); const requests = []; let now = 0;
  const values = { window: win, document: doc, performance: { now: () => now },
    sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    fetch: async (url, init) => { requests.push({url, headers: init.headers, event: JSON.parse(init.body)}); if (requests.length === 1) throw new Error('Uncertain response'); return {ok:true}; } };
  try {
    for (const name of names) Object.defineProperty(globalThis, name, {value: values[name], writable:true, configurable:true});
    const stop = startActivation('private-test-credential', 'original-project');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 2);
    assert.equal(requests[0].event.event_id, requests[1].event.event_id);
    now = 1000; win.dispatchEvent(new Event('keydown'));
    setActiveProjectId('different-project');
    now = 2000; stop();
    assert.equal(requests.at(-1).event.active_milliseconds, 1000);
    for (const request of requests) {
      assert.equal(request.url, '/api/v1/activation/events/');
      assert.equal(request.headers.get('X-Project-ID'), 'original-project');
      assert.deepEqual(Object.keys(request.event).sort(), ['active_milliseconds', 'event_id', 'kind', 'session_id']);
      assert.ok(!JSON.stringify(request.event).includes('private-test-credential'));
    }
  } finally {
    setActiveProjectId(null);
    for (const name of names) {
      if (previous[name]) Object.defineProperty(globalThis, name, previous[name]); else delete globalThis[name];
    }
  }
});
