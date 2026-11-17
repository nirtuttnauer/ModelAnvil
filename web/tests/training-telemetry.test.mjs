import test from 'node:test';
import assert from 'node:assert/strict';
import { NOT_REPORTED, measuredAt, mebibytes, missingReasons, optimizationSummary, telemetryCell, telemetryRows } from '../src/api/training-telemetry.ts';

const mlxRow = {
  step: 2, loss: 2.5, measured_at: '2026-11-15T16:40:12.345678+00:00', gradient_norm: 0.125, tokens_per_second: 812.5,
  training_pairs: 640, padding_positions: 96, gpu_allocated_bytes: 300 * 1024 ** 2, peak_allocated_bytes: 1536 * 1024 ** 2,
  peak_reserved_bytes: null, gpu_utilization_percent: null,
  unavailable_metrics: { peak_reserved_bytes: 'not_exposed_by_mlx', gpu_utilization_percent: 'not_exposed_by_mlx' },
};

test('measured values render; runtime-declared gaps say why and are never estimated', () => {
  assert.equal(telemetryCell(mlxRow, 'loss', v => v.toFixed(3)), '2.500');
  assert.equal(telemetryCell(mlxRow, 'gradient_norm', v => v.toFixed(4)), '0.1250');
  assert.equal(telemetryCell(mlxRow, 'peak_allocated_bytes', mebibytes), '1536.0');
  assert.equal(telemetryCell(mlxRow, 'peak_reserved_bytes', mebibytes), 'Not exposed by MLX');
  assert.equal(telemetryCell(mlxRow, 'gpu_utilization_percent', v => `${v}%`), 'Not exposed by MLX');
  // Without a declared reason the value is plainly missing; zero is a measurement, not a gap.
  assert.equal(telemetryCell({ step: 1, peak_allocated_bytes: null }, 'peak_allocated_bytes', mebibytes), NOT_REPORTED);
  assert.equal(telemetryCell({ step: 1, gpu_utilization_percent: 0 }, 'gpu_utilization_percent', v => `${v}%`), '0%');
  assert.equal(telemetryCell({ step: 1, tokens_per_second: NaN }, 'tokens_per_second', v => v.toFixed(2)), NOT_REPORTED);
  assert.equal(telemetryCell({ step: 1, unavailable_metrics: { loss: 'unknown_code' } }, 'loss', v => String(v)), NOT_REPORTED);
  const reasons = missingReasons([mlxRow, { ...mlxRow, step: 3 }]);
  assert.equal(reasons.length, 1);
  assert.deepEqual(reasons[0].metrics, ['Peak reserved memory', 'GPU utilization']);
  assert.match(reasons[0].reason, /not estimated/);
  assert.deepEqual(missingReasons([{ ...mlxRow, gpu_utilization_percent: 40, peak_reserved_bytes: 1 }]), []);
});

test('rows need a measurement time, keep one entry per step and show the latest steps in order', () => {
  const rows = telemetryRows([{ step: 3, measured_at: 'a' }, { step: 1, measured_at: 'b' }, { step: 2 }, { step: 3, measured_at: 'c' }, { step: -1, measured_at: 'd' }, { step: 1.5, measured_at: 'e' }]);
  assert.deepEqual(rows.map(row => [row.step, row.measured_at]), [[1, 'b'], [3, 'c']]);
  assert.equal(telemetryRows(Array.from({ length: 25 }, (_, step) => ({ step, measured_at: 'x' }))).length, 10);
  assert.equal(measuredAt(mlxRow.measured_at), '2026-11-15 16:40:12 UTC');
  assert.equal(measuredAt('bad'), 'Time not reported');
  assert.equal(measuredAt(undefined), 'Time not reported');
});

test('the pinned optimization profile is described without raw identifiers', () => {
  assert.equal(optimizationSummary(null), null);
  assert.equal(optimizationSummary({ compute_precision: 'fp32', gradient_checkpointing: false, batch_samples: 1, sequence_layout: 'padded', attention_kernel: 'mlx_fast_sdpa', optimizer: 'adamw' }),
    'FP32 compute · one sample per step · no gradient checkpointing · AdamW · MLX fast attention');
  assert.equal(optimizationSummary({ compute_precision: 'bf16', gradient_checkpointing: true, batch_samples: 8, sequence_layout: 'packed', attention_kernel: 'mlx_fast_sdpa_force_fused', optimizer: 'adafactor' }),
    'BF16 compute, FP32 adapters · 8 samples per step, packed with sample-boundary masks · gradient checkpointing · Adafactor (factored, no momentum) · MLX fast attention, fused kernel forced');
});
