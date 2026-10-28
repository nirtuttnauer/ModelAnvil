import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluationHash, evaluationSelection, nextExperimentAction } from '../src/api/improvement.ts';

const id = '11111111-1111-4111-8111-111111111111';
const training = { run_id: id, status: 'completed', created_at: '2026-10-28T12:00:00Z', output_model_version: 3, base_model_version: 1, guided_evaluation: { eligible: true, reason: '' } };
const evaluation = { run_id: id, candidate_model_version: 3, baseline_model_version: 1, status: 'completed' };

test('experiment resumes from persisted training and paired evaluation states', () => {
  assert.equal(nextExperimentAction([], []).stage, 'Prepare');
  assert.equal(nextExperimentAction([{ ...training, status: 'running' }], []).stage, 'Train');
  assert.match(nextExperimentAction([{ ...training, status: 'failed' }], []).label, /recovery/);
  assert.equal(nextExperimentAction([training], []).href, evaluationHash(id));
  assert.equal(nextExperimentAction([training], [evaluation]).stage, 'Decide');
  assert.equal(nextExperimentAction([training], [{ ...evaluation, improvement_decision: { outcome: 'accept' } }]).stage, 'Export');
  assert.equal(nextExperimentAction([training], [{ ...evaluation, improvement_decision: { outcome: 'reject' } }]).stage, 'Improve');
});

test('unrelated evaluations and lower training loss cannot complete the improvement journey', () => {
  assert.equal(nextExperimentAction([training], [{ ...evaluation, baseline_model_version: 2 }]).stage, 'Compare');
  assert.equal(nextExperimentAction([{ ...training, output_model_version: null }], [evaluation]).stage, 'Train');
  assert.equal(nextExperimentAction([{ ...training, created_at: '2026-10-27' }, { ...training, run_id: 'new', status: 'running' }], [evaluation]).stage, 'Train');
  assert.match(nextExperimentAction([training], [{ ...evaluation, status: 'pending', job: 'job' }]).href, /runs\/evaluation/);
  assert.equal(nextExperimentAction([{ ...training, guided_evaluation: { eligible: false, reason: 'Unsupported adapter' } }], []).href, '#evaluation');
});

test('evaluation routes retain exact identities and refuse malformed handoffs', () => {
  assert.deepEqual(evaluationSelection(evaluationHash(id)), { trainingRun: id, evaluationRun: '', suiteVersion: '' });
  assert.equal(evaluationSelection(`#evaluation?run=${id}`).evaluationRun, id);
  assert.equal(evaluationSelection(`#evaluation?training_run=${id}&suite_version=${id}`).suiteVersion, id);
  assert.deepEqual(evaluationSelection('#evaluation?training_run=../../secrets&run=invalid'), { trainingRun: '', evaluationRun: '', suiteVersion: '' });
});
