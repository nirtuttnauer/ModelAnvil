import type { StoryObj } from '@storybook/react-vite';
import { http, HttpResponse } from 'msw';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import screens from './Screens.stories';
import { writeDraft } from '../api/drafts';
import { trainingDefaults } from '../api/training-workspace';
import { mlResponses } from './ml-fixtures';
import { demoRequests } from './demo-network';

const datasetId = 'd1000000-0000-4000-8000-000000000001', revisionId = 'd1000000-0000-4000-8000-000000000002', artifactId = 'd1000000-0000-4000-8000-000000000003';
const records = Array.from({ length: 6 }, (_, i) => ({ customer_question: `Reset question ${i + 1}?`, support_reply: `Open settings ${i + 1}.`, notes: `Device context ${i + 1}`, group_key: `case-${i + 1}` }));
const fileText = 'customer_question,support_reply,notes,group_key\n' + records.map(row => Object.values(row).join(',')).join('\n');
const splits = { train: 4, validation: 1, test: 1 };
const recipe = 'c'.repeat(64);
let inspected = 0, mappings: Record<string, string>[] = [], prepared: Record<string, unknown> | null = null;
const mapping = { mode: 'prompt_response', prompt_field: 'customer_question', response_field: 'support_reply' };
const sampleRows = records.slice(0, 5).map((row, i) => ({ sample_id: `sample-${i + 1}`, source_group_id: row.group_key, assigned_split: i < 4 ? 'train' : 'validation', blocks: [{ role: 'user', type: 'text', text: row.customer_question }, { role: 'assistant', type: 'text', text: row.support_reply }] }));
const meta = {
  ...screens, title: 'ModelAnvil/Actions/Training dataset preview',
  parameters: { demoRoute: '#training', demoHeading: 'Training', demoApiPath: '/api/v1/fine-tuning/options/' },
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context); inspected = 0; mappings = []; prepared = null;
    writeDraft(sessionStorage, 'modelanvil.draft.v1:' + JSON.stringify(['demo-tenant', '1', 'training', 'new']), { ...trainingDefaults, guidedStage: 1 }, trainingDefaults);
    const state = context.parameters.datasetState;
    const activeRecords = state === 'messages' ? [{ dialogue: [{ role: 'user', content: 'Reset?' }, { role: 'assistant', content: 'Open settings.' }] }] : records;
    let artifact = { artifact_id: artifactId, state: 'staging', sha256: '', byte_size: 0 };
    let name = 'support';
    const revision = () => ({ id: 8, revision_id: revisionId, dataset: 8, dataset_name: name, revision_no: 1, schema_version: '1.0', manifest_digest: recipe, manifest_artifact: 9,
      recipe_digest: recipe, source_snapshots: [], row_count: 6, state: 'published', published_at: new Date().toISOString(), metadata: { split_counts: splits } });
    context.msw.use(
      http.get('/api/v1/dataset-revisions/', () => HttpResponse.json({ results: [...mlResponses['/api/v1/dataset-revisions/'] as object[], ...(prepared ? [revision()] : [])], next: null })),
      http.get('/api/v1/dataset-revisions/:id/inspect/', () => HttpResponse.json({ rows: sampleRows, total: 6, recipe: { extraction: { source_mapping: mapping } }, split_counts: splits })),
      http.post('/api/v1/fine-tuning/inspect-source/', async ({ request }) => {
        inspected++; if (state === 'retry' && inspected === 1) return HttpResponse.json({ detail: 'Synthetic inspection failure' }, { status: 503 });
        const form = await request.formData(); const file = form.get('file') as File;
        return HttpResponse.json({ row_count: activeRecords.length, columns: Object.keys(activeRecords[0]), sample_rows: activeRecords.slice(0, 5).map(row => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, typeof value === 'string' ? value : JSON.stringify(value)]))),
          recommended_mapping: { mode: 'auto' }, validation: { checked_rows: activeRecords.length, invalid_rows: 0, missing_value_rows: 0, duplicate_rows: 0, formatting_error_rows: 0, issues: [], can_prepare: true, mapping: JSON.parse(String(form.get('source_mapping') || '{"mode":"auto"}')) }, source_digest: Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())), b => b.toString(16).padStart(2, '0')).join(''), limits: 'First 5 source rows. Synthetic data for UI testing.' });
      }),
      http.post('/api/v1/fine-tuning/preview/', async ({ request }) => {
        const form = await request.formData(); const selected = JSON.parse(String(form.get('source_mapping'))) as Record<string, string>; mappings.push(selected);
        const rows = selected.mode === 'text' ? records.slice(0, 5).map((row, i) => ({ sample_id: `sample-${i + 1}`, assigned_split: 'train', blocks: [{ type: 'text', text: row.notes }] })) : selected.mode === 'messages' ? [{ blocks: [{ role: 'user', text: 'Reset?' }, { role: 'assistant', text: 'Open settings.' }] }] : sampleRows.map((row, i) => ({ ...row, blocks: [{ role: 'user', text: records[i][selected.prompt_field as keyof typeof records[0]] }, { role: 'assistant', text: records[i][selected.response_field as keyof typeof records[0]] }] }));
        return HttpResponse.json({ row_count: activeRecords.length, source_group_count: activeRecords.length, split_counts: splits, recipe_digest: recipe, examples: rows.map(row => row.blocks), sample_rows: rows, objectives: [selected.mode === 'text' ? 'all text tokens' : 'assistant responses'], dropped_count: 0, warnings: [] });
      }),
      http.post('/api/v1/artifacts/', async ({ request }) => { const body = await request.json() as typeof artifact; artifact = { ...artifact, ...body }; return HttpResponse.json(artifact, { status: 201 }); }),
      http.post('/api/v1/artifacts/:id/upload/', () => { artifact.state = 'committed'; return HttpResponse.json(artifact); }),
      http.post('/api/v1/datasets/', async ({ request }) => { name = (await request.json() as { name: string }).name; return HttpResponse.json({ dataset_id: datasetId, name, description: '', current_revision: null, metadata: {}, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }, { status: 201 }); }),
      http.post('/api/v1/datasets/:id/prepare/', async ({ request }) => { prepared = await request.json() as Record<string, unknown>; return HttpResponse.json(revision(), { status: 201 }); }),
      http.get('/api/v1/dataset-revisions/' + revisionId + '/', () => HttpResponse.json(revision())),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
