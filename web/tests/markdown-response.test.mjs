import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { build } from 'rolldown';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { structuredResponse } from '../src/api/response-content.ts';

const bundle = await build({
  input: fileURLToPath(new URL('../src/components/MarkdownResponse.tsx', import.meta.url)),
  platform: 'node', external: id => ['react', 'react-dom', 'react/jsx-runtime'].includes(id) || id.endsWith('.css'), output: { format: 'cjs' }, write: false,
});
const module = { exports: {} };
vm.runInNewContext(bundle.output.find(chunk => chunk.type === 'chunk').code, {
  module, exports: module.exports, require: id => id.endsWith('.css') ? {} : createRequire(import.meta.url)(id), console,
});
const { ChatResponseContent } = module.exports;
const render = text => renderToStaticMarkup(createElement(ChatResponseContent, { text }));

test('responses render Markdown headings, emphasis, lists, tables and inline code', () => {
  const html = render('## Answer\n\nUse **training** and `model.fit()`.\n\n- First\n- Second\n\n| Method | Steps |\n| --- | --- |\n| SFT | 73 |');
  for (const fragment of ['<h2>Answer</h2>', '<strong>training</strong>', '<code>model.fit()</code>', '<li>First</li>', '<table>', '<th>Method</th>', 'Copy response']) assert.ok(html.includes(fragment), fragment);
});

test('fenced, indented and incomplete streamed code stays text with separate copy controls', () => {
  const html = render('```python\ndef train():\n    return "<script>"\n```\n\n    indented_code()\n');
  assert.ok(html.includes('language-python'));
  assert.ok(html.includes('    return &quot;&lt;script&gt;&quot;'));
  assert.equal((html.match(/aria-label="Copy code"/g) || []).length, 2);
  const partial = render('```python\ndef train():\n    return');
  assert.ok(partial.includes('language-python'));
  assert.ok(partial.includes('    return'));
  assert.ok(render('```').includes('response-code-block'));
});

test('model content cannot execute HTML or unsafe links and images make no remote requests', () => {
  const html = render('<script>alert(1)</script>\n\n<img src="https://example.test/track" onerror="alert(1)">\n\n[bad](javascript:alert%281%29)\n\n[good](https://example.test/docs)\n\n![Source image](https://example.test/image.png)\n\n![bad](data:image/svg+xml,test)');
  assert.doesNotMatch(html, /<script|<img|href="javascript:|href="data:/);
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('href="https://example.test/docs" target="_blank" rel="noopener noreferrer"'));
  assert.ok(html.includes('href="https://example.test/image.png"'));
  assert.ok(html.includes('Source image'));
});

test('plain JSON retains its inspector while fenced JSON is a copyable chat code block', () => {
  assert.deepEqual(structuredResponse(' {"score":0,"passed":false} '), { score: 0, passed: false });
  assert.deepEqual(structuredResponse('```json\n{"score":0}\n```'), { score: 0 });
  assert.equal(structuredResponse('```json\n{"score":0}\n```', false), null);
  assert.ok(render('{"score":0,"passed":false}').includes('data-inspector'));
  const fenced = render('```json\n{"score":0}\n```');
  assert.ok(fenced.includes('language-json')); assert.ok(fenced.includes('Copy code'));
  for (const text of ['{"partial":', '42', '[unfinished', 'null']) assert.equal(structuredResponse(text), null);
  assert.ok(render(null).includes('Not reported')); assert.ok(render('').includes('Empty text'));
  assert.doesNotMatch(render(null), /Copy response/);
});
