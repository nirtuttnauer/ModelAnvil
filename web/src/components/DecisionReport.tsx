import { EvidenceLabel } from './EvidenceLabel';

export interface DecisionSlice {
  slice: string;
  sample_count: number;
  candidate_accuracy: number;
  baseline_accuracy: number;
  relation: string;
  candidate_uncertainty?: { lower: number; upper: number };
  baseline_uncertainty?: { lower: number; upper: number };
}

export interface DecisionReportData {
  eligible: boolean;
  decisive: boolean;
  recommended_outcome: string;
  sample_count: number;
  candidate_accuracy: number | null;
  baseline_accuracy: number | null;
  prompt_format?: string | null;
  runtime_seconds?: number | null;
  minimum_decisive_cases: number;
  production_qualified: boolean;
  slices: DecisionSlice[];
  gate: { passed: boolean; reason: string };
  candidate_pins?: unknown;
  baseline_pins?: unknown;
}

function percent(value: number | null) {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : 'Not reported';
}

export function DecisionReport({ report }: { report: DecisionReportData }) {
  const headline = report.recommended_outcome === 'accept' ? 'Accept is supported' : report.recommended_outcome === 'reject' ? 'Reject is supported' : report.eligible ? 'Not enough evidence to call a win or a loss' : 'Decision report unavailable';
  return <section aria-label="Decision report">
    <h4>{headline}</h4>
    <p>{report.gate.reason}</p>
    <EvidenceLabel evidence={{ level: report.eligible ? 'integrated_execution' : 'configuration_only', source: report.prompt_format ? `Prompt format ${report.prompt_format}` : 'Prompt format not reported', production_qualified: report.production_qualified }} />
    <dl className="ml-definition-list">
      <div><dt>Sample</dt><dd>{report.sample_count} cases · decisive from {report.minimum_decisive_cases}</dd></div>
      <div><dt>Candidate accuracy</dt><dd>{percent(report.candidate_accuracy)}</dd></div>
      <div><dt>Baseline accuracy</dt><dd>{percent(report.baseline_accuracy)}</dd></div>
      <div><dt>Runtime</dt><dd>{typeof report.runtime_seconds === 'number' ? `${report.runtime_seconds.toFixed(1)} seconds` : 'Not reported'}</dd></div>
    </dl>
    {!!report.slices.length && <ul>{report.slices.map(slice => <li key={slice.slice}>{slice.slice}: {slice.relation} · {slice.sample_count} cases · candidate {percent(slice.candidate_accuracy)} · baseline {percent(slice.baseline_accuracy)}</li>)}</ul>}
    <p className="muted">Training loss, chat, and a three-step setup check are not this decision. Recording a choice does not deploy the model.</p>
  </section>;
}
