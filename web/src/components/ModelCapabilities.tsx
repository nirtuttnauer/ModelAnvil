import { Card } from './ui';
import { resourceHash } from '../api/resource-routes';
import { useEffect, useState } from 'react';
import { allResources, type RegisteredModel } from '../api/resources';
import { errorMessage } from '../api/client';

export function ModelCapabilities({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [versions, setVersions] = useState<RegisteredModel[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    const c = new AbortController(); setError('');
    allResources<RegisteredModel>('/api/v1/model-versions/', token, c.signal)
      .then(rows => { if (!c.signal.aborted) setVersions(rows); })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => c.abort();
  }, [token, refreshKey]);
  return <Card className="panel"><div className="panel-title"><div><h2>Model runtime compatibility</h2><p>Eligibility is checked from pinned inputs. Launch and generation still validate actual runtime and capacity.</p></div></div><div className="panel-body">
    {error && <p role="alert" className="error-text">{error}</p>}
    {!error && !versions.length && <p className="muted">Import or initialize a model to inspect its supported operations.</p>}
    {versions.map(version => <details key={version.model_version_id}><summary>{version.model_name} · r{version.revision_no}</summary>
      <a href={resourceHash('model-version', version.model_version_id)}>Inspect exact version and lineage</a><dl className="ops-facts">{(['train','evaluate','chat'] as const).map(operation => <div key={operation}><dt>{operation}</dt><dd>{version.capabilities?.[operation].eligible ? 'Eligible' : 'Unavailable'} · {version.capabilities?.[operation].reason || 'Compatibility not reported'}</dd></div>)}</dl>
      {version.capabilities?.train.eligible && <p>Recipes: {version.capabilities.train.recipes.join(', ')}</p>}
      {version.capabilities?.chat.eligible && <p>Devices: {version.capabilities.chat.devices.join(', ')}</p>}
    </details>)}
  </div></Card>;
}
