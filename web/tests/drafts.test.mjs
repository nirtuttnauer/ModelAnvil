import test from 'node:test';
import assert from 'node:assert/strict';
import { draftKey, readDraft, writeDraft, pruneDrafts, DRAFT_TTL_MS } from '../src/api/drafts.ts';

function storage() {
  const data = new Map();
  return { get length() { return data.size; }, key: i => [...data.keys()][i] ?? null,
    getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
}
test('draft restores only the exact organization, project, form and resource without execution approvals', () => {
  const s = storage(), defaults = { steps: '50', recipe: 'sft' }, key = draftKey('org', 'project', 'training', 'new');
  writeDraft(s, key, { steps: '73', recipe: 'lora', preflight_token: 'never-save', arbitrary: 'discard' }, defaults, 10);
  assert.deepEqual(readDraft(s, key, defaults, 20), { steps: '73', recipe: 'lora' });
  assert.equal(s.getItem(key).includes('never-save'), false);
  for (const args of [['other', 'project', 'training', 'new'], ['org', 'other', 'training', 'new'], ['org', 'project', 'chat', 'new'], ['org', 'project', 'training', 'other']]) assert.equal(readDraft(s, draftKey(...args), defaults, 20), null);
  s.removeItem(key); assert.equal(readDraft(s, key, defaults, 20), null);
});
test('expired, malformed and incompatible drafts are removed; unrelated browser storage remains', () => {
  const s = storage(), key = draftKey('org', null, 'chat');
  s.setItem('other-app', 'leave alone');
  writeDraft(s, key, { prompt: 'private text' }, { prompt: '' }, 0);
  assert.equal(readDraft(s, key, { prompt: '' }, DRAFT_TTL_MS), null);
  for (const raw of ['{', JSON.stringify({ expiresAt: 100, values: { prompt: 3 } }), JSON.stringify({ expiresAt: Infinity, values: {} })]) {
    s.setItem(key, raw); assert.equal(readDraft(s, key, { prompt: '' }, 10), null); assert.equal(s.getItem(key), null);
  }
  writeDraft(s, key, { prompt: 'expires' }, { prompt: '' }, 0); pruneDrafts(s, DRAFT_TTL_MS);
  assert.equal(s.getItem(key), null); assert.equal(s.getItem('other-app'), 'leave alone');
});
test('credential fields, nonfinite numbers and oversized drafts are rejected before writing', () => {
  const s = storage(), key = draftKey('org', 'project', 'form');
  assert.throws(() => writeDraft(s, key, { apiKey: 'secret' }, { apiKey: '' }), /Credentials/);
  assert.throws(() => writeDraft(s, key, { amount: NaN }, { amount: 0 }), /Invalid/);
  assert.throws(() => writeDraft(s, key, { text: 'a'.repeat(1_000_001) }, { text: '' }), /limit/);
  assert.equal(s.length, 0);
});
