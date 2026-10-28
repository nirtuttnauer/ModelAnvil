import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'rolldown';

const bundle = await build({ input: fileURLToPath(new URL('../src/components/ImprovementReport.tsx', import.meta.url)), external: id => ['react', 'react/jsx-runtime'].includes(id) || id.endsWith('.css'), output: { format: 'cjs' }, write: false });
const module = { exports: {} };
vm.runInNewContext(bundle.output.find(chunk => chunk.type === 'chunk').code, { module, exports: module.exports, require: id => id.endsWith('.css') ? {} : createRequire(import.meta.url)(id) });
const { ImprovementReport } = module.exports;
const report = { available: true, complete_cases: 3, total_cases: 3, labels: ['billing', 'access'],
  candidate: { accuracy: 2 / 3, macro_f1: 0.5, confusion_matrix: [[1, 0, 1], [0, 1, 0]] }, baseline: { accuracy: 1 / 3, macro_f1: 0.25 },
  accuracy_delta: 1 / 3, accuracy_delta_interval: [-1 / 3, 1],
  case_changes: { improved: 1, regressed: 0, unchanged: 2, changed_cases: [{ case_id: 'case-2', expected_output: 'access', candidate_output: 'access', baseline_output: 'billing', change: 'improved' }] } };
const render = value => renderToStaticMarkup(h(ImprovementReport, { report: value, runId: 'evaluation', candidateName: 'Candidate', baselineName: 'Base' }));

test('decision report shows paired change, uncertainty, invalid outputs and exact changed cases', () => {
  const html = render(report);
  assert.match(html, /66.7%/); assert.match(html, /33.3%/); assert.match(html, /\+33.3 percentage points/);
  assert.match(html, /-33.3 to 100.0 points/); assert.match(html, /Invalid output/);
  assert.match(html, /case-2/); assert.match(html, /1 improved · 0 regressed · 2 unchanged cases/);
});

test('partial comparisons cannot present scored verdicts or enable report download', () => {
  const html = render({ ...report, available: false, complete_cases: 1, reason: 'Missing baseline cases.' });
  assert.match(html, /Missing baseline cases/); assert.match(html, /disabled=""/);
  assert.doesNotMatch(html, /66.7%|\+33.3 percentage points/);
});

test('unreported measures remain unknown and content is escaped', () => {
  const html = render({ ...report, candidate: { accuracy: null, macro_f1: null }, accuracy_delta: null, accuracy_delta_interval: null, case_changes: { improved: 0, regressed: 1, unchanged: 2, changed_cases: [{ case_id: '<script>', expected_output: 'a', candidate_output: '<img>', baseline_output: 'a', change: 'regressed' }] } });
  assert.match(html, /Not reported/); assert.doesNotMatch(html, /NaN|<script>|<img>/);
  assert.match(html, /&lt;script&gt;/);
});

test('resource evidence distinguishes recorded zero queue time from absent memory measurements', () => {
  const html = render({ ...report, resource_evidence: { evaluation: { execution_seconds: 28.4, queue_seconds: 0, usage_available: true, usage: [{ quantity: '3', unit: 'evaluation_cases', amount: null, currency: null }] }, peak_memory_bytes: null } });
  assert.match(html, /28.4 seconds/); assert.match(html, /3 evaluation cases/);
  assert.match(html, /Evaluation queue time: 0.0 seconds/); assert.match(html, /Peak memory<\/dt><dd>Not measured/);
  assert.doesNotMatch(html, /\$0|0.00 GiB/);
});
