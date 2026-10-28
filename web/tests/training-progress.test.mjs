import test from 'node:test';
import assert from 'node:assert/strict';
import { trainingProgress, trainingDuration, trainingLossSeries } from '../src/api/training-progress.ts';

const now = Date.parse('2026-10-14T12:00:00Z');
const run = { status: 'running', current_step: 20, progress_step: 23, total_steps: 100, latest_loss: 0,
  runtime: { execution_mode: 'worker' }, started_at: new Date(now - 120000).toISOString(),
  metrics_log: [10, 20].map((step, i) => ({ step, loss: 1 - i, validation_loss: i ? 0 : undefined, measured_at: new Date(now - 60000 + i * 30000).toISOString() })) };

test('progress separates worker reports from committed checkpoints and estimates recent wall intervals', () => {
  const value = trainingProgress(run, now, true);
  assert.equal(value.committed, 20); assert.equal(value.reported, 23); assert.equal(value.percent, 23);
  assert.equal(value.elapsed, 120); assert.equal(value.secondsPerStep, 3); assert.equal(value.remaining, 231);
  assert.equal(value.remainingLabel, 'About 3m 51s');
});

test('engine estimates account for all updates in a checkpoint window, including recovered runs', () => {
  const value = trainingProgress({ ...run, current_step: 60, progress_step: 61,
    metrics_log: [{ step: 50, loss: 1, engine_wall_seconds: 20, updates_since_checkpoint: 10 }, { step: 60, loss: 0.8, engine_wall_seconds: 30, updates_since_checkpoint: 10 }] }, now, true);
  assert.equal(value.secondsPerStep, 2.5); assert.equal(value.remaining, 97.5);
  assert.match(value.basis, /Checkpoint storage/);
});

test('CPU step timings can estimate without GPU timestamps; CPU process time cannot', () => {
  const metrics_log = [{ step: 1, loss: 1, engine_wall_seconds: 0.1 }, { step: 2, loss: 0.5, engine_wall_seconds: 0.2 }];
  const value = trainingProgress({ ...run, current_step: 2, progress_step: 2, metrics_log }, now, true);
  assert.ok(Math.abs(value.secondsPerStep - 0.15) < 1e-9);
  assert.equal(trainingProgress({ ...run, metrics_log: metrics_log.map(row => ({ step: row.step, loss: row.loss, cpu_seconds: 1 })) }, now, true).remaining, null);
});

test('queued, stopped, synthetic and stale runs never get a remaining-time countdown', () => {
  for (const [changes, fresh, label] of [
    [{ status: 'pending', started_at: null }, true, 'Waiting to start'],
    [{ status: 'failed', completed_at: new Date(now - 60000).toISOString() }, true, 'Run stopped'],
    [{ status: 'cancelled' }, true, 'Run stopped'],
    [{ status: 'completed' }, true, 'Finished'],
    [{ runtime: { execution_mode: 'simulation' } }, true, 'Unavailable for synthetic runs'],
    [{}, false, 'Waiting for a fresh update'],
    [{ progress_step: 100 }, true, 'Finalizing run'],
  ]) {
    const value = trainingProgress({ ...run, ...changes }, now, fresh);
    assert.equal(value.remaining, null); assert.equal(value.remainingLabel, label);
  }
  assert.equal(trainingProgress({ ...run, status: 'failed', completed_at: new Date(now - 60000).toISOString() }, now, true).elapsed, 60);
  assert.equal(trainingProgress({ ...run, status: 'cancelled', completed_at: null }, now, true).elapsed, null);
});

test('insufficient or invalid timing is unknown and progress stays bounded', () => {
  for (const metrics_log of [[], [{ step: 1, loss: 1, engine_wall_seconds: 1 }], [{ step: 1, loss: 1, measured_at: 'bad' }, { step: 2, loss: 0, measured_at: 'bad' }],
    [{ step: 1, loss: 1, measured_at: new Date(now + 1000).toISOString() }, { step: 2, loss: 0, measured_at: new Date(now + 2000).toISOString() }],
    [{ step: 1, loss: 1, engine_wall_seconds: -1 }, { step: 2, loss: 0, engine_wall_seconds: Infinity }]]) {
    assert.equal(trainingProgress({ ...run, metrics_log }, now, true).remaining, null);
  }
  assert.equal(trainingProgress({ ...run, progress_step: 200 }, now, true).percent, 100);
  assert.equal(trainingProgress({ ...run, progress_step: -1 }, now, true).reported, 20);
  assert.equal(trainingProgress({ ...run, total_steps: 0 }, now, true).percent, null);
  assert.equal(trainingProgress({ ...run, started_at: 'bad' }, now, true).elapsed, null);
});

test('loss curves preserve zeros, omit missing validation, and sort/deduplicate exact steps', () => {
  const series = trainingLossSeries([{ step: 2, loss: NaN, validation_loss: null }, { step: 1, loss: 1 }, { step: 1, loss: 0, validation_loss: 0 }, { step: 3, loss: 0.5, validation_loss: Infinity }]);
  assert.deepEqual(series, [{ name: 'Training loss', points: [{ x: 1, y: 0 }, { x: 3, y: 0.5 }] }, { name: 'Validation loss', points: [{ x: 1, y: 0 }] }]);
  assert.deepEqual(trainingLossSeries(), []);
});

test('duration formatting retains unknown values and never shows zero for a positive estimate', () => {
  assert.equal(trainingDuration(null), 'Not reported'); assert.equal(trainingDuration(NaN), 'Not reported');
  assert.equal(trainingDuration(-1), 'Not reported'); assert.equal(trainingDuration(0.2), '< 1s');
  assert.equal(trainingDuration(0), '< 1s'); assert.equal(trainingDuration(60), '1m'); assert.equal(trainingDuration(3660), '1h 1m');
});

test('an unchanged old timing report does not present an estimate as live', () => {
  const value = trainingProgress({ ...run, metrics_log: run.metrics_log.map(row => ({ ...row, measured_at: new Date(Date.parse(row.measured_at) - 600000).toISOString() })) }, now, true);
  assert.equal(value.remaining, null); assert.equal(value.remainingLabel, 'Waiting for new step timings');
});
