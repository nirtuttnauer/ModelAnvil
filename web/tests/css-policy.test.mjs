import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

// Page and component stylesheets hold layout only. Everything that styles an element or a primitive
// lives in src/design-system (tokens → semantic → base → primitives) or in src/app.css (shell).
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const sheets = (dir) => readdirSync(new URL(dir, import.meta.url)).filter(name => name.endsWith('.css')).map(name => [`${dir}${name}`, read(`${dir}${name}`)]);
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
const selectors = (css) => [...stripComments(css).matchAll(/(?:^|[{};])\s*([^{};]+?)\s*\{/g)].map(match => match[1]).filter(selector => !selector.startsWith('@'));

const pages = sheets('../src/pages/');
const components = sheets('../src/components/');
const legacy = /\.(panel|panel-title|panel-body|notice|state|badge|form-grid|detail-box|workspace-details|text-button|icon-button|resource-table|empty-state)(?![\w-])/;

test('page stylesheets declare the layer order and wrap their rules in the pages layer', () => {
  assert.ok(pages.length > 0);
  for (const [name, css] of pages) {
    assert.match(css, /^@layer tokens, base, primitives, shell, pages;/, `${name} must start with the layer order`);
    assert.match(css, /@layer pages \{/, `${name} must wrap its rules in @layer pages`);
  }
});

test('page stylesheets contain layout only: no element, primitive or legacy selectors, no overrides, no color literals', () => {
  for (const [name, css] of pages) {
    assert.doesNotMatch(css, /\[data-ui/, `${name} restyles a primitive`);
    assert.doesNotMatch(css, /!important/, `${name} uses !important`);
    assert.doesNotMatch(stripComments(css), /#[0-9a-fA-F]{3,8}\b/, `${name} contains a color literal`);
    assert.doesNotMatch(css, legacy, `${name} references a retired class`);
    for (const selector of selectors(css)) for (const part of selector.split(',')) {
      assert.doesNotMatch(part.trim(), /^[a-z][a-z0-9]*(?![\w-])/, `${name}: "${part.trim()}" styles an element outside a class scope`);
    }
  }
});

test('component stylesheets stay free of overrides, color literals and retired classes', () => {
  for (const [name, css] of components) {
    assert.doesNotMatch(css, /!important/, `${name} uses !important`);
    assert.doesNotMatch(stripComments(css), /#[0-9a-fA-F]{3,8}\b/, `${name} contains a color literal`);
    assert.doesNotMatch(css, legacy, `${name} references a retired class`);
  }
});

test('the shell imports only the design system and its own stylesheet', () => {
  const main = read('../src/main.tsx');
  assert.match(main, /import '\.\/design-system\/index\.css';/);
  assert.match(main, /import '\.\/app\.css';/);
  for (const retired of ['style.css', 'premium.css', 'workspace-ui.css', 'design-system/components.css']) {
    assert.ok(!main.includes(retired), `main.tsx still imports ${retired}`);
  }
  assert.doesNotMatch(read('../src/design-system/primitives.css'), /LEGACY ALIASES/, 'the legacy alias block must stay deleted');
});
