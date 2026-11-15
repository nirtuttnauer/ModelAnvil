import { Disclosure, LinkButton, Notice, Section } from '../ui';
import { ChartEmpty, LineChart } from '../Charts';
import { ModelExport } from '../ModelExport';
import { TrainingRunProgress } from '../TrainingRunProgress';
import { RunDetailsPanel } from './RunDetailsPanel';
import { GpuTelemetry } from './GpuTelemetry';
import { evaluationHash } from '../../api/improvement';
import { trainingLossSeries } from '../../api/training-progress';
import type { ModelVersion, Tokenizer, TrainingRun } from '../../api/training';
import { GuidedDecision } from '../GuidedDecision';
import { useState } from 'react';

const number = (value: number) => value.toLocaleString(undefined, { maximumSignificantDigits: 4 });

/** Stage and health first, then the four numbers that decide wait-or-cancel, the loss curve, and details folded away. */
export function CurrentRun({ run, label, refreshedAt, progressError, onRefresh, onCancel, busy, token, tokenizers, models }: {
  run: TrainingRun; label: string; refreshedAt: number; progressError: string | null; onRefresh(): void; onCancel(runId: string): void; busy: boolean;
  token: string; tokenizers: Tokenizer[]; models: ModelVersion[];
}) {
  const series = trainingLossSeries(run.metrics_log);
  const trained = run.status === 'completed' && !!run.output_model_version_uuid;
  const summary = run.quality_summary;
  const runtimePin = run.runtime?.pins?.runtime || '';
  const [decisionOpen, setDecisionOpen] = useState(false);
  return <div className="training-current">
    <TrainingRunProgress key={`progress-${run.run_id}`} run={run} label={label} refreshedAt={refreshedAt} refreshError={progressError} onRefresh={onRefresh} onCancel={() => onCancel(run.run_id)} cancelBusy={busy} />
    {(summary || trained) && <Notice tone="success" className="training-candidate">
      <div>
        <strong>{trained ? 'Your trained model is ready.' : 'Training finished.'}</strong>
        {summary && (summary.validation_loss != null && summary.baseline_loss != null
          ? <><p>Validation loss: {number(summary.baseline_loss)} before training → {number(summary.validation_loss)} for the selected model. Lower is better.</p><p>{summary.validation_loss < summary.baseline_loss ? 'Validation improved' : 'Validation did not improve'} on {summary.validation_examples} examples; check real answers too. Selected checkpoint: step {summary.selected_step} of {run.total_steps}.</p></>
          : <p>No validation examples were available. Test the model on independent examples before relying on it. Selected checkpoint: step {summary.selected_step} of {run.total_steps}.</p>)}
      </div>
      {trained && <div data-ui="actions">
        {run.guided_evaluation?.eligible && run.base_model_version && <LinkButton variant="primary" href={evaluationHash(run.run_id)}>Compare on held-out examples</LinkButton>}
        <LinkButton href={`#chat?model_version=${encodeURIComponent(run.output_model_version_uuid!)}`}>Try your model</LinkButton>
        {run.base_model_version && <LinkButton href={`#chat?model_version=${encodeURIComponent(run.output_model_version_uuid!)}&compare_base=1`}>Try base vs trained</LinkButton>}
      </div>}
    </Notice>}
    {run.status === 'completed' && <ModelExport key={`export-${run.run_id}`} runId={run.run_id} options={run.export_options || []} token={token} evidence={run.execution_evidence} checkpointStep={summary?.selected_step ?? run.total_steps} synthetic={run.runtime?.execution_mode === 'simulation'} />}
    {run.status === 'completed' && !/^modelanvil\.(smolvlm-|speecht5-)/.test(runtimePin) && <Disclosure summary="Compare and decide" variant="card" open={decisionOpen} onToggle={event => setDecisionOpen(event.currentTarget.open)}>{decisionOpen && <GuidedDecision key={`${token}:${run.run_id}`} token={token} runId={run.run_id} />}</Disclosure>}
    <Section title="Loss & checkpoint activity" level={2} description={`${label} · ${run.execution_evidence?.level || 'unknown evidence'} · recorded values`}>
      {series.length ? <LineChart key={run.run_id} series={series} xLabel="Committed step" yLabel="Loss" /> : <ChartEmpty message={run.status === 'pending' ? 'This run is queued. Loss appears after the first measured checkpoint.' : 'No loss measurements have been recorded for this run.'} />}
    </Section>
    <Disclosure summary="Details" variant="card">
      <RunDetailsPanel run={run} label={label} tokenizers={tokenizers} models={models} token={token} variant="current" busy={busy} onCancel={onCancel}>
        <GpuTelemetry metrics={run.metrics_log} profile={run.runtime?.pins?.optimization} />
      </RunDetailsPanel>
    </Disclosure>
  </div>;
}
