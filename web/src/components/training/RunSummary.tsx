import { Button, KeyValueList } from '../ui';
import { trainingMethodLabel } from '../../api/training';

export function RunSummary({ model, dataset, recipe, compute, steps, synthetic, canReview, busy, checking, onPreflight }: {
  model: string; dataset: string; recipe: string; compute: string; steps: number; synthetic: boolean; canReview: boolean; busy: boolean; checking: boolean; onPreflight(): void;
}) {
  return <aside className="training-run-preview" aria-label="Run summary">
    <h2>Your training run</h2>
    <KeyValueList items={[
      { label: 'Model', value: model }, { label: 'Dataset', value: dataset }, { label: 'Method', value: trainingMethodLabel(recipe) },
      { label: 'Compute', value: compute }, { label: 'Steps', value: steps > 0 ? steps : 'Add a dataset' },
    ]} />
    <p className="muted">{synthetic ? 'Synthetic runs use no worker or budget.' : `Reserves ${steps > 0 ? steps : 'the planned'} training steps. Preflight checks compatibility, hardware, storage and budget before launch.`}</p>
    {!synthetic && <Button type="button" variant="primary" disabled={busy || checking || !canReview} onClick={onPreflight}>{checking ? 'Checking…' : 'Run preflight'}</Button>}
    {!canReview && <p className="muted" role="status">Choose a model and dataset to continue.</p>}
  </aside>;
}
