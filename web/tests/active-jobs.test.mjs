import test from 'node:test';
import assert from 'node:assert/strict';
import { activeJobDisplayName, loadActiveJobs } from '../src/api/active-jobs.ts';

test('managed training labels stay readable while custom job names remain intact', () => {
  const id = 'c67e2e82-4a2d-425f-8524-f42c9d841be3';
  for (const recipe of ['full_sft', 'lora_adapter', 'scratch_pretraining']) {
    assert.equal(activeJobDisplayName(`${recipe}: ${id}`), 'Model training · c67e2e82');
  }
  assert.equal(activeJobDisplayName('Juniper support training'), 'Juniper support training');
  assert.equal(activeJobDisplayName('lora_adapter: custom training'), 'lora_adapter: custom training');
  assert.equal(activeJobDisplayName(''), 'Untitled job');
});

test('active jobs include every page, exclude terminal work, and use only the latest attempt progress', async () => {
  const original = globalThis.fetch, calls = [];
  const job = (job_id, status, created_at = '2026-10-15T10:00:00Z') => ({ job_id, status, name: job_id, created_at, desired_action: 'run' });
  globalThis.fetch = async input => {
    calls.push(String(input)); const url = new URL(input, 'http://localhost');
    if (url.pathname.endsWith('/jobs/')) return Response.json(url.search ? {
      results: [job('running', 'running'), job('stale', 'running'), job('cancelled', 'cancelled')], next: null,
    } : { results: [job('queued', 'queued'), job('done', 'succeeded'), job('failed', 'failed')], next: '/api/v1/jobs/?cursor=next' });
    return Response.json({ results: url.searchParams.get('job_id') === 'running'
      ? [{ job_id: 'unrelated', status: 'running', progress: 1 }, { job_id: 'running', status: 'running', progress: 0.42 }]
      : [{ job_id: 'stale', status: 'failed', progress: 0.8 }, { job_id: 'stale', status: 'running', progress: 0.4 }], next: null });
  };
  try {
    const jobs = await loadActiveJobs('test-key');
    assert.deepEqual(jobs.map(job => [job.job_id, job.progress]), [['running', 42], ['stale', null], ['queued', null]]);
    assert.equal(calls.length, 4);
  } finally { globalThis.fetch = original; }
});

test('missing progress keeps active work visible, while a failed job list remains an error', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async input => String(input).includes('/job-attempts/') ? new Response('', { status: 503 }) : Response.json({
    results: [{ job_id: 'active', status: 'running', name: 'Training', created_at: '2026-10-15T10:00:00Z' }], next: null,
  });
  try {
    assert.equal((await loadActiveJobs('test-key'))[0].progress, null);
    globalThis.fetch = async () => new Response('', { status: 503 });
    await assert.rejects(loadActiveJobs('test-key'));
  } finally { globalThis.fetch = original; }
});
