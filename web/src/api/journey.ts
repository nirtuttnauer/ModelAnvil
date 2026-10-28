/** The one fine-tuning journey shown by Welcome, Overview and the Training wizard. */
export const FINE_TUNE_STAGES = ['Prepare', 'Train', 'Compare', 'Decide', 'Export'] as const;
export type FineTuneStage = (typeof FINE_TUNE_STAGES)[number];
export const PREPARE_STEPS = ['Choose model', 'Add examples', 'Review plan'] as const;

/** Map any recorded stage name (including legacy "Improve") onto the shared journey. */
export function stageFor(stage: string | null | undefined): FineTuneStage {
  if (stage === 'Improve') return 'Prepare';
  return (FINE_TUNE_STAGES as readonly string[]).includes(stage ?? '') ? (stage as FineTuneStage) : 'Prepare';
}

export function stageIndex(stage: string | null | undefined): number {
  return FINE_TUNE_STAGES.indexOf(stageFor(stage));
}
