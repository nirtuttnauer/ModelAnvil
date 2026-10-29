import { Button, Disclosure, KeyValueList, LinkButton, StatusBadge } from '../ui';
import { Identifier } from '../Identifier';
import { evaluationHash } from '../../api/improvement';
import { runHash } from '../../api/runs';
import { trainingMethodLabel, type ModelVersion, type Tokenizer, type TrainingRun } from '../../api/training';
import { InferenceCheck } from './InferenceCheck';

/** The facts behind one run: inputs, result, checkpoints and the inference check. */
export function RunDetailsPanel({ run, label, tokenizers, models, token, variant, busy, onCancel, onClose, children }: {
  run: TrainingRun; label: string; tokenizers: Tokenizer[]; models: ModelVersion[]; token: string; variant: 'history' | 'current';
  busy: boolean; onCancel(runId: string): void; onClose?(): void; children?: React.ReactNode;
}) {
  const active = run.status === 'running' || run.status === 'pending';
  const trained = run.status === 'completed' && !!run.output_model_version_uuid;
  const summary = run.quality_summary;
  return <div className="training-run-details">
    {variant === 'history' && <div className="training-run-details-head">
      <div><h2>{label}</h2><StatusBadge status={run.status} /></div>
      <div data-ui="actions">
        {trained && run.guided_evaluation?.eligible && run.base_model_version && <LinkButton variant="primary" href={evaluationHash(run.run_id)}>Compare on held-out examples</LinkButton>}
        {trained && <LinkButton href={`#chat?model_version=${encodeURIComponent(run.output_model_version_uuid!)}`}>Try your model</LinkButton>}
        {trained && run.base_model_version && <LinkButton href={`#chat?model_version=${encodeURIComponent(run.output_model_version_uuid!)}&compare_base=1`}>Try base vs trained</LinkButton>}
        {active && <Button type="button" disabled={busy} onClick={() => onCancel(run.run_id)}>Cancel run</Button>}
        <LinkButton variant="quiet" href={runHash('training', run.run_id)}>Open run</LinkButton>
        {onClose && <Button type="button" variant="quiet" onClick={onClose}>Close details</Button>}
      </div>
    </div>}
    {children}
    {variant === 'history' && summary && <p>Selected checkpoint: step {summary.selected_step} of {run.total_steps}.{summary.validation_loss != null && summary.baseline_loss != null ? ` Validation loss ${summary.baseline_loss.toLocaleString(undefined, { maximumSignificantDigits: 4 })} → ${summary.validation_loss.toLocaleString(undefined, { maximumSignificantDigits: 4 })} on ${summary.validation_examples} examples.` : ' No validation examples were available.'}</p>}
    <KeyValueList columns={2} items={[
      { label: 'Run ID', value: <Identifier value={run.run_id} label="Run ID" display="code" /> },
      { label: 'Method', value: trainingMethodLabel(run.recipe_type) },
      { label: 'Base model', value: run.base_model_version ? <>{models.find(m => m.id === run.base_model_version)?.model_name || 'Pinned version'} <Identifier value={String(run.base_model_version)} label="Base model record ID" /></> : 'Random initialization' },
      { label: 'Tokenizer', value: <>{tokenizers.find(t => t.id === run.tokenizer_version)?.name || 'Version'} <Identifier value={String(run.tokenizer_version)} label="Tokenizer record ID" /></> },
      { label: run.runtime?.execution_mode === 'worker' ? 'Weights' : 'Seed', value: run.runtime?.execution_mode === 'worker' ? 'Pinned base weights' : String(run.initialization_seed) },
      ...(run.dataset_manifest_digest ? [{ label: 'Dataset manifest', value: <Identifier value={run.dataset_manifest_digest} label="Dataset manifest digest" display="code" /> }] : []),
      ...(run.job ? [{ label: 'Job', value: <Identifier value={run.job} label="Job ID" display="code" /> }] : []),
      { label: 'Evidence', value: run.execution_evidence ? `${run.execution_evidence.level} · ${run.execution_evidence.source}` : 'Not reported' },
    ]} />
    <div className="training-checkpoints">
      <h3>Checkpoints · {run.checkpoints.length}{run.checkpoints.length > 5 ? ' (latest 5 shown)' : ''}</h3>
      {run.checkpoints.length ? <ul>{run.checkpoints.slice(-5).map(c => <li key={c.checkpoint_id}>
        <strong>Step {c.step}</strong><StatusBadge status={c.is_valid ? 'valid' : 'invalid'} label={c.is_valid ? 'Valid Safetensors' : 'Invalid'} />
        <span className="muted">State <Identifier value={c.state_digest} label="Checkpoint state digest" />{(c.weights_manifest?.weights_sha256 || c.weights_manifest?.weights?.weights_sha256) && <> · Weights <Identifier value={c.weights_manifest?.weights_sha256 || c.weights_manifest?.weights?.weights_sha256 || ''} label="Weights SHA-256" /></>}</span>
      </li>)}</ul> : <p className="muted">No checkpoints recorded yet.</p>}
    </div>
    <Disclosure summary="Advanced inference check"><InferenceCheck key={run.run_id} runId={run.run_id} token={token} enabled={run.status === 'completed'} /></Disclosure>
  </div>;
}
