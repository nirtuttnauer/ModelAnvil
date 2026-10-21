import test from 'node:test';
import assert from 'node:assert/strict';
import { trainingDefaults, legacyGuidedDefaults, preparedTrainingFields, migrateGuidedTraining, trainingStepCount, trainingLaunchPayload, trainingTab, latestTrainingRun } from '../src/api/training-workspace.ts';

const inputs = { execution_mode: 'worker', recipe_type: 'lora_adapter', base_model_version: 3, tokenizer_version: 4,
  runner_manifest: 5, pool: 6, budget_policy_id: 'training-policy', initialization_seed: 42 };
const revision = { id: 7, dataset_name: 'Support', row_count: 60, metadata: { split_counts: { train: 48, validation: 6, test: 6 } } };

test('recommended setup fills the exact configuration edited by advanced controls', () => {
  assert.equal(trainingDefaults.preset, 'recommended');
  assert.equal(trainingStepCount(trainingDefaults, null), 0);
  const config = { ...trainingDefaults, ...preparedTrainingFields(inputs, 'Local model'), selectedDataset: '7' };
  assert.equal(config.base, '3'); assert.equal(config.tokenizer, '4'); assert.equal(config.runner, '5');
  assert.equal(config.selectedPool, '6'); assert.equal(config.selectedPolicy, 'training-policy');
  assert.equal(trainingStepCount(config, revision), 288);
  assert.equal(trainingStepCount({ ...config, recipe: 'full_sft' }, revision), 144);
  assert.equal(trainingStepCount({ ...config, preset: 'quick' }, revision), 3);
  assert.equal(trainingStepCount({ ...config, preset: 'custom', steps: '2400' }, revision), 2400);
  assert.equal(trainingStepCount({ ...config, preset: 'recommended' }, null), 0);
});

test('old guided drafts preserve pinned resources, upload state and the monitored run', () => {
  const config = migrateGuidedTraining({ ...legacyGuidedDefaults, inputsJson: JSON.stringify(inputs), revisionJson: JSON.stringify(revision),
    stage: 3, runId: 'saved-run', modelName: 'Local model', name: 'Support', resumeJson: '{"upload":"saved"}', preset: 'custom', steps: 99 });
  assert.equal(config.currentRunId, 'saved-run'); assert.equal(config.guidedStage, 2);
  assert.equal(config.base, '3'); assert.equal(config.selectedDataset, '7'); assert.equal(config.steps, '99');
  assert.equal(config.resumeJson, '{"upload":"saved"}'); assert.equal(config.revisionJson, JSON.stringify(revision));
  assert.equal('preflight_token' in config, false);
  assert.equal(migrateGuidedTraining({ ...legacyGuidedDefaults, inputsJson: '{broken' }).base, '');
});

test('current run chooses the newest active run and never substitutes a missing pinned run', () => {
  const runs = [
    { run_id: 'old', status: 'running', created_at: '2026-10-12T10:00:00Z' },
    { run_id: 'completed', status: 'completed', created_at: '2026-10-14T11:00:00Z' },
    { run_id: 'new', status: 'pending', created_at: '2026-10-14T10:00:00Z' },
  ];
  assert.equal(latestTrainingRun(runs, '').run_id, 'new');
  assert.equal(latestTrainingRun(runs, 'completed').run_id, 'completed');
  assert.equal(latestTrainingRun(runs, 'missing'), undefined);
  assert.equal(latestTrainingRun(runs.filter(run => run.status === 'completed'), '').run_id, 'completed');
  assert.equal(latestTrainingRun([], ''), undefined);
  assert.deepEqual(runs.map(run => run.run_id), ['old', 'completed', 'new']);
});

test('training tabs survive shared URLs and reject unknown tab names', () => {
  assert.equal(trainingTab('#training?tab=current-run&run=saved-run'), 'current-run');
  assert.equal(trainingTab('#training?tab=history'), 'history');
  assert.equal(trainingTab('#training?tab=unknown'), 'configure');
  assert.equal(trainingTab('#training'), 'configure');
});

test('shared launch pins exactly the selected inputs and preserves an uncertain guided launch identity', () => {
  const config = migrateGuidedTraining({ ...legacyGuidedDefaults, inputsJson: JSON.stringify({ ...inputs, project: 'project-id' }),
    revisionJson: JSON.stringify(revision), preset: 'custom', steps: 2400, launchKey: 'uncertain-launch' });
  const payload = trainingLaunchPayload(config, 2400, false);
  assert.deepEqual(payload, { ...inputs, project: 'project-id', dataset_revision: 7, total_steps: 2400 });
  assert.equal(config.launchKey, 'uncertain-launch');
  assert.equal(config.launchInputs, JSON.stringify(payload));
  assert.equal(config.launchInputs.includes('preflight_token'), false);
  assert.deepEqual(trainingLaunchPayload({ ...config, learningRate: '0.01', validationInterval: '10' }, 99, true).hyperparameters,
    { learning_rate: 0.01, validation_interval: 10 });
  const fixture = trainingLaunchPayload({ ...config, mode: 'simulation', recipe: 'scratch_pretraining' }, 10, false);
  assert.equal(fixture.base_model_version, null);
  for (const field of ['pool', 'runner_manifest', 'budget_policy_id']) assert.equal(field in fixture, false);
});
