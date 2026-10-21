import type { StoryObj } from '@storybook/react-vite';
import { http, HttpResponse } from 'msw';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import previewMeta from './TrainingDatasetPreview.stories';
import { demoRequests } from './demo-network';
import type { TrainingColumnMapping, TrainingDatasetValidation } from '../api/training-dataset';

const mapping: TrainingColumnMapping = { mode: 'prompt_response', prompt_field: 'prompt', response_field: 'response' };
const records = Array.from({ length: 7 }, (_, i) => ({ prompt: `Question ${i + 1}?`, response: `Answer ${i + 1}.`, alternate: `Reviewed answer ${i + 1}.`, notes: `Context ${i + 1}` }));
const rows = records.slice(0, 5).map((row, i) => ({ sample_id: `example-${i}`, assigned_split: i < 3 ? 'train' : i === 3 ? 'validation' : 'test', blocks: [{ type: 'text', role: 'user', text: row.prompt }, { type: 'text', role: 'assistant', text: row.response }] }));
const meta = {
  ...previewMeta, title: 'ModelAnvil/Actions/Dataset validation',
  beforeEach(context: Parameters<typeof previewMeta.beforeEach>[0]) {
    previewMeta.beforeEach(context);
    const state = context.parameters.validationState;
    let inspected = 0;
    context.msw.use(
      http.post('/api/v1/fine-tuning/inspect-source/', async ({ request }) => {
        inspected++;
        const form = await request.formData(), file = form.get('file') as File;
        if (file.name === 'malformed.json') return HttpResponse.json({ detail: 'The file is malformed. Use one JSON object per line, a JSON array, or a CSV with unique column names.' }, { status: 400 });
        if (state === 'retry' && inspected === 2) return HttpResponse.json({ detail: 'Synthetic validation service unavailable. Try again.' }, { status: 503 });
        const activeRecords = JSON.parse(await file.text()) as typeof records;
        const selected = form.has('source_mapping') ? JSON.parse(String(form.get('source_mapping'))) as TrainingColumnMapping : mapping;
        const bad = file.name !== 'corrected.json' && (state === 'errors' || state === 'mapping') && selected.response_field !== 'alternate';
        const warnings = state === 'warnings';
        const report: TrainingDatasetValidation = { checked_rows: 7, invalid_rows: bad ? 2 : 0, missing_value_rows: bad ? 1 : warnings ? 2 : 0,
          duplicate_rows: warnings ? 1 : 0, formatting_error_rows: bad ? 1 : 0, can_prepare: !bad, mapping: selected,
          issues: bad ? [
            { code: 'missing_values', severity: 'error', count: 1, rows: [6], message: 'Column "response" has missing or blank values. Fill every required value before previewing again.' },
            { code: 'formatting', severity: 'error', count: 1, rows: [7], message: 'Repair malformed training records before continuing.', examples: [{ row: 7, message: 'Example 7: response must contain nonempty text.' }] },
          ] : warnings ? [
            { code: 'missing_values', severity: 'warning', count: 2, rows: [4, 5], message: 'Column "notes" has missing or blank values. Check whether these blanks are intentional; unused columns do not affect training.' },
            { code: 'duplicate_rows', severity: 'warning', count: 1, rows: [7], message: 'Repeated training content adds no new examples. Exact duplicates will be removed during guided preparation; the first occurrence is kept.', examples: [{ row: 7, duplicate_of: 1 }] },
            { code: 'whitespace', severity: 'warning', count: 1, rows: [3], message: 'Leading or trailing whitespace is present. Check formatting; text is preserved exactly as supplied.' },
          ] : [] };
        return HttpResponse.json({ row_count: 7, columns: Object.keys(activeRecords[0]), sample_rows: activeRecords.slice(0, 5), recommended_mapping: mapping, validation: report,
          source_digest: Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())), b => b.toString(16).padStart(2, '0')).join(''), limits: 'First 5 source rows. Synthetic data for UI testing.' });
      }),
      http.post('/api/v1/fine-tuning/preview/', () => HttpResponse.json({ row_count: state === 'warnings' ? 6 : 7, source_group_count: 6, split_counts: { train: 4, validation: 1, test: 1 },
        recipe_digest: 'c'.repeat(64), examples: rows.map(row => row.blocks), sample_rows: rows, objectives: ['assistant responses'], dropped_count: state === 'warnings' ? 1 : 0, warnings: [] })),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
