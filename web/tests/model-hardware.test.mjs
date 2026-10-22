import test from 'node:test';
import assert from 'node:assert/strict';
import { modelHardwareFit, workerHardware, memoryBytes, formatMemory } from '../src/api/model-hardware.ts';

const gib = 1024 ** 3;
const now = Date.now();
const requirements = { host_memory_bytes: 8 * gib, accelerator_memory_bytes: 4 * gib,
  accelerator_backends: ['mps', 'cuda'], runtime_contract: 'pinned-runtime', basis: 'Declared profile' };
const target = { id: 'one', name: 'GPU worker', hostBytes: 16 * gib, acceleratorBytes: 8 * gib,
  backend: 'cuda', runtimeContract: 'pinned-runtime', connected: true, busy: false, observedAt: now, maxAgeSeconds: 60 };

test('fit compares both host and accelerator requirements without treating total memory as free capacity', () => {
  assert.equal(modelHardwareFit(requirements, [target], now).status, 'meets');
  assert.equal(modelHardwareFit(requirements, [{ ...target, hostBytes: 4 * gib }], now).status, 'insufficient');
  assert.equal(modelHardwareFit(requirements, [{ ...target, acceleratorBytes: 2 * gib }], now).status, 'insufficient');
  assert.equal(modelHardwareFit(requirements, [{ ...target, acceleratorBytes: null }], now).status, 'partial');
  assert.equal(modelHardwareFit(requirements, [{ ...target, hostBytes: null }], now).status, 'unknown');
  const busy = modelHardwareFit(requirements, [{ ...target, busy: true }], now);
  assert.equal(busy.status, 'meets'); assert.equal(busy.target.busy, true); assert.match(busy.reason, /Free memory/);
});

test('offline, stale, future and mismatched hardware never reports a memory fit', () => {
  for (const change of [{ connected: false }, { observedAt: now - 61000 }, { observedAt: now + 1000 }, { observedAt: NaN }]) {
    assert.equal(modelHardwareFit(requirements, [{ ...target, ...change }], now).status, 'offline');
  }
  assert.equal(modelHardwareFit(requirements, [{ ...target, runtimeContract: 'other' }], now).status, 'unknown');
  assert.equal(modelHardwareFit(requirements, [{ ...target, backend: 'cpu' }], now).status, 'unsupported');
  assert.equal(modelHardwareFit(requirements, [{ ...target, backend: '' }], now).status, 'unknown');
  assert.equal(modelHardwareFit(null, [target], now).status, 'unknown');
});

test('the best matching worker is compared individually; device memory is never combined across workers', () => {
  const small = { ...target, id: 'small', acceleratorBytes: 2 * gib };
  assert.equal(modelHardwareFit(requirements, [small, { ...small, id: 'second' }], now).status, 'insufficient');
  assert.equal(modelHardwareFit(requirements, [small, target], now).target.id, 'one');
  const cpu = { ...requirements, accelerator_memory_bytes: 0, accelerator_backends: ['cpu'] };
  assert.equal(modelHardwareFit(cpu, [{ ...target, backend: 'cpu', acceleratorBytes: null }], now).status, 'meets');
});

test('unknown and malformed measurements stay unknown, and worker declarations retain freshness and busy state', () => {
  for (const value of [null, undefined, 0, -1, NaN, Infinity, true, '16 GiB', 1.5]) assert.equal(memoryBytes(value), null);
  assert.equal(formatMemory(16 * gib), '16 GiB'); assert.equal(formatMemory(gib / 4), '256 MiB'); assert.equal(formatMemory(null), 'Unknown');
  const worker = workerHardware({ id: 3, name: 'Local', pool: 1, pool_name: 'CPU', status: 'busy', connection_state: 'connected',
    last_heartbeat_at: new Date(now - 30000).toISOString(), capabilities: { memory_bytes: 16 * gib, accelerator: 'cpu', training_runtime: 'pinned-runtime' } }, now);
  assert.equal(worker.busy, true); assert.equal(worker.observedAt, now - 30000); assert.equal(worker.acceleratorBytes, null);
  assert.equal(workerHardware({ id: 1, name: 'Bad', pool: 1, pool_name: 'Pool', status: 'available', capabilities: {} }, now).connected, false);
});
