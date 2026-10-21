import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { build } from 'rolldown';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const bundle = await build({
  input: fileURLToPath(new URL('../src/components/Identifier.tsx', import.meta.url)), platform: 'node',
  external: id => ['react', 'react-dom', 'react/jsx-runtime', 'lucide-react'].includes(id) || id.endsWith('.css'),
  output: { format: 'cjs' }, write: false,
});
const module = { exports: {} };
vm.runInNewContext(bundle.output.find(chunk => chunk.type === 'chunk').code, {
  module, exports: module.exports, require: id => id.endsWith('.css') ? {} : createRequire(import.meta.url)(id), console,
});
const { Identifier, isOpaqueIdentifier } = module.exports;
const render = props => renderToStaticMarkup(createElement(Identifier, props));
const value = '019a3621-4d78-7bd0-8e43-9a091242336a';

test('technical identifiers initially render one named non-submitting icon without exposing the value', () => {
  const html = render({ value, label: 'Model ID' });
  assert.match(html, /<button[^>]*type="button"/);
  assert.match(html, /aria-label="Copy Model ID"/);
  assert.match(html, /<svg[^>]*aria-hidden="true"/);
  assert.equal((html.match(/<button/g) || []).length, 1);
  assert.doesNotMatch(html, new RegExp(value));
  assert.doesNotMatch(html, /role="tooltip"|Copied|copied\./);
});

test('empty identifiers disappear while numeric zero remains available', () => {
  for (const empty of ['', null, undefined]) assert.equal(render({ value: empty }), '');
  const html = render({ value: 0 });
  assert.match(html, /aria-label="Copy ID"/);
  assert.match(html, /type="button"/);
});

test('identifier labels are escaped and values never become initial markup', () => {
  const html = render({ value: '<script>unsafe()</script>', label: '<script>"ID" & value</script>' });
  assert.match(html, /aria-label="Copy &lt;script&gt;&quot;ID&quot; &amp; value&lt;\/script&gt;"/);
  assert.doesNotMatch(html, /<script>|unsafe\(\)/);
});

test('opaque detection recognizes UUIDs and hashes without hiding ordinary prose or numeric labels', () => {
  for (const opaque of [value, value.toUpperCase(), 'a'.repeat(64), 'sha256:' + 'b'.repeat(64)]) assert.equal(isOpaqueIdentifier(opaque), true, opaque);
  for (const readable of ['Support assistant', 'sample-42', '0', 'helpful', 'abc', 'https://example.test']) assert.equal(isOpaqueIdentifier(readable), false, readable);
});
