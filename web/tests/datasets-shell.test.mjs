import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Integration seam guard; real browser/API acceptance is run separately.
test('the dataset navigation mounts the real page and does not fetch source snapshots', () => {
  const source = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.match(source, /import\s+\{\s*DatasetsPage\s*\}\s+from\s+['"]\.\/pages\/DatasetsPage['"]/);
  assert.match(source, /<DatasetsPage\s+token=\{token\}\s+refreshKey=\{datasetRefreshKey\}/);
  assert.doesNotMatch(source, /name:\s*'Datasets'[^\n]*source-snapshots/);
  assert.match(source, /if\s*\(page === 'Datasets'\)/);
});
