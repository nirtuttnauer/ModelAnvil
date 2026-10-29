import { runHash } from './runs.ts';

export interface ImprovementTraining {
  run_id: string; status: string; created_at?: string; output_model_version?: number | null;
  base_model_version?: number | null;
  guided_evaluation?: { eligible: boolean; reason: string };
}
export interface ImprovementEvaluation {
  run_id: string; status: string; created_at?: string; candidate_model_version: number;
  baseline_model_version?: number | null; job?: string | null;
  improvement_decision?: { outcome: 'accept' | 'reject' } | null;
}

export interface OverviewEvaluation extends ImprovementEvaluation {
  execution_evidence?: { level: string; source: string };
  metrics: { key: string; value: number; sample_count: number; slice_name: string }[];
}

export function evaluationHash(trainingRun: string): string {
  return `#evaluation?training_run=${encodeURIComponent(trainingRun)}`;
}

export function evaluationSelection(hash: string): { trainingRun: string; evaluationRun: string; suiteVersion: string } {
  const query = new URLSearchParams(hash.split('?')[1]);
  const identifier = (key: string) => {
    const value = query.get(key) || '';
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) ? value : '';
  };
  return { trainingRun: identifier('training_run'), evaluationRun: identifier('run'), suiteVersion: identifier('suite_version') };
}

export interface ExperimentAction { title: string; description: string; label: string; href: string; stage: string }
const newest = <T extends { created_at?: string }>(items: T[]) => [...items].sort((a, b) =>
  (Date.parse(b.created_at || '') || 0) - (Date.parse(a.created_at || '') || 0));

/** Resume the latest experiment using persisted records, never training loss. */
export function nextExperimentAction(training: ImprovementTraining[], evaluations: ImprovementEvaluation[]): ExperimentAction {
  const run = newest(training)[0];
  if (!run) return { title: 'Start your first training run', description: 'Choose a model, add your examples and train on this computer.', label: 'Start training', href: '#training', stage: 'Prepare' };
  if (['pending', 'running'].includes(run.status)) return { title: 'Your training is in progress', description: 'Follow progress and saved checkpoints. You can leave and return to this run.', label: 'View training progress', href: runHash('training', run.run_id, '#overview'), stage: 'Train' };
  if (['failed', 'cancelled'].includes(run.status)) return { title: 'Continue after an interrupted run', description: 'Inspect the saved progress and available recovery actions before starting again.', label: 'Review recovery options', href: runHash('training', run.run_id, '#overview'), stage: 'Train' };
  if (run.status !== 'completed' || !run.output_model_version || !run.base_model_version) return { title: 'Continue your training run', description: 'Inspect this run’s trained model and evidence to choose the next step.', label: 'Open training run', href: runHash('training', run.run_id, '#overview'), stage: 'Train' };
  const evaluation = newest(evaluations.filter(item => item.candidate_model_version === run.output_model_version && item.baseline_model_version === run.base_model_version))[0];
  if (!evaluation) return run.guided_evaluation?.eligible !== true
    ? { title: 'Review the candidate’s evaluation support', description: run.guided_evaluation?.reason || 'Guided comparison support has not been reported for this candidate. Inspect its supported evaluation profiles.', label: 'Open Evaluation', href: '#evaluation', stage: 'Compare' }
    : { title: 'Find out whether your model improved', description: 'Compare the trained model and its base model on held-out examples.', label: 'Compare on held-out examples', href: evaluationHash(run.run_id), stage: 'Compare' };
  const href = `#evaluation?run=${encodeURIComponent(evaluation.run_id)}`;
  if (evaluation.improvement_decision?.outcome === 'accept') return { title: 'Your accepted candidate is ready to inspect', description: 'Review the recorded decision and download the exact candidate with its evidence.', label: 'Review decision and export', href, stage: 'Export' };
  if (evaluation.improvement_decision?.outcome === 'reject') return { title: 'Use what this comparison taught you', description: 'Review the candidate’s failures before preparing a new dataset. Keep protected evaluation examples out of training.', label: 'Review rejected candidate', href, stage: 'Improve' };
  if (evaluation.status === 'completed') return { title: 'Your comparison is ready for a decision', description: 'Inspect improvements, regressions and coverage, then record whether to accept or reject the candidate.', label: 'Review comparison', href, stage: 'Decide' };
  if (evaluation.job && ['pending', 'running'].includes(evaluation.status)) return { title: 'Your comparison is running', description: 'Candidate and baseline outputs are being recorded against the same held-out cases.', label: 'View evaluation progress', href: runHash('evaluation', evaluation.run_id, '#overview'), stage: 'Compare' };
  return { title: 'Continue your model comparison', description: 'Review the saved evaluation and its next available action.', label: 'Open comparison', href, stage: 'Compare' };
}
