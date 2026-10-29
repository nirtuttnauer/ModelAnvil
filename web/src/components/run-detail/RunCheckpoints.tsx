import { Disclosure, RecordTable, StatusBadge } from '../ui';
import { Identifier } from '../Identifier';
import type { Bounded, Checkpoint } from '../../api/run-detail';

/** Committed checkpoints for a training run, folded away. */
export function RunCheckpoints({ checkpoints }: { checkpoints: Bounded<Checkpoint> }) {
  return <Disclosure summary={`Checkpoints (${checkpoints.total})`} variant="card">
    <p className="runs-hint">{checkpoints.total === 0 ? 'No checkpoint has been committed for this run.' : `${checkpoints.rows.length} of ${checkpoints.total} loaded.`}</p>
    {checkpoints.rows.length > 0 && (
      <div className="table-scroll" tabIndex={0}>
        <RecordTable>
          <thead><tr><th scope="col">Step</th><th scope="col">State digest</th><th scope="col">Validity</th><th scope="col">Runtime contract</th><th scope="col">Committed</th></tr></thead>
          <tbody>
            {checkpoints.rows.map((checkpoint) => (
              <tr key={checkpoint.checkpoint_id}>
                <td>{checkpoint.step}</td>
                <td><Identifier value={checkpoint.state_digest} label="Checkpoint state digest" display="code" /></td>
                <td><StatusBadge status={checkpoint.is_valid ? 'valid' : 'invalid'} /></td>
                <td>{checkpoint.contract_digest ? <Identifier value={checkpoint.contract_digest} label="Runtime contract digest" display="code" /> : 'Not recorded'}</td>
                <td>{new Date(checkpoint.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </RecordTable>
      </div>
    )}
  </Disclosure>;
}
