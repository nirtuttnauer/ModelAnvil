import { Disclosure, KeyValueList, LinkButton, StatusBadge } from '../ui';
import { InspectorPanel } from '../InspectorPanel';
import { Identifier } from '../Identifier';
import { DataInspector } from '../DataInspector';
import { SegmentBar } from '../Charts';
import { numericEntries } from '../chart-data';
import { resourceHash } from '../../api/resource-routes';
import type { DatasetRevision } from '../../api/datasets';

/** Facts about one dataset version, with the raw records folded away. */
export function DatasetVersionInspector({ revision, onClose }: { revision: DatasetRevision; onClose(): void }) {
  const splits = numericEntries(revision.metadata.split_counts).filter(item => Number.isInteger(item.value) && item.value >= 0);
  const report = revision.metadata.drop_report;
  const reasons = numericEntries(report && typeof report === 'object' ? (report as Record<string, unknown>).drop_reason_counts : undefined);
  return <InspectorPanel title={`Version ${revision.revision_no}`} eyebrow="Dataset version" onClose={onClose} focusOnOpen>
    <div data-ui="actions"><StatusBadge status={revision.state} /><span className="muted">{revision.row_count == null ? 'Not prepared' : `${revision.row_count.toLocaleString()} examples`}</span></div>
    <KeyValueList items={[
      { label: 'Dataset record', value: `#${revision.dataset}` },
      { label: 'Published', value: revision.published_at ? new Date(revision.published_at).toLocaleString() : 'Not published' },
      { label: 'Schema', value: revision.schema_version },
      { label: 'Version ID', value: <Identifier value={revision.revision_id} label="Version ID" display="code" /> },
      { label: 'Manifest digest', value: <Identifier value={revision.manifest_digest} label="Manifest SHA-256" display="code" /> },
      { label: 'Recipe digest', value: <Identifier value={revision.recipe_digest} label="Recipe SHA-256" display="code" /> },
      { label: 'Manifest artifact', value: revision.manifest_artifact ? <Identifier value={revision.manifest_artifact} label="Manifest artifact ID" display="code" /> : 'None' },
      { label: 'Source references', value: `${revision.source_snapshots.length} recorded` },
    ]} />
    {splits.length ? <SegmentBar data={splits} unit="examples" /> : <p className="muted">This version does not report split counts.</p>}
    {reasons.length > 0 && <KeyValueList items={reasons.map(item => ({ label: item.label, value: `${item.value} excluded` }))} />}
    <div data-ui="actions">
      <LinkButton variant="primary" href={`#training?dataset_revision=${encodeURIComponent(revision.revision_id)}`}>Fine-tune with this dataset</LinkButton>
      <LinkButton href={resourceHash('dataset-revision', revision.revision_id)}>Open dataset version</LinkButton>
    </div>
    <Disclosure summary="Raw metadata" variant="quiet"><DataInspector value={{ metadata: revision.metadata, source_snapshots: revision.source_snapshots }} /></Disclosure>
  </InspectorPanel>;
}
