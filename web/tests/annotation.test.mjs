import test from 'node:test';
import assert from 'node:assert/strict';
import { initialLabel, matchesQueue, nextPending, parseSamples, validLabel, validateSamples } from '../src/api/annotation.ts';

const schema = { kind: 'classification', classes: ['positive', 'negative'] };
const task = (id, review = null, flagged = false) => ({ task_id: id, sample_ref: `sample-${id}`, status: 'pending', needs_adjudication: flagged, assigned_reviewer: '', content: { text: `Source ${id}`, draft_prediction: { predicted_label: 'positive' } }, latest_review: review });

test('another assigned reviewer record does not remove my formal task from pending', () => {
  const formal={...task('pair',{decision:'corrected'}),formal_preference:true,assigned_to_me:true,reviewed_by_me:false};
  assert.equal(matchesQueue(formal,'pending'),true);
  assert.equal(matchesQueue(formal,'reviewed'),false);
  assert.equal(nextPending([task('current'),formal],'current'),'pair');
  assert.equal(matchesQueue({...formal,reviewed_by_me:true},'pending'),false);
  assert.equal(matchesQueue({...formal,assigned_to_me:false},'pending'),false);
});

test('manual/model labels preserve exact text and schema membership', () => {
  assert.equal(initialLabel(task('one')), 'positive');
  assert.equal(initialLabel(task('one', { human_label: { label: 'negative' } })), 'negative');
  assert.equal(initialLabel({ ...task('one'), content: {} }), '');
  assert.equal(validLabel(schema, 'positive'), true);
  for (const value of ['', ' positive ', 'unknown', null, ['positive']]) assert.equal(validLabel(schema, value), false);
  assert.equal(validLabel({kind:'text_generation'}, ' exact\n'), true);
  assert.equal(validLabel({kind:'text_generation'}, ' \n'), false);
  assert.equal(validLabel({kind:'preference_ranking'}, 'abstain'), true);
  assert.equal(validLabel({kind:'ner_span'}, 'text'), false);
});

test('queue filters use review records and flags rather than ambiguous task status', () => {
  const rejected = task('reject', { decision: 'rejected' });
  const skipped = task('skip', { decision: 'skipped' });
  const flagged = task('flag', null, true);
  assert.equal(matchesQueue(rejected, 'pending'), false);
  assert.equal(matchesQueue(rejected, 'reviewed'), true);
  assert.equal(matchesQueue(flagged, 'pending'), false);
  assert.equal(matchesQueue(flagged, 'flagged'), true);
  assert.equal(matchesQueue(skipped, 'skipped'), true);
  assert.equal(matchesQueue(task('ONE'), 'all', ' source one '), true);
  assert.equal(matchesQueue(task('one'), 'all', 'positive'), false, 'hidden predictions must not affect search');
});

test('advancement follows queue order, wraps once and excludes flags and all saved outcomes', () => {
  const rows = [task('1'), task('2', {decision:'skipped'}), task('3', null, true), task('4')];
  assert.equal(nextPending(rows, '1'), '4');
  assert.equal(nextPending(rows, '4'), '1');
  assert.equal(nextPending([task('1')], '1'), null);
  assert.equal(nextPending([task('1', {decision:'corrected'}), task('2',null,true)], '1'), null);
});

test('JSON/JSONL file imports preserve content and report actionable malformed lines', () => {
  const row = { id:'one', text:' exact\ntext ', metadata:{ false:false }, draft_prediction:{predicted_label:'positive',model_version_id:'pinned'} };
  assert.deepEqual(parseSamples('\uFEFF' + JSON.stringify([row])), [row]);
  assert.deepEqual(parseSamples(JSON.stringify(row) + '\r\n\r\n' + JSON.stringify({...row,id:'two'})), [row,{...row,id:'two'}]);
  assert.throws(() => parseSamples(JSON.stringify(row) + '\ninvalid'), /line 2/);
  for (const raw of ['', '[]', '[null]', '[1]', '[[]]', '[{}', 'null']) assert.throws(() => parseSamples(raw));
  assert.throws(() => parseSamples(JSON.stringify(Array(501).fill(row))), /500/);
});

test('additive import validates the entire batch, pinned predictions and protected samples', () => {
  const row = {id:'one',text:'Source',draft_prediction:{predicted_label:'positive',model_version_id:'pinned'}};
  assert.doesNotThrow(() => validateSamples([row],schema,'pinned'));
  assert.doesNotThrow(() => validateSamples([{id:'manual',text:'Source'}],schema,'pinned'), 'model-assisted campaigns retain manual fallback');
  assert.throws(() => validateSamples([row,row],schema,'pinned'), /Duplicate/);
  assert.throws(() => validateSamples([row],schema,null), /pinned/);
  assert.throws(() => validateSamples([row],schema,'different'), /pinned/);
  assert.throws(() => validateSamples([{...row,draft_prediction:{...row.draft_prediction,predicted_label:'unknown'}}],schema,'pinned'), /schema/);
  for (const extra of [{protected:true},{split:'test'},{split:'held_out'},{split:' Validation '},{assigned_split:'test'},{assigned_split:'val'}]) assert.throws(() => validateSamples([{...row,...extra}],schema,'pinned'), /protected/);
  assert.throws(() => validateSamples([row],schema,'pinned',['one']), /protected/);
  for (const id of ['',null,' '.repeat(5),'x'.repeat(129)]) assert.throws(() => validateSamples([{...row,id}],schema,'pinned'), /id/);
  assert.throws(() => validateSamples([],schema,null));
});

test('sources satisfy publication precedence and preferences include both candidates', () => {
  for (const source of [{candidate_a:'A'}, {text:''}, {text:0,prompt:'valid'}, {text:null,input:'valid'}, {text:' ',input:'valid'}]) assert.throws(() => validateSamples([{id:'one',...source}],schema,null), /text, prompt, or input/);
  assert.doesNotThrow(() => validateSamples([{id:'one',prompt:'source'}],schema,null));
  const preference = {kind:'preference_ranking',classes:[]};
  assert.throws(() => validateSamples([{id:'one',prompt:'source',candidate_a:'A'}],preference,null), /both candidate/);
  assert.doesNotThrow(() => validateSamples([{id:'one',prompt:'source',candidate_a:'A',candidate_b:'B'}],preference,null));
  assert.doesNotThrow(() => validateSamples([{id:'one',candidate_a:'A',candidate_b:'B'}],preference,null));
});
