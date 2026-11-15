import { RecordTable } from '../ui';
import {
  NOT_REPORTED, measuredAt, mebibytes, missingReasons, optimizationSummary, telemetryCell, telemetryRows,
  type OptimizationProfile, type TelemetryMetric,
} from '../../api/training-telemetry';

const fixed = (digits: number) => (value: number) => value.toFixed(digits);

/** Latest measured accelerator steps with their measurement times; missing values say why and are never estimated. */
export function GpuTelemetry({ metrics, profile }: { metrics?: TelemetryMetric[]; profile?: OptimizationProfile | null }) {
  const rows = telemetryRows(metrics);
  const summary = optimizationSummary(profile);
  if (!rows.length && !summary) return null;
  const reasons = missingReasons(rows);
  return <div className="training-telemetry">
    {summary && <p><strong>Optimization profile:</strong> {summary}</p>}
    {rows.length > 0 && <div className="table-scroll" tabIndex={0}><RecordTable>
      <caption>Measured GPU steps, latest {rows.length}. Missing values are not estimated.</caption>
      <thead><tr><th>Step and time</th><th>Training loss</th><th>Validation loss</th><th>Gradient norm</th><th>Tokens/s</th><th>Allocated / peak allocated / peak reserved MiB</th><th>GPU utilization</th><th>Trainable / total params</th></tr></thead>
      <tbody>{rows.map(m => <tr key={m.step}>
        <td>{m.step}<br /><small className="muted"><time dateTime={m.measured_at}>{measuredAt(m.measured_at)}</time></small></td>
        <td>{telemetryCell(m, 'loss', fixed(6))}</td>
        <td>{telemetryCell(m, 'validation_loss', fixed(6))}{m.validation_prediction_tokens == null ? '' : <><br /><small className="muted">{m.validation_prediction_tokens} prediction tokens</small></>}</td>
        <td>{telemetryCell(m, 'gradient_norm', fixed(4))}</td>
        <td>{telemetryCell(m, 'tokens_per_second', fixed(2))}{m.training_pairs == null ? '' : <><br /><small className="muted">{m.training_pairs} supervised tokens{m.padding_positions ? `, ${m.padding_positions} padding` : ''}</small></>}</td>
        <td>{telemetryCell(m, 'gpu_allocated_bytes', mebibytes)} / {telemetryCell(m, 'peak_allocated_bytes', mebibytes)} / {telemetryCell(m, 'peak_reserved_bytes', mebibytes)}</td>
        <td>{telemetryCell(m, 'gpu_utilization_percent', value => `${value}%`)}</td>
        <td>{m.trainable_parameters?.toLocaleString() ?? NOT_REPORTED} / {m.total_parameters?.toLocaleString() ?? NOT_REPORTED}</td>
      </tr>)}</tbody>
    </RecordTable></div>}
    {reasons.map(item => <p key={item.reason} className="muted"><small>{item.metrics.join(' and ')}: {item.reason}</small></p>)}
  </div>;
}
