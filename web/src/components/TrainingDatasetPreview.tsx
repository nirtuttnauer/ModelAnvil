import { Notice, RecordTable } from './ui';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { columnMappingError, mappingFields, type TrainingColumnMapping, type TrainingDatasetValidation, type TrainingSampleRow, type TrainingSourceInspection } from '../api/training-dataset';
import './training-dataset-preview.css';

export function TrainingSourcePreview({ inspection, mapping, onChange, disabled }: {
  inspection: TrainingSourceInspection; mapping: TrainingColumnMapping; onChange: (value: TrainingColumnMapping) => void; disabled: boolean;
}) {
  const problem = columnMappingError(mapping, inspection.columns);
  const fields = mappingFields(mapping.mode);
  const fieldControl = (field: typeof fields[number]) => <label key={field.key}>{field.label}{field.required ? ' *' : ' (optional)'}<select value={mapping[field.key] || ''} required={field.required} disabled={disabled} onChange={event => onChange({ ...mapping, [field.key]: event.target.value })}><option value="">{field.required ? 'Select a source column' : field.key === 'group_field' ? 'Group repeated prompts automatically' : 'Do not include'}</option>{inspection.columns.map(column => <option key={column} value={column}>{column}</option>)}</select></label>;
  return <section className="training-dataset-preview" aria-label="Dataset source preview">
    <h3>Preview source rows</h3><p>{inspection.row_count} source rows · {inspection.columns.length} columns</p>
    <div className="training-sample-table" role="region" aria-label="Source sample rows" tabIndex={0}><RecordTable><caption>{inspection.limits}</caption><thead><tr><th scope="col">Row</th>{inspection.columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead><tbody>{inspection.sample_rows.map((row, index) => <tr key={index}><th scope="row" data-label="Row">{index + 1}</th>{inspection.columns.map(column => <td key={column} data-label={column}>{row[column] ?? 'Missing'}</td>)}</tr>)}</tbody></RecordTable></div>
    <h3>Map columns to training fields</h3><div className="training-column-mapping">
      <label>Training data structure<select value={mapping.mode} disabled={disabled} onChange={event => onChange({ mode: event.target.value as TrainingColumnMapping['mode'] })}><option value="auto">Automatic (standard fields)</option><option value="prompt_response">Prompt and response</option><option value="messages">Chat messages</option><option value="text">Plain text</option></select></label>
      {fields.filter(field => field.required).map(fieldControl)}
    </div>
    {fields.some(field => !field.required) && <details className="training-mapping-options"><summary>Optional context and grouping</summary><div className="training-column-mapping">{fields.filter(field => !field.required).map(fieldControl)}</div></details>}
    {problem && <p className="error-text" role="status">{problem}</p>}
    <p className="muted">{mapping.mode === 'text' ? 'Plain text trains on all text tokens.' : 'Records with chat roles train on assistant responses and mask user and system tokens. Plain-text records train on all text tokens.'} Review the validated training examples below before publication.</p>
  </section>;
}

export function TrainingSampleRows({ rows, caption = 'Sample rows from the prepared training data.' }: { rows: TrainingSampleRow[]; caption?: string }) {
  return <div className="training-sample-table" role="region" aria-label="Prepared sample rows" tabIndex={0}><RecordTable><caption>{caption}</caption><thead><tr><th scope="col">Example</th><th scope="col">Input / context</th><th scope="col">Target response / training text</th><th scope="col">Split</th></tr></thead><tbody>{rows.slice(0, 5).map((row, index) => <tr key={row.sample_id || index}><th scope="row" data-label="Example">{index + 1}</th><td data-label="Input / context">{(row.blocks || []).filter(block => block.role && block.role !== 'assistant').map(block => `${block.role}: ${block.text || ''}`).join('\n\n') || 'No prompt · plain text'}</td><td data-label="Target response / training text">{(row.blocks || []).filter(block => !block.role || block.role === 'assistant').map(block => block.text || `[${block.type || 'Non-text'} block]`).join('\n\n') || 'No target text reported'}</td><td data-label="Split">{row.assigned_split || 'Not reported'}</td></tr>)}</tbody></RecordTable></div>;
}

export function DatasetValidationWarnings({ report, checking }: { report: TrainingDatasetValidation | null; checking: boolean }) {
  return <section id="training-dataset-validation" className="training-dataset-validation" aria-label="Dataset validation" aria-busy={checking}>
    <h3>Dataset validation</h3>
    <p role="status">{checking ? 'Checking every row with the selected column mapping…' : !report ? 'Validation has not completed. Complete the mapping or retry the check before continuing.' : report.invalid_rows ? `${report.invalid_rows} of ${report.checked_rows} rows need repair. Fix the source data or adjust your column mapping before continuing.` : report.issues.length ? `All ${report.checked_rows} rows checked. Review the warnings before continuing.` : `All ${report.checked_rows} rows checked. No missing values, duplicate content or formatting issues found.`}</p>
    {report && !checking && <>
      <dl className="training-validation-counts">{[['Missing values', report.missing_value_rows], ['Duplicate rows', report.duplicate_rows], ['Formatting errors', report.formatting_error_rows]].map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>
      {report.issues.map((issue, index) => <Notice tone={issue.severity === 'error' ? 'error' : 'caution'} key={`${issue.code}-${index}`}>
        <strong>{issue.severity === 'error' ? 'Fix required' : 'Warning'} · {issue.count} {issue.count === 1 ? 'row' : 'rows'}</strong><p>{issue.message}</p>
        <p>Source {issue.rows.length === 1 ? 'row' : 'rows'}: {issue.rows.join(', ')}{issue.count > issue.rows.length ? ` (first ${issue.rows.length} shown)` : ''}.</p>
        {issue.examples && <ul>{issue.examples.map(example => <li key={example.row}>Row {example.row}: {example.message || `same training content as row ${example.duplicate_of}`}</li>)}</ul>}
      </Notice>)}
      <p className="muted">Row numbers count data records, excluding the CSV header. Every row is checked; issue examples show up to five rows. Model token limits are checked when you preview the dataset.</p>
    </>}
  </section>;
}

export function PreparedDatasetPreview({ revisionId, token }: { revisionId: string; token: string }) {
  const [result, setResult] = useState<{ rows: TrainingSampleRow[]; total: number; report?: { drop_reason_counts?: Record<string, number> }; recipe?: { extraction?: { source_mapping?: TrainingColumnMapping } } } | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setResult(null); setError('');
    void apiRequest<NonNullable<typeof result>>(`/api/v1/dataset-revisions/${encodeURIComponent(revisionId)}/inspect/`, token, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setResult(value); }).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
  }, [revisionId, token]);
  return <section className="training-dataset-preview" aria-label="Selected dataset preview"><h3>Selected dataset · sample rows</h3>
    {error ? <p role="status">Dataset preview unavailable: {error}</p> : !result ? <p role="status">Loading prepared samples…</p> : <><p>{result.total} prepared rows. This published revision uses a fixed mapping; create a new revision to change it.</p>{!!result.report?.drop_reason_counts?.['duplicate.exact'] && <Notice as="p" className="notice">{result.report.drop_reason_counts['duplicate.exact']} exact duplicate rows were removed when preparing this revision.</Notice>}{result.recipe?.extraction?.source_mapping && <dl className="training-mapping-summary">{Object.entries(result.recipe.extraction.source_mapping).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value}</dd></div>)}</dl>}{result.rows.length ? <TrainingSampleRows rows={result.rows} /> : <p>No sample rows are available in this revision.</p>}</>}
  </section>;
}
