import test from 'node:test';
import assert from 'node:assert/strict';
import { chartRange, formatValue, interval, numericEntries, validPoints } from '../src/components/chart-data.ts';

test('chart scales handle zero, single values, negatives, and missing measurements', () => {
  assert.deepEqual(chartRange([]), [0, 1]);
  assert.deepEqual(chartRange([NaN, Infinity]), [0, 1]);
  assert.deepEqual(chartRange([0], true), [0, 1]);
  assert.deepEqual(chartRange([-3, 7], true), [-3, 7]);
  assert.deepEqual(chartRange([4, 8], true), [0, 8]);
  const [min, max] = chartRange([-5]);
  assert.ok(min < -5 && max > -5);
});
test('numeric plot data keeps legitimate zero and rejects non-numeric values', () => {
  assert.deepEqual(validPoints([{ x: 2, y: 0 }, { x: 1, y: 4 }, { x: 3, y: NaN }]), [{ x: 1, y: 4 }, { x: 2, y: 0 }]);
  assert.notEqual(formatValue(.000001), '0');
  assert.notEqual(formatValue(-.000001), '-0');
  assert.deepEqual(numericEntries({ pass_rate: 0, count: 4, missing: null, bool: true, bad: Infinity, text: '4' }), [{ label: 'pass rate', value: 0 }, { label: 'count', value: 4 }]);
});
test('uncertainty is only displayed when the stored bounds are finite and ordered', () => {
  assert.deepEqual(interval({ lower: 0, upper: 1 }), { lower: 0, upper: 1 });
  assert.deepEqual(interval({ ci_low: 0.2, ci_high: 0.8, confidence: 0.95 }), { lower: 0.2, upper: 0.8 });
  assert.equal(interval({ ci_low: 0.8, ci_high: 0.2 }), undefined);
  for (const v of [null, {}, { lower: '0', upper: 1 }, { lower: 2, upper: 1 }, { lower: 0, upper: Infinity }]) assert.equal(interval(v), undefined);
});

test('optimizer ticks preserve visible distinctions across small measured loss changes', () => {
  const low = .69308267, high = .69314718;
  const resolution = (high-low)/4;
  const labels = Array.from({length:5}, (_, i) => formatValue(low + i*resolution, resolution));
  assert.equal(new Set(labels).size, 5);
  assert.notEqual(formatValue(low, resolution), formatValue(high, resolution));
});
