import test from 'node:test';
import assert from 'node:assert/strict';
import { computeReadiness } from '../src/api/compute.ts';

test('compute connection states never equate registration or stale heartbeat with readiness', () => {
  for (const [connection, text] of [
    ['not_connected', 'Waiting'], ['stale', 'stale'], ['credential_unavailable', 'revoked'],
    ['offline', 'offline'], ['connected', 'connected'],
  ]) assert.match(computeReadiness({ id: 1, status: 'available', connection_state: connection, capabilities: {} }), new RegExp(text));
  assert.match(computeReadiness({ id: 1, status: 'available', capabilities: {} }), /Waiting/);
  assert.match(computeReadiness({ id: 1, status: 'busy', connection_state: 'connected', capabilities: {} }), /busy/);
});
