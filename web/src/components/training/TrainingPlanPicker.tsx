import { Button, Select, TextControl } from '../ui';
import type { GuidedRevision } from '../../api/guided-training';

export function TrainingPlanPicker({ preset, onPreset, manualSteps, onSteps, steps, revision, plan, synthetic, canReview }: {
  preset: string; onPreset(value: string): void; manualSteps: string; onSteps(value: string): void; steps: number; revision: GuidedRevision | null;
  plan: { epochs: number; trainingExamples: number }; synthetic: boolean; canReview: boolean;
}) {
  const validation = revision?.metadata.split_counts.validation ?? 0, test = revision?.metadata.split_counts.test ?? 0;
  return <section className="training-plan">
    <Select label="Training plan" value={preset} onChange={event => { onPreset(event.target.value); if (event.target.value === 'custom') onSteps(String(steps || 50)); }}>
      <option value="recommended" disabled={!revision}>Recommended{revision ? ` · ${plan.epochs} passes` : ' · add a dataset first'}</option>
      <option value="quick">Quick check · 3 steps</option>
      <option value="custom">Custom step count</option>
    </Select>
    {preset === 'custom' && <TextControl label="Total steps" required type="number" min="1" max="3000" step="1" value={manualSteps} onChange={event => onSteps(event.target.value)} />}
    <p className="muted">{preset === 'recommended' ? revision ? `${plan.epochs} passes over ${plan.trainingExamples} examples (${steps} steps)${revision ? ` · ${validation} validation, ${test} test held out.` : '.'}` : 'Add your dataset to calculate the recommended plan.' : preset === 'quick' ? 'Checks your setup in 3 steps. Use more steps to judge quality.' : `${steps} training steps${revision ? ` · ${validation} validation, ${test} test held out.` : '.'}`}</p>
    {synthetic && <Button variant="primary" disabled={!canReview}>Start synthetic run</Button>}
  </section>;
}
