import { Button, RecordTable, Section, StatusBadge } from '../ui';
import { resourceHash } from '../../api/resource-routes';
import { runHash } from '../../api/runs';
import type { ModelImport } from './useModelImports';

/** Downloads and verified uploads, with cancel and resume where the job allows it. */
export function ModelImports({ imports, busy, error, onChange }: { imports: ModelImport[]; busy: boolean; error?: string; onChange(item: ModelImport, action: 'cancel' | 'resume'): void }) {
  if (!imports.length && !error) return null;
  return <Section title="Imports" description="Downloads and verified uploads for this project.">
    {error && <p className="error-text" role="alert">{error}</p>}
    {imports.length > 0 && <div className="table-scroll" tabIndex={0}><RecordTable>
      <thead><tr><th>Import</th><th>Files verified</th><th>Status</th><th>Model</th><th>Actions</th></tr></thead>
      <tbody>{imports.map(item => { const job = item.job_status || ''; return <tr key={item.import_id}>
        <td>{item.name}</td>
        <td>{Object.keys(item.acquired_files).length} of {Object.keys(item.files).length}</td>
        <td><StatusBadge status={item.job_status || item.status} /></td>
        <td>{item.candidate_id ? <a href={resourceHash('model-version', item.candidate_id)}>Open model version</a> : 'Pending'}</td>
        <td><div data-ui="actions">
          {item.job_id && <a href={runHash('job', item.job_id)}>Job</a>}
          {['queued', 'running'].includes(job) && <Button type="button" size="sm" disabled={busy} onClick={() => onChange(item, 'cancel')}>Cancel</Button>}
          {['failed', 'interrupted', 'cancelled'].includes(job) && <Button type="button" size="sm" disabled={busy} onClick={() => onChange(item, 'resume')}>Resume</Button>}
        </div></td>
      </tr>; })}</tbody>
    </RecordTable></div>}
  </Section>;
}
