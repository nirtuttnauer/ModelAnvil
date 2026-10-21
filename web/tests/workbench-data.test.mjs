import test from 'node:test';
import assert from 'node:assert/strict';
import { compareMetrics, highlightTerms } from '../src/components/workbench-data.ts';

test('comparison matches exact metric and slice, keeps baseline-only evidence, zeros and missing values', () => {
  const metric = (key, slice_name, value, sample_count = 0) => ({ key, slice_name, value, sample_count });
  const rows = compareMetrics([metric('accuracy', 'all', 0), metric('loss', 'all', 0.1), metric('accuracy', 'new', 0.5), metric('invalid', 'all', NaN), metric('huge', 'all', Number.MAX_VALUE)],
    [metric('loss', 'all', 0.2), metric('accuracy', 'all', 0), metric('accuracy', 'old', 0.8), metric('invalid', 'all', 0), metric('huge', 'all', -Number.MAX_VALUE)]);
  assert.equal(rows[0].delta, 0);
  assert.equal(rows[0].candidate.sample_count, 0);
  assert.equal(rows[1].delta, -0.1);
  assert.equal(rows[2].delta, null);
  assert.equal(rows[3].delta, null);
  assert.equal(rows[4].delta, null);
  assert.equal(rows[5].candidate, undefined);
  assert.equal(rows[5].baseline.value, 0.8);
  assert.deepEqual(compareMetrics([], []), []);
  assert.equal(compareMetrics([metric('a:b', 'c', 1)], [metric('a', 'b:c', 0)])[0].delta, null);
});

test('query highlighting preserves exact source text, handles Unicode and treats source markup as text', () => {
  for (const [text, query] of [['Password reset\nPASSWORD link', 'password'], ['שלום café 東京', 'שלום café 東京'], ['<script>alert(1)</script> [a+b]', 'script a+b'], ['  exact text\n', '.*'], ['repeat repeats', 'repeat repeat']]) {
    const parts = highlightTerms(text, query);
    assert.equal(parts.map(part => part.text).join(''), text);
  }
  assert.deepEqual(highlightTerms('Password reset', 'PASSWORD'), [{ text: 'Password', matched: true }, { text: ' reset', matched: false }]);
  assert.deepEqual(highlightTerms('exact', ''), [{ text: 'exact', matched: false }]);
});
