import { Button, Card, Field } from '../components/ui';
import { LineagePanel, type LineagePath } from '../components/LineagePanel';
import { VersionChip } from '../components/ResourcePicker';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { handoffHash, resourceHash, type ResourceKind } from '../api/resource-routes';
import { runHash } from '../api/runs';
import { DataInspector } from '../components/DataInspector';
import { ResourceState } from '../components/ResourceState';

interface Lineage {
  training_runs: { run_id: string; recipe: string; status?: string; output_model_version?: string | null; dataset_revision: string | null; base_model_version: string | null; recovery_parent: string | null }[];
  evaluations?: { run_id: string; status: string }[]; releases?: { release_version_id: string; revision_no: number; status: string }[];
  rows?: Record<string, unknown>[]; total?: number; next_cursor?: number | null;
  capabilities?: { train: boolean; annotate: boolean; limits: string };
}
interface RecordDetail extends Record<string, unknown> {
  model_name?: string; dataset_name?: string; revision_no: number;
  capabilities?: { train: { eligible: boolean }; evaluate: { eligible: boolean }; chat: { eligible: boolean } };
}
export function ResourceDetailPage({ token, kind, id, refreshKey }: { token: string; kind: ResourceKind; id: string; refreshKey: number }) {
  const [record, setRecord] = useState<RecordDetail | null>(null), [lineage, setLineage] = useState<Lineage | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState<string | null>(null), [retry, setRetry] = useState(0);
  const [query, setQuery] = useState(''), [cursor, setCursor] = useState(0);
  const path = `/api/v1/${kind === 'model-version' ? 'model-versions' : 'dataset-revisions'}/${encodeURIComponent(id)}/`;
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null);
    Promise.all([apiRequest<RecordDetail>(path, token, { signal: c.signal }), apiRequest<Lineage>(path + (kind === 'model-version' ? 'lineage/' : `inspect/?cursor=${cursor}&query=${encodeURIComponent(query)}`), token, { signal: c.signal })])
      .then(([r, l]) => { if (!c.signal.aborted) { setRecord(r); setLineage(l); } })
      .catch(e => { if (!c.signal.aborted) setError(`This exact resource is unavailable, deleted, or inaccessible in this project. ${errorMessage(e)}`); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, path, kind, refreshKey, retry, query, cursor]);
  const paths: LineagePath[] = [];
  const current = { kind: kind === 'model-version' ? 'Model' : 'Dataset', name: record?.model_name || record?.dataset_name || 'Exact resource', id, revision: record?.revision_no, href: resourceHash(kind, id) };
  for (const run of lineage?.training_runs || []) {
    const inputs: LineagePath['nodes'] = [];
    if (run.dataset_revision) inputs.push(run.dataset_revision === id ? current : { kind: 'Dataset', name: 'Pinned dataset revision', id: run.dataset_revision, href: resourceHash('dataset-revision', run.dataset_revision) });
    const execution = { kind: 'Training', name: run.recipe, id: run.run_id, state: run.status, href: runHash('training', run.run_id) };
    const output = run.output_model_version || (kind === 'model-version' ? id : null);
    const outputNodes = output ? [output === id ? current : { kind: 'Model', name: 'Output model version', id: output, href: resourceHash('model-version', output) }] : [];
    paths.push({ label: 'Dataset → training → recorded output', nodes: [...inputs, execution, ...outputNodes] });
    if (run.base_model_version) paths.push({ label: 'Base model → training', nodes: [{ kind: 'Model', name: 'Pinned base model', id: run.base_model_version, href: resourceHash('model-version', run.base_model_version) }, execution] });
    if (run.recovery_parent) paths.push({ label: 'Parent execution → recovery', nodes: [{ kind: 'Training', name: 'Parent execution', id: run.recovery_parent, href: runHash('training', run.recovery_parent) }, execution] });
  }
  if (kind === 'model-version') {
    for (const run of lineage?.evaluations || []) paths.push({ label: 'Model → evaluation', nodes: [current, { kind: 'Evaluation', name: 'Recorded evaluation', id: run.run_id, state: run.status, href: runHash('evaluation', run.run_id) }] });
    for (const release of lineage?.releases || []) paths.push({ label: 'Model → release', nodes: [current, { kind: 'Release', name: 'Recorded release', id: release.release_version_id, revision: release.revision_no, state: release.status, href: `#releases?release_version=${release.release_version_id}` }] });
  }
  return <Card className="panel"><div className="panel-title"><div><h2>{record?.model_name || record?.dataset_name || 'Exact resource'}{record && ` · revision ${record.revision_no}`}</h2><VersionChip {...current} state={typeof record?.state === 'string' ? record.state : undefined} /></div><a href={kind === 'model-version' ? '#models' : '#datasets'}>Back to {kind === 'model-version' ? 'Models' : 'Datasets'}</a></div><div className="panel-body">
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
    {record && lineage && <>
      <div className="actions" aria-label="Compatible resource actions">
        {(kind === 'model-version' ? record.capabilities?.train.eligible : lineage.capabilities?.train) && <a href={handoffHash('training', kind, id)}>Train this version</a>}
        {kind === 'model-version' && record.capabilities?.chat.eligible && <a href={handoffHash('chat', kind, id)}>Chat with this version</a>}
        {kind === 'model-version' && record.capabilities?.evaluate.eligible && <a href={handoffHash('evaluation', kind, id)}>Evaluate this version</a>}
        {kind === 'model-version' && lineage.evaluations?.some(e => e.status === 'completed') && <a href={handoffHash('releases', kind, id)}>Review candidate release</a>}
        {kind === 'dataset-revision' && lineage.capabilities?.annotate && <a href={handoffHash('annotation', kind, id)}>Annotate this revision</a>}
      </div><p className="muted">Actions carry this exact revision. The receiving form checks current access, compatibility and launch permissions.</p>
      {lineage.capabilities?.limits && <p className="muted">{lineage.capabilities.limits}</p>}
      <LineagePanel paths={paths} />
      {kind === 'dataset-revision' && <section><h3>Published records ({lineage.total})</h3><label>Search published records<Field value={query} onChange={e => { setQuery(e.target.value); setCursor(0); }} /></label><DataInspector value={lineage.rows || []} /><div className="actions"><Button disabled={!cursor} onClick={() => setCursor(Math.max(0, cursor-25))}>Previous records</Button><Button disabled={lineage.next_cursor == null} onClick={() => setCursor(lineage.next_cursor!)}>Next records</Button></div></section>}
      <details open><summary>Exact revision and evidence</summary><DataInspector value={record} /></details><details><summary>Preparation, artifacts and lineage records</summary><DataInspector value={lineage} /></details>
    </>}
  </div></Card>;
}