function verified(canvasElement: HTMLElement) {
  expect(demoRequests.some(request => request.method === 'POST' && ['/api/v1/training-runs/', '/api/v1/training-runs/preflight/'].includes(request.path))).toBe(false);
  canvasElement.dataset.demoVerified = 'passed';
}
async function upload(canvasElement: HTMLElement, messages = false) {
  const canvas = within(canvasElement);
  const file = new File([messages ? JSON.stringify([{ dialogue: [{ role: 'user', content: 'Reset?' }, { role: 'assistant', content: 'Open settings.' }] }]) : fileText], messages ? 'messages.json' : 'support.csv', { type: messages ? 'application/json' : 'text/csv' });
  await userEvent.upload(await canvas.findByLabelText('Training file', { exact: true }), file);
  await expect(canvas.findByRole('region', { name: 'Dataset source preview' })).resolves.toBeVisible();
  return canvas;
}
async function mapPair(canvasElement: HTMLElement) {
  const canvas = await upload(canvasElement);
  await userEvent.selectOptions(canvas.getByLabelText('Training data structure'), 'prompt_response');
  await expect(canvas.getByRole('button', { name: 'Preview dataset' })).toBeDisabled();
  await userEvent.selectOptions(canvas.getByLabelText(/^Prompt column/), 'customer_question');
  await userEvent.selectOptions(canvas.getByLabelText(/^Response column/), 'support_reply');
  return canvas;
}
async function preview(canvasElement: HTMLElement) {
  const canvas = within(canvasElement); await waitFor(() => expect(canvas.getByRole('button', { name: 'Preview dataset' })).toBeEnabled()); await userEvent.click(canvas.getByRole('button', { name: 'Preview dataset' }));
  await expect(canvas.findByRole('region', { name: 'Prepared sample rows' })).resolves.toBeVisible();
  await expect(canvas.getByRole('button', { name: 'Use this dataset' })).toBeVisible();
}
export const CustomColumns: Story = { play: async ({ canvasElement }) => { const canvas = await mapPair(canvasElement); await expect(canvas.getByLabelText('Dataset name')).toHaveValue('support'); await preview(canvasElement); expect(mappings[0]).toMatchObject(mapping); verified(canvasElement); } };
export const PreserveDatasetName: Story = { play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await userEvent.type(await canvas.findByLabelText('Dataset name'), 'My support examples');
  await upload(canvasElement);
  await expect(canvas.getByLabelText('Dataset name')).toHaveValue('My support examples');
  verified(canvasElement);
} };
export const OptionalContext: Story = { play: async ({ canvasElement }) => {
  const canvas = await mapPair(canvasElement);
  const context = canvas.getByLabelText(/^Additional context column/);
  await expect(context).not.toBeVisible();
  const toggle = canvas.getByText('Optional context and grouping', { selector: 'summary' });
  await userEvent.click(toggle);
  await userEvent.selectOptions(context, 'notes');
  await userEvent.click(toggle); await userEvent.click(toggle);
  await expect(context).toHaveValue('notes');
  await preview(canvasElement);
  expect(mappings[0]).toMatchObject({ ...mapping, context_field: 'notes' });
  if (window.innerWidth <= 540) for (const region of canvasElement.querySelectorAll('.training-sample-table')) {
    expect(region.scrollWidth).toBeLessThanOrEqual(region.clientWidth + 1);
  }
  verified(canvasElement);
} };
export const MessagesColumn: Story = { parameters: { datasetState: 'messages' }, play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement, true); await userEvent.selectOptions(canvas.getByLabelText('Training data structure'), 'messages'); await userEvent.selectOptions(canvas.getByLabelText(/^Messages column/), 'dialogue');
  await preview(canvasElement); expect(mappings[0]).toMatchObject({ mode: 'messages', messages_field: 'dialogue' }); verified(canvasElement);
} };
export const PlainText: Story = { play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement); await userEvent.selectOptions(canvas.getByLabelText('Training data structure'), 'text'); await userEvent.selectOptions(canvas.getByLabelText(/^Text column/), 'notes');
  await preview(canvasElement); await expect(canvas.getByText(/Training learns all text tokens/)).toBeVisible(); verified(canvasElement);
} };
export const MappingChangeRequiresPreview: Story = { play: async ({ canvasElement }) => {
  const canvas = await mapPair(canvasElement); await preview(canvasElement); await userEvent.selectOptions(canvas.getByLabelText(/^Response column/), 'notes');
  await waitFor(() => expect(canvas.queryByRole('button', { name: 'Use this dataset' })).not.toBeInTheDocument());
  await preview(canvasElement); expect(mappings).toHaveLength(2); expect(mappings[1].response_field).toBe('notes'); verified(canvasElement);
} };
export const PublishReviewedMapping: Story = { play: async ({ canvasElement }) => {
  const canvas = await mapPair(canvasElement); await preview(canvasElement); await userEvent.click(canvas.getByRole('button', { name: 'Use this dataset' }));
  await expect(canvas.findByRole('heading', { name: 'Model and dataset selected' })).resolves.toBeVisible(); expect(prepared).toMatchObject({ source_format: 'training', source_mapping: mapping }); verified(canvasElement);
} };
export const ExistingPublishedRevision: Story = { play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await userEvent.click(await canvas.findByRole('button', { name: 'Advanced settings' }));
  const revisions = canvas.getByLabelText('Prepared dataset revision', { exact: true }); await waitFor(() => expect(within(revisions).getAllByRole('option').length).toBeGreaterThan(1));
  await userEvent.selectOptions(revisions, '1'); await expect(canvas.findByRole('region', { name: 'Selected dataset preview' })).resolves.toBeVisible(); await expect(canvas.findByRole('region', { name: 'Prepared sample rows' })).resolves.toBeVisible(); verified(canvasElement);
} };
export const InspectionRetry: Story = { parameters: { datasetState: 'retry' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await userEvent.upload(await canvas.findByLabelText('Training file', { exact: true }), new File([fileText], 'support.csv', { type: 'text/csv' }));
  await expect(canvas.findByRole('alert')).resolves.toBeVisible(); await userEvent.click(canvas.getByRole('button', { name: 'Try again' }));
  await expect(canvas.findByRole('region', { name: 'Dataset source preview' })).resolves.toBeVisible(); expect(inspected).toBe(2); verified(canvasElement);
} };
export const Dark: Story = { ...CustomColumns, parameters: { demoTheme: 'dark' } };
export const Preview: Story = CustomColumns;