async function upload(canvasElement: HTMLElement, name = 'validation.json', issues = 'clean') {
  const canvas = within(canvasElement);
  const source = records.map(row => ({ ...row }));
  if (issues === 'errors') { source[5].response = ''; (source[6] as Record<string, unknown>).response = 42; }
  if (issues === 'warnings') { source[3].notes = ''; source[4].notes = ''; source[2].prompt += ' '; source[6] = { ...source[0] }; }
  await userEvent.upload(await canvas.findByLabelText('Training file', { exact: true }), new File([name === 'malformed.json' ? '{invalid' : JSON.stringify(source)], name, { type: 'application/json' }));
  return canvas;
}
function verified(canvasElement: HTMLElement) {
  expect(demoRequests.some(request => request.method === 'POST' && ['/api/v1/training-runs/', '/api/v1/training-runs/preflight/', '/api/v1/artifacts/', '/api/v1/datasets/'].includes(request.path))).toBe(false);
  canvasElement.dataset.demoVerified = 'passed';
}
async function ready(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await waitFor(() => expect(canvas.getByRole('button', { name: 'Preview dataset' })).toBeEnabled());
  await userEvent.click(canvas.getByRole('button', { name: 'Preview dataset' }));
  await expect(canvas.findByRole('button', { name: 'Use this dataset' })).resolves.toBeVisible();
}
export const CleanDataset: Story = { play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement); await expect(canvas.findByText(/No missing values, duplicate content or formatting issues found/)).resolves.toBeVisible();
  await ready(canvasElement); verified(canvasElement);
} };
export const WarningsOnly: Story = { parameters: { validationState: 'warnings' }, play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement, 'validation.json', 'warnings'); await expect(canvas.findByText(/Exact duplicates will be removed/)).resolves.toBeVisible();
  await expect(canvas.getByText(/unused columns do not affect training/)).toBeVisible(); await expect(canvas.getByText(/same training content as row 1/)).toBeVisible();
  await ready(canvasElement); await expect(canvas.getByText(/1 duplicate examples removed/)).toBeVisible(); verified(canvasElement);
} };
export const MissingAndFormattingErrors: Story = { parameters: { validationState: 'errors' }, play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement, 'validation.json', 'errors'); await expect(canvas.findByText(/2 of 7 rows need repair/)).resolves.toBeVisible();
  await expect(canvas.getByText(/Example 7: response must contain nonempty text/)).toBeVisible(); await expect(canvas.getByRole('button', { name: 'Preview dataset' })).toBeDisabled();
  expect(demoRequests.some(request => request.path === '/api/v1/fine-tuning/preview/')).toBe(false); verified(canvasElement);
} };
export const MappingFix: Story = { parameters: { validationState: 'mapping' }, play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement, 'validation.json', 'errors'); await expect(canvas.findByText(/2 of 7 rows need repair/)).resolves.toBeVisible();
  await userEvent.selectOptions(canvas.getByLabelText(/^Response column/), 'alternate'); await ready(canvasElement);
  expect(canvas.queryByText(/rows need repair/)).not.toBeInTheDocument(); verified(canvasElement);
} };
export const CorrectedFile: Story = { parameters: { validationState: 'errors' }, play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement, 'validation.json', 'errors'); await expect(canvas.findByText(/2 of 7 rows need repair/)).resolves.toBeVisible();
  await upload(canvasElement, 'corrected.json'); await ready(canvasElement); expect(canvas.queryByText(/rows need repair/)).not.toBeInTheDocument(); verified(canvasElement);
} };
export const ValidationRetry: Story = { parameters: { validationState: 'retry' }, play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement); await expect(canvas.findByText(/No missing values, duplicate content or formatting issues found/)).resolves.toBeVisible();
  await userEvent.selectOptions(canvas.getByLabelText(/^Response column/), 'alternate'); await expect(canvas.findByRole('alert')).resolves.toHaveTextContent('HTTP 503');
  await expect(canvas.getByRole('button', { name: 'Preview dataset' })).toBeDisabled(); await userEvent.click(canvas.getByRole('button', { name: 'Try again' }));
  await ready(canvasElement); await expect(canvas.getByLabelText(/^Response column/)).toHaveValue('alternate'); verified(canvasElement);
} };
export const MalformedFile: Story = { play: async ({ canvasElement }) => {
  const canvas = await upload(canvasElement, 'malformed.json'); await expect(canvas.findByRole('alert')).resolves.toHaveTextContent('file is malformed');
  await expect(canvas.getByRole('button', { name: 'Preview dataset' })).toBeDisabled(); await upload(canvasElement, 'corrected.json'); await ready(canvasElement); verified(canvasElement);
} };
export const Dark: Story = { ...WarningsOnly, parameters: { ...WarningsOnly.parameters, demoTheme: 'dark' } };
export const Preview: Story = WarningsOnly;
