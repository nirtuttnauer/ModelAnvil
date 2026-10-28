import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { build } from 'rolldown';

async function load(file) {
  const bundle = await build({ input: fileURLToPath(new URL(`../src/components/${file}.tsx`, import.meta.url)), external: ['react', 'react/jsx-runtime'], output: { format: 'cjs' }, write: false });
  const module = { exports: {} };
  vm.runInNewContext(bundle.output.find(chunk => chunk.type === 'chunk').code, { module, exports: module.exports, require: createRequire(import.meta.url) });
  return module.exports;
}
const [{ Feedback }, { ResourceState }] = await Promise.all([load('Feedback'), load('ResourceState')]);

test('loading announces its text while decorative icons stay hidden from assistive technology', () => {
  const html = renderToStaticMarkup(h(ResourceState, { loading: true }));
  assert.match(html, /role="status"/);
  assert.match(html, /Loading workspace data…/);
  assert.match(html, /aria-hidden="true"/);
  assert.doesNotMatch(html, /aria-busy="true"/);
  assert.equal(ResourceState({}), null);
});

test('error recovery takes precedence over loading and never submits a containing form', () => {
  let retries = 0;
  const result = ResourceState({ loading: true, error: 'Request <failed>', onRetry: () => retries++ });
  const html = renderToStaticMarkup(result);
  assert.match(html, /role="alert"/);
  assert.match(html, /Request &lt;failed&gt;/);
  assert.match(html, /<button[^>]*type="button"[^>]*>Try again<\/button>/);
  assert.doesNotMatch(html, /Loading workspace/);
  result.props.action.props.onClick();
  assert.equal(retries, 1);
});

test('empty feedback preserves content and native attributes without announcing a new alert', () => {
  const html = renderToStaticMarkup(h(Feedback, { state: 'empty', title: 'No matching sources', description: 'Clear your filters.', 'data-test': 'catalog', tabIndex: -1 }));
  assert.match(html, /No matching sources/);
  assert.match(html, /Clear your filters\./);
  assert.match(html, /data-test="catalog"/);
  assert.match(html, /tabindex="-1"/);
  assert.doesNotMatch(html, /role="(?:alert|status)"/);
  assert.doesNotMatch(html, /feedback-action/);
});
