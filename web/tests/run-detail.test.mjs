import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { attemptsPath, detailPath, parseRunRoute, runHash, runRoute } from '../src/api/runs.ts';

const id = '11111111-2222-3333-4444-555555555555';

test('a run deep link round-trips through reload and back navigation', () => {
  assert.equal(runRoute('training', id), `runs/training/${id}`);
  assert.equal(runHash('job', id), `#runs/job/${id}`);
  assert.deepEqual(parseRunRoute(`#runs/training/${id}`), { kind: 'training', id });
  assert.deepEqual(parseRunRoute(`#runs/evaluation/${id}?from=workflows`), { kind: 'evaluation', id });
  assert.deepEqual(parseRunRoute(`#runs/job/${id.toUpperCase()}`), { kind: 'job', id: id.toUpperCase() });
});

test('only well-formed run identifiers produce a run route', () => {
  for (const hash of [
    `#runs`,
    `#runs/training`,
    `#runs/training/${id}/extra`,
    `#runs/dataset/${id}`,
    `#runs/training/not-a-uuid`,
    `#runs/training/${id.slice(0, -1)}x`,
    `#workflows`,
    '',
  ]) {
    assert.equal(parseRunRoute(hash), null, `${hash} must not resolve to a run`);
  }
});

test('run detail and attempts paths stay under the read-only projection', () => {
  assert.equal(detailPath('job', id), `/api/v1/run-details/job/${id}/`);
  assert.equal(attemptsPath('job', id), `/api/v1/run-details/job/${id}/attempts/`);
  for (const path of [detailPath('training', id), attemptsPath('evaluation', id)]) {
    assert.match(path, /^\/api\/v1\/run-details\/(job|training|evaluation)\/[0-9a-f-]{36}\/(attempts\/)?$/);
  }
});

test('the shell mounts the run view and keeps it on the address for reload and back', () => {
  const source = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  assert.match(source, /import\s+\{\s*RunDetailPage\s*\}\s+from\s+['"]\.\/pages\/RunDetailPage['"]/);
  assert.match(source, /<RunDetailPage[\s\S]*?refreshKey=\{refreshKey\}/);
  assert.match(source, /setRunRoute\(parseRunRoute\(window\.location\.hash\)\)/);
  assert.match(source, /onHashChange/);
  // The run detail area is reachable by URL only; it never claims a nav group.
  assert.match(source, /name:\s*'Run Detail'[\s\S]*?slug:\s*'runs'/);
  assert.doesNotMatch(source, /labels:\s*\[[^\]]*'Run Detail'/);
});

test('list surfaces link into the durable run view instead of only an inline panel', () => {
  for (const [file, call] of [
    ['WorkflowsPage.tsx', "runHash('job', j.job_id)"],
    ['TrainingPage.tsx', "runHash('training', r.run_id)"],
    ['EvaluationPage.tsx', "runHash('evaluation', r.run_id)"],
  ]) {
    const source = readFileSync(new URL(`../src/pages/${file}`, import.meta.url), 'utf8');
    assert.match(source, /import\s+\{\s*runHash\s*\}\s+from\s+['"]\.\.\/api\/runs['"]/);
    assert.ok(source.includes(call), `${file} must link ${call}`);
  }
});

test('the run view reports recovery blockers instead of implying a resume it cannot perform', () => {
  const source = readFileSync(new URL('../src/pages/RunDetailPage.tsx', import.meta.url), 'utf8');
  assert.match(source, /blocked_by/);
  assert.match(source, /preserves_history/);
  assert.match(source, /resume\?\.checkpoint/);
  assert.match(source, /resume\?\.budget/);
  // Cancellation posts to the existing endpoints and stays requested until acknowledged.
  assert.match(source, /detail\?\.actions\.cancel\.endpoint/);
  assert.match(source, /method:\s*'POST'/);
  assert.match(source, /setCancelRequested\(true\)/);
  assert.match(source, /Requested — not yet acknowledged by the worker/);
  // No invented resume/retry write endpoint.
  assert.doesNotMatch(source, /\/resume\/|\/retry\//);
});

test('the run view keeps polling bounded, visible and non-destructive', () => {
  const source = readFileSync(new URL('../src/pages/RunDetailPage.tsx', import.meta.url), 'utf8');
  assert.match(source, /const POLL_MS = \d+;/);
  assert.match(source, /const MAX_POLL_MS = \d+;/);
  assert.match(source, /document\.visibilityState === 'visible'/);
  assert.match(source, /TERMINAL\.includes\(state/);
  assert.match(source, /setPollMs\(\(value\) => Math\.min\(value \* 2, MAX_POLL_MS\)\)/);
  // Drafts and the selected run survive a failed refresh.
  assert.match(source, /sessionStorage\.setItem\(noteKey\(kind, runId\), value\)/);
  assert.match(source, /if \(quiet && hasDetail\.current\)/);
  assert.match(source, /Last successful update/);
});

test('the job list keeps its filters in the address across back/forward navigation', () => {
  const source = readFileSync(new URL('../src/pages/WorkflowsPage.tsx', import.meta.url), 'utf8');
  assert.match(source, /function filtersFromHash\(\)/);
  assert.match(source, /useState\(filtersFromHash\(\)\.query\)/);
  assert.match(source, /useState\(filtersFromHash\(\)\.status\)/);
  assert.match(source, /const nextHash = `#workflows\$\{search \? `\?\$\{search\}` : ''\}`/);
  assert.match(source, /addEventListener\('hashchange', onHashChange\)/);
});

test('the run view stays usable at narrow widths and exposes attempt history', () => {
  const css = readFileSync(new URL('../src/pages/runs.css', import.meta.url), 'utf8');
  assert.match(css, /@media \(max-width: 900px\)/);
  assert.match(css, /\.runs-page \.runs-states,[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/);
  const source = readFileSync(new URL('../src/pages/RunDetailPage.tsx', import.meta.url), 'utf8');
  assert.match(source, /Load more attempts/);
  assert.match(source, /nextPagePath\(attemptsNext, attemptsPath\(kind, runId\)\)/);
  assert.match(source, /aria-live="polite"/);
});