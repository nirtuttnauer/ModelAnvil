import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import type { ModelExportOption } from '../api/model-export';
import { Button, Notice, RecordTable } from './ui';
import { ModelExport } from './ModelExport';
import type { Decision } from './ImprovementDecision';

interface ClassificationScore { accuracy: number | null; macro_f1: number | null; confusion_matrix?: number[][] }
interface ChangedCase { case_id: string; expected_output: string; candidate_output: string; baseline_output: string; change: string }
interface MeasuredResources { queue_seconds: number | null; execution_seconds: number | null; usage_available: boolean; usage: { quantity: string; unit: string; amount: string | null; currency: string | null }[] }
export interface DecisionReport {
  available: boolean; reason?: string; candidate?: ClassificationScore; baseline?: ClassificationScore;
  case_changes?: { improved: number; regressed: number; unchanged: number; changed_cases?: ChangedCase[] };
  complete_cases: number; total_cases: number; accuracy_delta: number | null; accuracy_delta_interval: [number, number] | null;
  labels: string[]; training_run_id?: string | null; export_available?: boolean;
  uncertainty_method?: string; resource_evidence?: { device?: string; prompt_format?: string; runtime?: string; decoding?: string; training?: MeasuredResources; evaluation?: MeasuredResources; peak_memory_bytes?: number | null; basis?: string };
}
const percentage = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : 'Not reported';
const score = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : 'Not reported';
const elapsed = (seconds: number | null | undefined) => typeof seconds === 'number' && Number.isFinite(seconds) ? `${seconds.toFixed(1)} seconds` : 'Not measured';

