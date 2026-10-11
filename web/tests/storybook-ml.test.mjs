import test from 'node:test';
import assert from 'node:assert/strict';
import { mlResponses, mlActions, resetMlFixtures } from '../src/stories/ml-fixtures.ts';

test('ML stories provide finite recorded measurements and explicit fixture evidence', () => {
  resetMlFixtures();
  for (const run of mlResponses['/api/v1/training-runs/']) {
    assert.match(run.execution_evidence.source, /fictional demo/);
    assert.equal(run.execution_evidence.level, 'fixture');
    assert.ok(run.current_step >= 0 && run.current_step <= run.total_steps);
    assert.ok(run.latest_loss === null || Number.isFinite(run.latest_loss));
    for (const metric of run.metrics_log) {
      assert.ok(Number.isFinite(metric.step) && metric.step >= 0);
      assert.ok(Number.isFinite(metric.loss));
    }
  }
  for (const run of mlResponses['/api/v1/alignment-runs/']) {
    assert.equal(run.execution_evidence.level, 'fixture');
    for (const value of Object.values(run.latest_metrics)) assert.ok(Number.isFinite(value));
  }
});

test('evaluation intervals contain finite metrics, and loaded cases belong to their suite slices', () => {
  resetMlFixtures();
  for (const run of mlResponses['/api/v1/evaluation-runs/']) {
    assert.equal(run.execution_evidence.level, 'fixture');
    for (const metric of run.metrics) {
      assert.ok(Number.isFinite(metric.value));
      assert.ok(Number.isInteger(metric.sample_count) && metric.sample_count > 0);
      const bounds = metric.uncertainty_interval;
      if (bounds) {
        assert.ok(Number.isFinite(bounds.lower) && Number.isFinite(bounds.upper));
        assert.ok(bounds.lower <= metric.value && metric.value <= bounds.upper);
      }
    }
    const cases = mlResponses[`/api/v1/evaluation-runs/${run.run_id}/cases/`];
    assert.ok(Array.isArray(cases));
    const slices = new Set(run.metrics.map(metric => metric.slice_name));
    for (const result of cases) {
      assert.ok(slices.has(result.slice_name));
      assert.equal(typeof result.passed, 'boolean');
      assert.ok(result.score === null || Number.isFinite(result.score));
    }
  }
});

test('reset removes demo writes and restores deterministic registration and launch actions', () => {
  resetMlFixtures();
  const baseline = structuredClone(mlResponses);
  const initialActionPaths = Object.keys(mlActions);
  const model = mlActions['/api/v1/models/']({ name: 'Temporary demo model' });
  const tokenizer = mlActions['/api/v1/tokenizers/']({ name: 'Temporary demo tokenizer' });
  const version = mlActions['/api/v1/model-versions/']({ model: model.id });
  assert.equal(version.model_name, 'Temporary demo model');
  const training = mlActions['/api/v1/training-runs/']({ total_steps: 25 });
  const evaluation = mlActions['/api/v1/evaluation-runs/']({ suite_version: 1 });
  mlActions['/api/v1/alignment-runs/']({ algorithm: 'dpo' });
  assert.equal(training.status, 'pending');
  assert.deepEqual(training.metrics_log, []);
  assert.equal(training.latest_loss, null);
  assert.deepEqual(evaluation.metrics, []);
  assert.ok(mlResponses['/api/v1/models/'].some(row => row.model_id === model.model_id));
  assert.ok(mlResponses['/api/v1/tokenizers/'].some(row => row.tokenizer_id === tokenizer.tokenizer_id));
  mlResponses['/api/v1/temporary-demo/'] = { stale: true };
  mlActions['/api/v1/temporary-demo/'] = () => ({ stale: true });
  resetMlFixtures();
  assert.deepEqual(mlResponses, baseline);
  assert.deepEqual(Object.keys(mlActions), initialActionPaths);
  const repeatedModel = mlActions['/api/v1/models/']({ name: 'Temporary demo model' });
  assert.deepEqual(repeatedModel, model);
  assert.deepEqual(mlActions['/api/v1/tokenizers/']({ name: 'Temporary demo tokenizer' }), tokenizer);
  assert.deepEqual(mlActions['/api/v1/model-versions/']({ model: repeatedModel.id }), version);
  assert.deepEqual(mlActions['/api/v1/training-runs/']({ total_steps: 25 }), training);
  resetMlFixtures();
});

