import test from 'node:test';
import assert from 'node:assert/strict';
import { apiRequest, getActiveProjectId, setActiveProjectId } from '../src/api/client.ts';

test('organization compute omits project headers without changing task-job scope or credentials', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (path, init) => { calls.push({ path, headers: init.headers }); return new Response('{}', { status: 200 }); };
  try {
    setActiveProjectId('selected-project');
    await apiRequest('/api/v1/compute-allocations/', 'organization-key', { headers: { 'X-Project-ID': 'explicit-project', 'X-Project': 'alias' } }, 'organization');
    assert.equal(calls[0].headers.has('X-Project-ID'), false);
    assert.equal(calls[0].headers.has('X-Project'), false);
    assert.equal(calls[0].headers.get('Authorization'), 'Bearer organization-key');
    assert.equal(getActiveProjectId(), 'selected-project');
    await apiRequest('/api/v1/jobs/', 'organization-key');
    assert.equal(calls[1].headers.get('X-Project-ID'), 'selected-project');
  } finally { globalThis.fetch = originalFetch; setActiveProjectId(null); }
});
