import { RecordTable } from './ui';
import { DataValue, dataLabel } from './DataInspector';
import { compareMetrics, type RecordedMetric } from './workbench-data';
import './workbench-components.css';

function Measurement({ value }: { value: number | null | undefined }) {
  return typeof value === 'number' && Number.isFinite(value) ? <DataValue value={value} /> : <span className="wb-muted">Not reported</span>;
}
function Interval({ value }: { value: unknown }) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const interval = value as Record<string, unknown>;
    if (typeof interval.lower === 'number' && typeof interval.upper === 'number' && Number.isFinite(interval.lower) && Number.isFinite(interval.upper) && interval.lower <= interval.upper) {
      return <span className="wb-number"><DataValue value={interval.lower} /> – <DataValue value={interval.upper} /></span>;
    }
  }
  return <span className="wb-muted">Not reported</span>;
}

export function MetricComparison({ metrics, baseline = [], candidateName = 'Candidate', baselineName = 'Baseline' }: {
  metrics: RecordedMetric[]; baseline?: RecordedMetric[]; candidateName?: string; baselineName?: string;
}) {
  const rows = compareMetrics(metrics, baseline);
  if (!rows.length) return <p className="wb-empty">No metrics recorded.</p>;
  return <div className="metric-comparison">
    <p className="wb-muted">Delta is candidate minus baseline for the same metric and slice. Its sign alone does not establish improvement. Intervals are shown only as recorded.</p>
    <div className="table-scroll" tabIndex={0} role="region" aria-label="Metric comparison table"><RecordTable>
      <caption className="wb-sr-only">Recorded candidate and baseline measurements by metric and slice</caption>
      <thead><tr><th scope="col">Metric / slice</th><th scope="col">{candidateName}</th><th scope="col">{baselineName}</th><th scope="col">Delta</th><th scope="col">Samples<br /><small>Candidate / baseline</small></th><th scope="col">Recorded uncertainty<br /><small>Candidate / baseline</small></th></tr></thead>
      <tbody>{rows.map(row => <tr key={JSON.stringify([row.key, row.slice])}><th scope="row"><strong title={row.key}>{dataLabel(row.key)}</strong><small>{row.slice}</small></th>
        <td><Measurement value={row.candidate?.value} /></td><td><Measurement value={row.baseline?.value} /></td><td className="wb-number">{row.delta == null ? <span className="wb-muted">Unavailable</span> : <span title={`Unrounded difference: ${row.delta}`}>{row.delta > 0 ? '+' : ''}{Number(row.delta.toPrecision(10))}</span>}</td>
        <td><Measurement value={row.candidate?.sample_count} /> / <Measurement value={row.baseline?.sample_count} /></td>
        <td><div><Interval value={row.candidate?.uncertainty_interval} /></div><div className="wb-baseline-interval"><Interval value={row.baseline?.uncertainty_interval} /></div></td>
      </tr>)}</tbody>
    </RecordTable></div>
  </div>;
}
