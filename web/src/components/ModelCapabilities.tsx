import { RecordTable, StatusBadge } from './ui';
import { resourceHash } from '../api/resource-routes';
import { trainingMethodLabel } from '../api/training';
import type { ModelVersion } from '../api/models';

const OPERATIONS = ['train', 'evaluate', 'chat'] as const;

/** Which operations each registered version can run, as reported by the server. */
export function ModelCapabilities({ versions }: { versions: ModelVersion[] }) {
  return <div data-ui="form">
    <p className="muted">Eligibility is checked from pinned inputs. Launch and generation still validate the runtime and capacity.</p>
    {!versions.length && <p className="muted">Import or initialize a model to inspect its supported operations.</p>}
    {versions.length > 0 && <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table">
      <thead><tr><th>Version</th><th>Train</th><th>Evaluate</th><th>Chat</th></tr></thead>
      <tbody>{versions.map(version => <tr key={version.model_version_id}>
        <td><a href={resourceHash('model-version', version.model_version_id)}>{version.model_name} · r{version.revision_no}</a></td>
        {OPERATIONS.map(operation => {
          const capability = version.capabilities?.[operation];
          if (!capability) return <td key={operation}>Not reported</td>;
          const detail = operation === 'train' && capability.eligible && 'recipes' in capability ? capability.recipes.map(trainingMethodLabel).join(', ')
            : operation === 'chat' && capability.eligible && 'devices' in capability ? capability.devices.join(', ') : capability.reason;
          return <td key={operation}><StatusBadge status={capability.eligible ? 'eligible' : 'unavailable'} tone={capability.eligible ? 'success' : 'neutral'} label={capability.eligible ? 'Eligible' : 'Unavailable'} />{detail && <small>{detail}</small>}</td>;
        })}
      </tr>)}</tbody>
    </RecordTable></div>}
  </div>;
}
