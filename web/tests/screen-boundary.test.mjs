import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { build } from 'rolldown';
import { Suspense } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const bundle = await build({
  input: fileURLToPath(new URL('../src/components/ScreenBoundary.tsx', import.meta.url)),
  external: ['react', 'react/jsx-runtime'], output: { format: 'cjs' }, write: false,
});
const module = { exports: {} };
let reloads = 0;
vm.runInNewContext(bundle.output.find(chunk => chunk.type === 'chunk').code, {
  module, exports: module.exports, require: createRequire(import.meta.url),
  window: { location: { reload() { reloads++; } } },
});
const { ScreenBoundary } = module.exports;

test('pending screen loads retain their content and accessible loading feedback', () => {
  const screen = new ScreenBoundary({ children: 'Screen content' });
  const rendered = screen.render();
  assert.equal(rendered.type, Suspense);
  assert.equal(rendered.props.children, 'Screen content');
  const fallback = renderToStaticMarkup(rendered.props.fallback);
  assert.match(fallback, /role="status"/);
  assert.match(fallback, /Loading screen…/);
});

test('screen failures offer reload without exposing internal error details', () => {
  const screen = new ScreenBoundary({ children: 'Screen content' });
  screen.state = ScreenBoundary.getDerivedStateFromError(new Error('Private module details'));
  const rendered = screen.render();
  const html = renderToStaticMarkup(rendered);
  assert.match(html, /role="alert"/);
  assert.doesNotMatch(html, /Private module details/);
  const button = rendered.props.action;
  assert.equal(button.props.type, 'button');
  assert.equal(button.props.children, 'Reload app');
  button.props.onClick();
  assert.equal(reloads, 1);
});
