import test from 'node:test';
import assert from 'node:assert/strict';
import { alignmentFields, evaluationFields, objectInput, preferenceFields, readFieldState, recordsInput, sampleFields, spanFields, structuredInput, writeFieldState } from '../src/components/form-data.ts';

test('field builders round-trip legacy drafts, nested lists, false, zero, null, whitespace, and exact numbers', () => {
  const legacy = '{"text":"  exact text\\n","zero":0,"enabled":false,"missing":null,"nested":{"values":[true,0,"",{"rate":0.8400000000000001}]},"__proto__":{"safe":true}}';
  const state = readFieldState(legacy);
  assert.deepEqual(objectInput(writeFieldState(state)), JSON.parse(legacy));
  assert.equal(Object.getPrototypeOf(objectInput(writeFieldState(state))), Object.prototype);
  assert.equal({}.safe, undefined);
  assert.deepEqual(structuredInput(writeFieldState(readFieldState('[1,{"enabled":false}]'))), [1, { enabled: false }]);
});

test('incomplete numeric fields and duplicate names never become a valid payload', () => {
  const state = readFieldState('{"count":1}');
  for (const text of ['', ' ', 'Infinity', 'NaN']) {
    state.fields[0].text = text;
    assert.throws(() => objectInput(writeFieldState(state)), /finite number/);
  }
  state.fields[0].text = '0';
  assert.deepEqual(objectInput(writeFieldState(state)), { count: 0 });
  state.fields.push({ ...state.fields[0], id: 'duplicate' });
  assert.throws(() => objectInput(writeFieldState(state)), /unique/);
  state.fields[1].name = '';
  assert.throws(() => objectInput(writeFieldState(state)), /needs a name/);
  for (const raw of ['invalid', 'null', '42', 'form-fields-v1:{"kind":"object","fields":[{}]}']) assert.throws(() => objectInput(raw));
  assert.throws(() => objectInput('invalid'), /Clear saved fields/);
  assert.throws(() => objectInput('[]'), /named fields/);
});

test('evaluation cases preserve empty outputs and whitespace while rejecting duplicate IDs and limits', () => {
  const row = { case_id: 'case-1', input_prompt: ' x\n', expected_output: '', slice: 'all', source: { pinned: true } };
  assert.deepEqual(recordsInput(JSON.stringify([row]), evaluationFields, 64, 'case_id'), [row]);
  for (const rows of [[], [row, row], [{ ...row, case_id: ' ' }], [{ ...row, input_prompt: 'x'.repeat(1025) }], Array.from({ length: 65 }, (_, i) => ({ ...row, case_id: String(i) }))]) assert.throws(() => recordsInput(JSON.stringify(rows), evaluationFields, 64, 'case_id'));
});

test('preference responses, imported predictions, and numeric annotation spans serialize to API values', () => {
  const pair = { prompt: 'Say a', chosen: ' a ', rejected: 'b' };
  assert.deepEqual(recordsInput(JSON.stringify([pair]), preferenceFields, 32), [pair]);
  const prediction = writeFieldState(readFieldState('{"predicted_label":"Helpful","model_version_id":"pinned"}'));
  const [sample] = recordsInput(JSON.stringify([{ id: 'one', text: 'source', draft_prediction: prediction }]), sampleFields, 500, 'id');
  assert.deepEqual(sample.draft_prediction, { predicted_label: 'Helpful', model_version_id: 'pinned' });
  const [span] = recordsInput('[{"start":"0","end":"4","label":"Person"}]', spanFields, Infinity);
  assert.deepEqual(span, { start: 0, end: 4, label: 'Person' });
  for (const start of ['', '-1', '0.5', 'NaN', false]) assert.throws(() => recordsInput(JSON.stringify([{ start, end: '4', label: 'Person' }]), spanFields, Infinity));
  assert.deepEqual(alignmentFields('dpo').map(field => field.key), ['learning_rate', 'max_gradient_norm', 'beta']);
  assert.equal(alignmentFields('reward_model').some(field => field.key === 'beta'), false);
});