export function ImprovementReport({ report, runId, candidateName, baselineName }: {
  report: DecisionReport; runId: string; candidateName: string; baselineName: string;
}) {
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ evaluation_run_id: runId, ...report }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `modelanvil-comparison-${runId}.json`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="improvement-report" aria-labelledby="improvement-report-title">
    <div className="section-heading"><div><h3 id="improvement-report-title">Did the candidate improve?</h3><p>{report.complete_cases} of {report.total_cases} paired cases complete.</p></div>
      <Button type="button" disabled={!report.available} onClick={download}>Download decision report</Button></div>
    {!report.available ? <Notice as="p">{report.reason || 'Complete the verified candidate and baseline comparison to review this report.'}</Notice> : <>
      <div className="table-scroll"><RecordTable className="resource-table"><caption>Classification on the same held-out cases</caption><thead><tr><th scope="col">Measure</th><th scope="col">{candidateName}</th><th scope="col">{baselineName}</th></tr></thead><tbody>
        <tr><th scope="row">Accuracy</th><td>{percentage(report.candidate?.accuracy)}</td><td>{percentage(report.baseline?.accuracy)}</td></tr>
        <tr><th scope="row">Macro-F1</th><td>{score(report.candidate?.macro_f1)}</td><td>{score(report.baseline?.macro_f1)}</td></tr>
      </tbody></RecordTable></div>
      <p>Accuracy change: <strong>{typeof report.accuracy_delta === 'number' ? `${report.accuracy_delta > 0 ? '+' : ''}${(report.accuracy_delta * 100).toFixed(1)} percentage points` : 'Not reported'}</strong>.
        {report.accuracy_delta_interval && <> Recorded interval: {(report.accuracy_delta_interval[0] * 100).toFixed(1)} to {(report.accuracy_delta_interval[1] * 100).toFixed(1)} points.</>}</p>
      {report.case_changes && <p>{report.case_changes.improved} improved · {report.case_changes.regressed} regressed · {report.case_changes.unchanged} unchanged cases.</p>}
      <p className="muted">Review changed cases and the sample count before deciding. A small evaluation can expose failures without establishing a broad quality claim.</p>
      <dl className="comparison-resources" aria-label="Measured evaluation resources">
        <div><dt>Evaluation elapsed time</dt><dd>{elapsed(report.resource_evidence?.evaluation?.execution_seconds)}</dd></div>
        <div><dt>Committed evaluation usage</dt><dd>{report.resource_evidence?.evaluation?.usage_available && report.resource_evidence.evaluation.usage.length
          ? report.resource_evidence.evaluation.usage.map(item => `${item.quantity} ${item.unit.replaceAll('_', ' ')}`).join(' · ') : 'Not measured'}</dd></div>
        <div><dt>Peak memory</dt><dd>{typeof report.resource_evidence?.peak_memory_bytes === 'number' ? `${(report.resource_evidence.peak_memory_bytes / 1024 ** 3).toFixed(2)} GiB` : 'Not measured'}</dd></div>
      </dl>
      {!!report.case_changes?.changed_cases?.length && <div className="table-scroll" role="region" aria-label="Changed classification cases" tabIndex={0}><RecordTable className="resource-table"><caption>Cases with different candidate and baseline outputs</caption><thead><tr><th scope="col">Case</th><th scope="col">Expected</th><th scope="col">Candidate</th><th scope="col">Baseline</th><th scope="col">Change</th></tr></thead><tbody>{report.case_changes.changed_cases.map(item => <tr key={item.case_id}><th scope="row">{item.case_id}</th><td>{item.expected_output}</td><td>{item.candidate_output}</td><td>{item.baseline_output}</td><td>{item.change}</td></tr>)}</tbody></RecordTable></div>}
      {[['Candidate', report.candidate], ['Baseline', report.baseline]].map(([name, result]) => {
        const matrix = (result as ClassificationScore | undefined)?.confusion_matrix;
        return matrix?.length ? <details key={name as string}><summary>{name as string} confusion matrix</summary><div className="table-scroll" tabIndex={0} role="region" aria-label={`${name} confusion matrix`}><RecordTable className="resource-table"><caption>Rows are expected labels; columns are predicted labels.</caption><thead><tr><th scope="col">Expected / predicted</th>{[...report.labels, 'Invalid output'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{matrix.map((row, index) => <tr key={report.labels[index] || index}><th scope="row">{report.labels[index] || 'Unknown'}</th>{row.map((value, column) => <td key={column}>{value}</td>)}</tr>)}</tbody></RecordTable></div></details> : null;
      })}
      <details><summary>Measurement and execution details</summary><p>{report.uncertainty_method || 'The report provides recorded uncertainty only; an unavailable interval remains unknown.'}</p><p>Runtime: {report.resource_evidence?.runtime || 'See the durable run'}. Device: {report.resource_evidence?.device || 'Not reported'}. Template: {report.resource_evidence?.prompt_format || 'Not reported'}.</p>
        <p>Training elapsed time: {elapsed(report.resource_evidence?.training?.execution_seconds)}. Evaluation queue time: {elapsed(report.resource_evidence?.evaluation?.queue_seconds)}.</p>
        <p>{report.resource_evidence?.basis || 'Elapsed time includes model loading. Missing memory and monetary cost measurements remain unknown.'}</p>
        <p>Measured usage and reservations are available in the <a href={`#runs/evaluation/${encodeURIComponent(runId)}`}>durable run</a>.</p></details>
    </>}
  </section>;
}

export function ReviewedModelExport({ token, trainingRun, candidate, decision, evaluationRun }: {
  token: string; trainingRun: string; candidate: number; decision?: Decision | null; evaluationRun: string;
}) {
  const [run, setRun] = useState<{ output_model_version: number; export_options: ModelExportOption[]; quality_summary?: { selected_step: number } } | null>(null);
  const [error, setError] = useState(''), [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setRun(null); setError('');
    if (decision?.outcome !== 'accept') return () => controller.abort();
    void apiRequest<NonNullable<typeof run>>(`/api/v1/training-runs/${trainingRun}/`, token, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) { if (value.output_model_version !== candidate) throw new Error('The training export no longer matches this evaluated candidate.'); setRun(value); } })
      .catch(failure => { if (!controller.signal.aborted) setError(errorMessage(failure)); });
    return () => controller.abort();
  }, [trainingRun, candidate, token, decision?.outcome, retry]);
  if (decision?.outcome !== 'accept') return null;
  return <section aria-label="Accepted candidate export">{error ? <Notice as="p" tone="error" role="alert">{error} <Button type="button" onClick={() => setRetry(value => value + 1)}>Retry export details</Button></Notice>
    : run ? <ModelExport runId={trainingRun} options={run.export_options || []} token={token} checkpointStep={run.quality_summary?.selected_step} evaluationRun={evaluationRun} /> : <p role="status">Checking the exact candidate export…</p>}</section>;
}
