// Isolated LiveServer acceptance: actual frontend client, real HTTP, no credential logging.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { apiRequest, apiPage, ApiRequestError, setActiveProjectId } from '../web/src/api/client.ts';

try {
  const input = JSON.parse(readFileSync(0, 'utf8'));
  const base = new URL(input.base);
  assert.equal(base.hostname, '127.0.0.1');
  assert.equal(base.protocol, 'http:');
  globalThis.window = { location: { origin: base.origin } };
  setActiveProjectId(input.project || null);
  const nativeFetch = globalThis.fetch;
  globalThis.fetch = (path, init) => {
    const url = new URL(path, base);
    assert.equal(url.origin, base.origin);
    assert.ok(url.pathname.startsWith('/api/v1/'));
    return nativeFetch(url, { ...init, signal: AbortSignal.timeout(10000) });
  };
  const get = path => apiRequest(path, input.token);
  const post = (path, body) => apiRequest(path, input.token, { method: 'POST', body: JSON.stringify(body) });
  if (input.mode === 'bank') {
    const source = '/api/v1/dataset-bank/sources/svg-lucide/';
    if (input.refused) {
      await assert.rejects(post(source + 'acquisitions/', {}), error => error instanceof ApiRequestError && error.status === 400);
      console.log(JSON.stringify({ state: 'refused' }));
    } else if (input.snapshot) {
      const state = await get(`/api/v1/dataset-bank/acquisitions/${input.snapshot}/`);
      assert.equal(state.state, 'ready');
      assert.equal(state.verified_records, input.records);
      assert.equal(state.budget_reservation.state, 'settled');
      const revisions = await apiPage('/api/v1/dataset-revisions/', input.token);
      const revision = revisions.results.find(row => row.revision_id === state.revision_id);
      assert.equal(revision.state, 'published');
      assert.equal(revision.metadata.split_counts.train + revision.metadata.split_counts.validation + revision.metadata.split_counts.test, state.row_count);
      console.log(JSON.stringify({ state: state.state, revision_id: state.revision_id, row_count: state.row_count }));
    } else {
      await post(source + 'preflight/', {});
      const body = { budget_policy_id: input.policy, estimated_amount: String(input.records), record_limit: input.records };
      const state = await post(source + 'acquisitions/', body);
      assert.equal(state.state, 'ingesting');
      const path = `/api/v1/dataset-bank/acquisitions/${state.snapshot_id}/`;
      const cancelled = await post(path + 'cancel/', {});
      assert.equal(cancelled.state, 'cancelled');
      assert.equal(cancelled.budget_reservation.state, 'released');
      const resumed = await post(path + 'resume/', { budget_policy_id: input.policy, estimated_amount: String(input.records) });
      assert.equal(resumed.job.status, 'queued');
      assert.equal(resumed.budget_reservation.state, 'reserved');
      console.log(JSON.stringify({ snapshot_id: resumed.snapshot_id, state: resumed.state }));
    }
  } else {
    const campaign = await post('/api/v1/labeling-campaigns/', {
      name: 'HTTP human review', kind: 'classification', classes: ['positive', 'negative'],
      guidelines: 'Review the supplied text', seed_mode: 'manual', max_cycles: 1,
      budget_limit_dollars: 100, audit_sample_refs: ['protected-audit'],
    });
    const campaignPath = `/api/v1/labeling-campaigns/${campaign.campaign_id}/`;
    await assert.rejects(post(campaignPath + 'batches/', { samples: [{ id: 'protected-audit', text: 'Protected evidence' }] }), error => error.status === 400);
    const batch = await post(campaignPath + 'batches/', { samples: [{ id: 'human-1', text: 'Useful response' }, { id: 'human-2', text: 'Unreadable response' }] });
    const tasks = await apiPage(`/api/v1/labeling-batches/${batch.batch_id}/tasks/`, input.token);
    for (const task of tasks.results) {
      const path = `/api/v1/annotation-tasks/${task.task_id}/`;
      const decision = task.sample_ref === 'human-1' ? 'corrected' : 'skipped';
      const revision = (task.latest_review?.revision_no || 0) + 1;
      await post(path + 'review/', { decision, human_label: decision === 'skipped' ? {} : { label: 'positive' }, expected_revision: revision });
      await assert.rejects(post(path + 'review/', { decision: 'corrected', human_label: { label: 'negative' }, expected_revision: revision }), error => error.status === 409);
      const history = await apiPage(path + 'history/', input.token);
      assert.equal(history.results.length, 1);
    }
    const snapshot = await post(`/api/v1/labeling-batches/${batch.batch_id}/close/`, {});
    const exported = await get(`/api/v1/annotation-snapshots/${snapshot.snapshot_id}/export/`);
    assert.equal(exported.items.length, 1);
    assert.equal(exported.items[0].sample_ref, 'human-1');
    assert.match(exported.manifest_digest, /^[a-f0-9]{64}$/);
    assert.equal((await get(campaignPath)).status, 'completed');
    console.log(JSON.stringify({ state: 'completed', item_count: exported.items.length, snapshot_id: snapshot.snapshot_id }));
  }
} catch {
  // Assertion failures can contain raw data. Keep credentials and source content out of logs.
  console.error('Data workflow HTTP acceptance failed.');
  process.exitCode = 1;
}
