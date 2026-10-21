import { guidedPlan, readGuidedValue, type GuidedInputs, type GuidedRevision } from './guided-training.ts';

export const trainingDefaults = {
  showForm: false, mode: 'worker', recipe: 'full_sft', runner: '', tokenizer: '', base: '',
  selectedDataset: '', selectedPool: '', selectedPolicy: '', seed: '42', steps: '50',
  learningRate: '', validationInterval: '0', pilotSteps: '3', comparisonIds: '',
  preset: 'recommended', guidedStage: 0, modelName: '', name: '', revisionJson: '', resumeJson: '',
  currentRunId: '', project: '', launchKey: '', launchInputs: '',
  columnMappingJson: '{"mode":"auto"}',
};
export type TrainingConfiguration = typeof trainingDefaults;
export const legacyGuidedDefaults = {
  stage: 0, steps: 3, preset: 'recommended', modelName: '', name: '', inputsJson: '',
  revisionJson: '', resumeJson: '', runId: '', launchKey: '',
};

export function preparedTrainingFields(inputs: GuidedInputs, modelName: string) {
  return { mode: inputs.execution_mode, recipe: inputs.recipe_type, base: String(inputs.base_model_version),
    tokenizer: String(inputs.tokenizer_version), runner: String(inputs.runner_manifest),
    selectedPool: String(inputs.pool), selectedPolicy: inputs.budget_policy_id,
    seed: String(inputs.initialization_seed), project: inputs.project || '', modelName, learningRate: '', validationInterval: '0' };
}

export function migrateGuidedTraining(legacy: typeof legacyGuidedDefaults): TrainingConfiguration {
  const inputs = readGuidedValue<GuidedInputs>(legacy.inputsJson);
  const revision = readGuidedValue<GuidedRevision>(legacy.revisionJson);
  const config = { ...trainingDefaults, ...(inputs ? preparedTrainingFields(inputs, legacy.modelName) : {}),
    steps: String(legacy.steps), preset: legacy.preset, guidedStage: Math.min(2, legacy.stage),
    name: legacy.name, revisionJson: legacy.revisionJson, resumeJson: legacy.resumeJson,
    selectedDataset: revision ? String(revision.id) : '', currentRunId: legacy.runId };
  if (legacy.launchKey && !legacy.runId && inputs && revision) {
    config.launchKey = legacy.launchKey;
    config.launchInputs = JSON.stringify(trainingLaunchPayload(config, trainingStepCount(config, revision), false));
  }
  return config;
}

export function trainingLaunchPayload(config: TrainingConfiguration, steps: number, referenceRuntime: boolean): Record<string, unknown> {
  return {
    execution_mode: config.mode, recipe_type: config.recipe,
    ...(config.tokenizer ? { tokenizer_version: Number(config.tokenizer) } : {}),
    ...(config.recipe === 'scratch_pretraining' ? { base_model_version: null } : config.base ? { base_model_version: Number(config.base) } : {}),
    initialization_seed: Number(config.seed), total_steps: steps,
    ...(config.mode === 'worker' && referenceRuntime ? { hyperparameters: {
      ...(config.learningRate ? { learning_rate: Number(config.learningRate) } : {}), validation_interval: Number(config.validationInterval),
    } } : {}),
    ...(config.selectedDataset ? { dataset_revision: Number(config.selectedDataset) } : {}),
    ...(config.mode === 'worker' && config.selectedPool ? { pool: Number(config.selectedPool) } : {}),
    ...(config.mode === 'worker' && config.selectedPolicy ? { budget_policy_id: config.selectedPolicy } : {}),
    ...(config.mode === 'worker' && config.runner ? { runner_manifest: Number(config.runner) } : {}),
    ...(config.project ? { project: config.project } : {}),
  };
}

export function trainingStepCount(config: TrainingConfiguration, revision: GuidedRevision | null): number {
  if (config.preset === 'quick') return 3;
  if (config.preset === 'recommended') return guidedPlan(revision, config.recipe === 'lora_adapter').steps;
  return Number(config.steps);
}

export type TrainingTab = 'configure' | 'current-run' | 'history';
export function trainingTab(hash: string): TrainingTab {
  const tab = new URLSearchParams(hash.split('?')[1]).get('tab');
  return tab === 'current-run' || tab === 'history' ? tab : 'configure';
}

export function latestTrainingRun<T extends { run_id: string; status: string; created_at: string }>(runs: T[], id: string): T | undefined {
  if (id) return runs.find(run => run.run_id === id);
  const sorted = [...runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  return sorted.find(run => ['pending', 'running'].includes(run.status)) ?? sorted[0];
}
