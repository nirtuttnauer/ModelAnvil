import { Button, Disclosure, RecordTable } from '../ui';
import { DataInspector, DataValue } from '../DataInspector';
import { BarChart, ChartPanel, LineChart } from '../Charts';
import type { RunKind } from '../../api/runs';
import type { RunDetail } from '../../api/run-detail';

/** Recorded metrics for one run: the loss chart (training) or measurement bars (evaluation), then the bounded table. */
export function RunMetrics({ kind, detail, busy, fullMetrics, historyError, onLoadHistory }: {
  kind: RunKind; detail: RunDetail; busy: boolean; fullMetrics: Record<string, unknown>[] | null; historyError: string; onLoadHistory(): void;
}) {
  const rows = detail.metrics.rows;
  return <Disclosure summary={`Metrics (${detail.metrics.total})`} variant="card" open={kind === 'training' && detail.metrics.total > 0}>
    {kind === 'training' && rows.length > 0 && <ChartPanel title="Recorded loss" description={`Exact metric steps · evidence: ${detail.evidence?.level ?? 'not reported'}`}>
      <LineChart series={[
        { name: 'Training loss', points: rows.flatMap(row => typeof row.step === 'number' && typeof row.loss === 'number' ? [{ x: row.step, y: row.loss }] : []) },
        { name: 'Validation loss', points: rows.flatMap(row => typeof row.step === 'number' && typeof row.validation_loss === 'number' ? [{ x: row.step, y: row.validation_loss }] : []) },
      ].filter(series => series.points.length)} yLabel="Loss" />
    </ChartPanel>}
    {kind === 'evaluation' && rows.length > 0 && <ChartPanel title="Evaluation measurements" description="Frozen scoring metrics; sample counts and uncertainty are in the table.">
      <BarChart data={rows.filter(row => typeof row.value === 'number').map(row => ({ label: String(row.key || 'Metric'), value: Number(row.value) }))} />
    </ChartPanel>}
    {detail.metrics.truncated && <p className="runs-hint">Showing the {rows.length} most recent of {detail.metrics.total} recorded points.</p>}
    {kind === 'training' && detail.metrics.truncated && <div data-ui="actions"><Button type="button" disabled={busy} onClick={onLoadHistory}>Inspect complete training history</Button></div>}
    {historyError && <p role="alert" className="error-text">{historyError}</p>}
    {fullMetrics && <Disclosure summary={`Complete recorded training history (${fullMetrics.length} points)`} variant="quiet" open><DataInspector value={fullMetrics} /></Disclosure>}
    {detail.metrics.total === 0 ? <p className="muted">No metrics have been recorded for this run.</p> : (
      <div className="table-scroll" tabIndex={0}>
        <RecordTable>
          <thead><tr><th scope="col">{kind === 'training' ? 'Step' : 'Metric'}</th><th scope="col">{kind === 'training' ? 'Loss' : 'Value'}</th><th scope="col">Other recorded values</th></tr></thead>
          <tbody>
            {rows.map((row, index) => {
              const rest = Object.entries(row).filter(([key]) => key !== 'step' && key !== 'loss');
              return (
                <tr key={`${String(row.step ?? index)}-${index}`}>
                  <td><DataValue value={kind === 'training' ? row.step ?? '—' : row.key ?? '—'} /></td>
                  <td>{kind === 'training' ? typeof row.loss === 'number' ? row.loss.toFixed(6) : 'Not reported' : <DataValue value={row.value ?? 'Not reported'} />}</td>
                  <td>{rest.length === 0 ? '—' : <DataValue value={Object.fromEntries(rest)} />}</td>
                </tr>
              );
            })}
          </tbody>
        </RecordTable>
      </div>
    )}
  </Disclosure>;
}
