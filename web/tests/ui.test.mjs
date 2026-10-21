import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'rolldown';

const bundle = await build({ input: fileURLToPath(new URL('../src/components/ui.tsx', import.meta.url)), external: ['react', 'react/jsx-runtime'], output: { format: 'cjs' }, write: false });
const module = { exports: {} };
vm.runInNewContext(bundle.output.find(chunk => chunk.type === 'chunk').code, { module, exports: module.exports, require: createRequire(import.meta.url) });
const { Button, MetricSummary, RecordTable } = module.exports;
const render = (cells, headers = [h('th', { key: 0 }, 'Run'), h('th', { key: 1 }, 'State')]) => renderToStaticMarkup(h(RecordTable, null,
  h('caption', null, 'Recorded runs'), h('thead', null, h('tr', null, headers)), h('tbody', null, h('tr', null, cells))));

test('record cards retain captions, values, header associations and native actions', () => {
  const html = render([h('td', { key: 0 }, h(Button, { type: 'button' }, 'Inspect exact run')), h('td', { key: 1 }, 'completed')]);
  assert.match(html, /<caption>Recorded runs<\/caption>/);
  assert.match(html, /class="record-label" aria-hidden="true">Run<\/span>/);
  assert.match(html, /<button[^>]*type="button"[^>]*>Inspect exact run<\/button>/);
  assert.match(html, /role="cell"/);
  assert.match(html, />completed<\/div>/);
});

test('spanning tables and existing labeled row headers retain their own layout', () => {
  assert.doesNotMatch(render([h('td', { key: 0, colSpan: 2 }, 'No records')]), /record-table|record-label/);
  const html = render([h('th', { key: 0, scope: 'row', 'data-label': 'Run' }, 'Exact run'), h('td', { key: 1, 'data-label': 'State' }, 'ready')]);
  assert.doesNotMatch(html, /record-label/);
  assert.match(html, /scope="row"/);
});

test('metric actions keep native activation without submitting surrounding forms', () => {
  let opened = 0;
  const view = MetricSummary({ label: 'Datasets', value: 0, detail: 0, onClick: () => opened++ });
  const html = renderToStaticMarkup(view);
  assert.match(html, /<button[^>]*type="button"/);
  assert.match(html, /data-ui="metric-summary"/);
  assert.match(html, /<b>0<\/b>/);
  assert.match(html, /<small>0<\/small>/);
  view.props.onClick();
  assert.equal(opened, 1);
  assert.match(renderToStaticMarkup(h(MetricSummary, { label: 'Submit', value: 2, type: 'submit', disabled: true })), /type="submit"[^>]*disabled/);
});

test('read-only metrics stay articles and forward labels and native refs', () => {
  const ref = { current: null };
  const view = MetricSummary({ as: 'article', label: 'Reservations', value: '—', 'aria-label': 'Reservation count', ref });
  assert.equal(view.type, 'article');
  assert.equal(view.props.ref, ref);
  const html = renderToStaticMarkup(view);
  assert.match(html, /^<article[^>]*aria-label="Reservation count"/);
  assert.doesNotMatch(html, /<button|tabindex|<small| as=/);
});
