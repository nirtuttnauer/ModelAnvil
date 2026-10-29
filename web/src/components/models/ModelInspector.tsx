import { useState } from 'react';
import { KeyValueList, LinkButton, Select, StatusBadge } from '../ui';
import { InspectorPanel } from '../InspectorPanel';
import { Identifier } from '../Identifier';
import { resourceHash } from '../../api/resource-routes';
import { statusLabel } from '../../api/status';
import { formatParameters, taskLabel, versionsOf, type Model, type ModelVersion } from '../../api/models';

const OPERATIONS = [['train', 'Train'], ['evaluate', 'Evaluate'], ['chat', 'Chat']] as const;

/** Facts and actions for one model and the version chosen from it. */
export function ModelInspector({ model, versions, onClose }: { model: Model; versions: ModelVersion[]; onClose(): void }) {
  const own = versionsOf(model, versions);
  const [versionId, setVersionId] = useState('');
  const version = own.find(item => item.model_version_id === versionId) || own[0];
  return <InspectorPanel title={model.name} eyebrow="Model" onClose={onClose} focusOnOpen footer={<p className="muted">Registry state is a recorded label, not a qualification.</p>}>
    {model.description && <p>{model.description}</p>}
    <KeyValueList items={[
      { label: 'Model ID', value: <Identifier value={model.model_id} label="Model ID" display="code" /> },
      { label: 'Intended tasks', value: model.intended_tasks.length ? model.intended_tasks.map(taskLabel).join(', ') : 'Not declared' },
    ]} />
    {!own.length && <p className="muted">No versions yet. Add a model or initialize a CPU base under Advanced.</p>}
    {own.length > 1 && <Select label="Version" value={version?.model_version_id ?? ''} onChange={event => setVersionId(event.target.value)}
      options={own.map(item => ({ value: item.model_version_id, label: `r${item.revision_no} · ${statusLabel(item.state)}` }))} />}
    {version && <>
      {own.length === 1 && <div data-ui="actions"><strong>Version r{version.revision_no}</strong><StatusBadge status={version.state} /></div>}
      <KeyValueList items={[
        { label: 'Architecture', value: version.architecture_ref || 'Not reported' },
        { label: 'Parameters', value: formatParameters(version.parameters_count) },
        { label: 'License', value: version.license_evidence || 'Not reported' },
        { label: 'Version ID', value: <Identifier value={version.model_version_id} label="Version ID" display="code" /> },
        ...OPERATIONS.map(([key, label]) => {
          const capability = version.capabilities?.[key];
          return { key, label, value: capability ? `${capability.eligible ? 'Eligible' : 'Unavailable'}${capability.reason ? ` · ${capability.reason}` : ''}` : 'Compatibility not reported' };
        }),
      ]} />
      <div data-ui="actions">
        <LinkButton variant="primary" href={`#training?model_version=${encodeURIComponent(version.model_version_id)}`}>Train with this version</LinkButton>
        <LinkButton href={`#chat?model_version=${encodeURIComponent(version.model_version_id)}`}>Chat</LinkButton>
        <LinkButton href={resourceHash('model-version', version.model_version_id)}>Open version</LinkButton>
      </div>
    </>}
  </InspectorPanel>;
}
