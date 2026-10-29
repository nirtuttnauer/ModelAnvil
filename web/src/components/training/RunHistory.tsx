import { Button, Checkbox, Disclosure, RecordTable, StatusBadge } from '../ui';
import { EmptyState } from '../Feedback';
import { Identifier } from '../Identifier';
import { LineChart } from '../Charts';
import { DataInspector } from '../DataInspector';
import { trainingMethodLabel, type TrainingRun } from '../../api/training';

export function RunHistory({ runs, selectedId, comparisonIds, onComparisonChange, compared, compareBlocked, runLabel, runHref, onInspect, onMonitor }: {
  runs: TrainingRun[]; selectedId?: string; comparisonIds: string; onComparisonChange(value: string): void; compared: TrainingRun[]; compareBlocked: string[];
  runLabel(id: string): string; runHref(run: TrainingRun): string; onInspect(run: TrainingRun): void; onMonitor(run: TrainingRun): void;
}) {
  const chosen = comparisonIds.split(',').filter(Boolean);
  if (!runs.length) return <EmptyState title="No training runs yet" description="Runs you start appear here with their method, progress and checkpoints." layout="centered" />;
  return <>
    <div className="table-scroll" tabIndex={0}>
      <RecordTable>
        <thead><tr><th>Run</th><th>Method</th><th>Status</th><th>Progress</th><th>Loss</th><th>Checkpoints</th></tr></thead>
        <tbody>{runs.map(r => <tr key={r.run_id} className={selectedId === r.run_id ? 'training-selected-row' : undefined}>
          <td>
            <div className="training-run-cell"><a href={runHref(r)}>{runLabel(r.run_id)}</a> <Identifier value={r.run_id} label="Run ID" /></div>
            <div data-ui="actions"><Button type="button" variant="quiet" size="sm" onClick={() => onInspect(r)}>Inspect run</Button><Button type="button" variant="quiet" size="sm" onClick={() => onMonitor(r)}>View monitor</Button>
              <Checkbox label="Compare this run" checked={chosen.includes(r.run_id)} onChange={e => onComparisonChange(e.target.checked ? [...chosen.slice(-1), r.run_id].join(',') : chosen.filter(id => id !== r.run_id).join(','))} /></div>
          </td>
          <td>{trainingMethodLabel(r.recipe_type)}</td>
          <td><StatusBadge status={r.status} /><small className="muted" title={r.execution_evidence?.source}>{r.execution_evidence?.level || 'unknown evidence'}</small></td>
          <td><progress value={r.current_step} max={r.total_steps || 1} aria-label={`${runLabel(r.run_id)} progress`} /> <small>{r.current_step} / {r.total_steps}</small></td>
          <td>{r.latest_loss === null ? 'Not reported' : r.latest_loss.toFixed(4)}</td>
          <td>{r.checkpoints.length}</td>
        </tr>)}</tbody>
      </RecordTable>
    </div>
    <Disclosure summary="Compare two runs" variant="card">
      <p className="muted">Tick two runs above. Overlays need the same method, runtime, tokenizer, dataset and validation protocol.</p>
      {compareBlocked.map(reason => <p key={reason} role="status">{reason}</p>)}
      {compared.map(run => <Disclosure key={run.run_id} summary={`${runLabel(run.run_id)} · ${trainingMethodLabel(run.recipe_type)}`} variant="quiet"><Identifier value={run.run_id} label="Run ID" display="code" /><DataInspector value={run.runtime} /></Disclosure>)}
      {!compareBlocked.length && compared.length > 0 && <LineChart series={compared.flatMap(run => [{ name: `${runLabel(run.run_id)} training`, points: (run.metrics_log || []).map(row => ({ x: row.step, y: row.loss })) }, { name: `${runLabel(run.run_id)} validation`, points: (run.metrics_log || []).flatMap(row => typeof row.validation_loss === 'number' ? [{ x: row.step, y: row.validation_loss! }] : []) }])} yLabel="Comparable loss" />}
    </Disclosure>
  </>;
}