test('reset restores model registration dependencies and preflight after nested edits', () => {
  resetMlFixtures();
  const baseline = structuredClone(mlResponses);
  mlResponses['/api/v1/models/'][0].name = 'Changed nested demo name';
  mlResponses['/api/v1/training-runs/preflight/'].budget.remaining = '0';
  mlResponses['/api/v1/training-runs/'][0].metrics_log[0].loss = 999;
  mlResponses['/api/v1/training-runs/'][0].execution_evidence.level = 'production';
  mlResponses['/api/v1/training-runs/preflight/'].temporary = 'must be removed';
  resetMlFixtures();
  assert.deepEqual(mlResponses, baseline);
  const preflight = mlActions['/api/v1/training-runs/preflight/']({ total_steps: 75 });
  assert.equal(preflight.budget.requested, 75);
  assert.equal(preflight.temporary, undefined);
  assert.equal(mlActions['/api/v1/training-runs/']({ total_steps: 20 }).execution_evidence.level, 'fixture');
  assert.equal(preflight.budget.remaining, baseline['/api/v1/training-runs/preflight/'].budget.remaining);
  const running = baseline['/api/v1/training-runs/'][1];
  const cancelled = mlActions[`/api/v1/training-runs/${running.run_id}/cancel/`]({});
  assert.deepEqual(cancelled.metrics_log, running.metrics_log);
  assert.equal(cancelled.status, 'cancelled');
  const version = mlActions['/api/v1/model-versions/']({ model: 1 });
  assert.equal(version.model_name, baseline['/api/v1/models/'][0].name);
  resetMlFixtures();
});


test('CPU registration and evaluation demo actions stay fictional and reset dynamic routes', () => {
  resetMlFixtures();
  const baseline = structuredClone(mlResponses);
  const actionPaths = Object.keys(mlActions);
  const base = mlActions['/api/v1/model-versions/initialize-cpu/']({ name: 'Demo CPU' });
  assert.equal(base.execution_evidence.level, 'fixture');
  assert.equal(base.model_version.state, 'draft');
  const suite = mlActions['/api/v1/evaluation-suites/register-cpu/']({ name: 'Demo checks', cases: [{ case_id: 'x', input_prompt: 'a', expected_output: 'b' }] });
  assert.equal(suite.cases_count, 1);
  const run = mlActions['/api/v1/evaluation-runs/']({ suite_version: suite.id, candidate_model_version: base.model_version.id });
  const completed = mlActions[`/api/v1/evaluation-runs/${run.run_id}/execute/`]({ max_tokens: 4 });
  assert.equal(completed.status, 'completed');
  assert.equal(completed.execution_evidence.level, 'fixture');
  assert.match(completed.execution_evidence.source, /No model was executed/);
  assert.deepEqual(mlResponses[`/api/v1/evaluation-runs/${run.run_id}/cases/`].map(c => c.case_id), ['x']);
  assert.equal(completed.metrics[0].sample_count, 1);
  resetMlFixtures();
  assert.deepEqual(mlResponses, baseline);
  assert.deepEqual(Object.keys(mlActions), actionPaths);
});

test('alignment demo registration, execution, cancellation and reset stay isolated and explicitly fictional', () => {
  resetMlFixtures();
  const baseline = structuredClone(mlResponses);
  const actionPaths = Object.keys(mlActions);
  const artifact = mlActions['/api/v1/alignment-runs/register-preferences/']({ name: 'Temporary pairs', samples: [{ prompt: 'Say a', chosen: 'a', rejected: 'b' }] });
  assert.equal(artifact.row_count, 1);
  assert.ok(mlResponses['/api/v1/alignment-runs/preference-artifacts/'].some(a => a.artifact_id === artifact.artifact_id));
  const run = mlActions['/api/v1/alignment-runs/']({ algorithm: 'dpo', total_steps: 4, train_dataset_artifact: artifact.artifact_id, held_out_dataset_artifact: '80000000-0000-4000-8000-000000000002' });
  assert.equal(run.execution_capabilities.can_execute, true);
  const completed = mlActions[`/api/v1/alignment-runs/${run.run_id}/execute/`]({});
  assert.equal(completed.status, 'completed');
  assert.equal(completed.current_step, 4);
  assert.equal(completed.execution_evidence.level, 'fixture');
  assert.equal(completed.execution_pins.demo_only, true);
  assert.equal(completed.metrics_history.length, 4);
  assert.ok(mlResponses['/api/v1/model-versions/'].some(v => v.id === completed.output_model_version));
  assert.deepEqual(mlActions[`/api/v1/alignment-runs/${run.run_id}/execute/`]({}), completed);
  const active = mlResponses['/api/v1/alignment-runs/'].find(r => r.status === 'running');
  const cancelled = mlActions[`/api/v1/alignment-runs/${active.run_id}/cancel/`]({});
  assert.equal(cancelled.status, 'cancelled');
  assert.equal(cancelled.current_step, active.current_step);
  assert.deepEqual(cancelled.latest_metrics, active.latest_metrics);
  resetMlFixtures();
  assert.deepEqual(mlResponses, baseline);
  assert.deepEqual(Object.keys(mlActions), actionPaths);
});
