import { Button, Disclosure, LinkButton, Section, StatusBadge, TextControl } from '../components/ui';
import { LineagePanel, type LineagePath } from '../components/LineagePanel';
import { VersionChip } from '../components/ResourcePicker';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { handoffHash, resourceHash, type ResourceKind } from '../api/resource-routes';
import { runHash } from '../api/runs';
import { DataInspector } from '../components/DataInspector';
import { ResourceState } from '../components/ResourceState';
import './ml-pages.css';

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
      .catch(e => { if (!c.signal.aborted) setError(`This resource is unavailable, deleted or inaccessible in this project. ${errorMessage(e)}`); })
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
  const name = record?.model_name || record?.dataset_name || 'Exact resource';
  const state = typeof record?.state === 'string' ? record.state : undefined;
  const actions = record && lineage ? [
    ...((kind === 'model-version' ? record.capabilities?.train.eligible : lineage.capabilities?.train) ? [{ href: handoffHash('training', kind, id), label: 'Train this version' }] : []),
    ...(kind === 'model-version' && record.capabilities?.chat.eligible ? [{ href: handoffHash('chat', kind, id), label: 'Chat with this version' }] : []),
    ...(kind === 'model-version' && record.capabilities?.evaluate.eligible ? [{ href: handoffHash('evaluation', kind, id), label: 'Evaluate this version' }] : []),
    ...(kind === 'model-version' && lineage.evaluations?.some(e => e.status === 'completed') ? [{ href: handoffHash('releases', kind, id), label: 'Review candidate release' }] : []),
    ...(kind === 'dataset-revision' && lineage.capabilities?.annotate ? [{ href: handoffHash('annotation', kind, id), label: 'Annotate this revision' }] : []),
  ] : [];

  return <div className="ml-page">
    <Section title={record ? `${name} · revision ${record.revision_no}` : name} description={kind === 'model-version' ? 'Model version with its recorded lineage.' : 'Dataset version with its recorded lineage.'} actions={<LinkButton variant="quiet" href={kind === 'model-version' ? '#models' : '#datasets'}>Back to {kind === 'model-version' ? 'Models' : 'Datasets'}</LinkButton>}>
      <ResourceState loading={loading && !record} error={error} onRetry={() => setRetry(v => v + 1)} />
      {record && lineage && <>
        <div data-ui="actions"><VersionChip {...current} state={state} />{state && <StatusBadge status={state} />}</div>
        {actions.length > 0 && <div data-ui="actions" aria-label="Compatible resource actions">{actions.map((action, index) => <LinkButton key={action.label} variant={index === 0 ? 'primary' : 'secondary'} href={action.href}>{action.label}</LinkButton>)}</div>}
        <p className="muted">Actions carry this exact revision. The receiving form checks access, compatibility and launch permissions.{lineage.capabilities?.limits ? ` ${lineage.capabilities.limits}` : ''}</p>
        <LineagePanel paths={paths} />
        {kind === 'dataset-revision' && <Section title={`Published records (${lineage.total})`} level={3}>
          <TextControl label="Search published records" value={query} onChange={e => { setQuery(e.target.value); setCursor(0); }} />
          <DataInspector value={lineage.rows || []} />
          <div data-ui="actions"><Button type="button" disabled={!cursor} onClick={() => setCursor(Math.max(0, cursor-25))}>Previous records</Button><Button type="button" disabled={lineage.next_cursor == null} onClick={() => setCursor(lineage.next_cursor!)}>Next records</Button></div>
        </Section>}
        <Disclosure summary="Raw record" variant="quiet">
          <DataInspector value={record} title="Revision and evidence" />
          <DataInspector value={lineage} title="Preparation, artifacts and lineage records" />
        </Disclosure>
      </>}
    </Section>
  </div>;
}
