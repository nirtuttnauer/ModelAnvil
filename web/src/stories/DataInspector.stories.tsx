import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { DataInspector, EvaluationCase, ResponseContent, TextContent } from '../components/DataInspector';
import { dataResponses } from './data-fixtures';
import '../design-system/index.css';
import './data-inspector-stories.css';

const digest = 'a3f1c2de'.repeat(8);
const evidence = {
  device: 'CPU', steps: 240, verified: true, model: 'tiny-transformer',
  manifest_digest: digest,
  configuration: { learning_rate: 0.001, batch_size: 16, mixed_precision: false },
  source_references: ['60000000-0000-4000-8000-000000000001', '60000000-0000-4000-8000-000000000002'],
};
const failedCase = {
  case_id: 'split-integrity-01', slice_name: 'source grounding', passed: false, score: 0,
  input_prompt: 'Summarize the source.\nUse only the supplied evidence.',
  candidate_output: 'The source describes a dataset.',
  expected_output: 'The source describes split integrity.',
  baseline_output: null, baseline_score: null,
  failure_reason: 'The response omitted the source’s main finding about split integrity.',
};

const meta = {
  title: 'ModelAnvil/Components/Data presentation',
  component: DataInspector,
  args: { value: evidence },
  parameters: { layout: 'fullscreen' },
  beforeEach({ parameters }) {
    document.documentElement.dataset.theme = parameters.demoTheme ?? 'light';
    delete document.getElementById('storybook-root')?.dataset.demoVerified;
  },
  decorators: [(Story) => <div className="data-story-canvas"><Story /></div>],
} satisfies Meta<typeof DataInspector>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Evidence: Story = {
  args: { title: 'Execution evidence', description: 'Recorded facts from this run.', value: evidence },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText('Learning rate')).toBeVisible();
    await expect(canvas.getByText('0.001')).toBeVisible();
    await expect(canvas.getByText('Yes')).toBeVisible();
    await expect(canvas.getByText('No', { exact: true })).toBeVisible();
    const identifier = canvas.getByRole('button', { name: 'Copy Manifest digest' });
    await expect(canvas.queryByText(digest, { exact: true })).not.toBeInTheDocument();
    identifier.focus();
    await expect(identifier).toHaveFocus();
    const tooltip = await within(document.body).findByRole('tooltip');
    await expect(within(tooltip).getByText(digest, { exact: true })).toBeVisible();
    await userEvent.keyboard('{Escape}');
    await expect(within(document.body).queryByRole('tooltip')).not.toBeInTheDocument();
    await expect(canvasElement.querySelector('pre')).toBeNull();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const Comparison: Story = {
  render: () => <EvaluationCase result={failedCase} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByText('split-integrity-01'));
    await expect(canvas.getByRole('heading', { name: 'Candidate response' })).toBeVisible();
    await expect(canvas.getByRole('heading', { name: 'Expected response' })).toBeVisible();
    await expect(canvas.getByText('The source describes split integrity.')).toBeVisible();
    await expect(canvas.getByText('Not reported', { exact: true })).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const MissingAndEmpty: Story = {
  args: { title: 'Missing and empty values', value: { missing: null, zero: 0, enabled: false, empty_text: '', empty_records: [], empty_metadata: {}, missing_field: undefined, measured_upper_bound: 0.8400000000000001 } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const text of ['0', 'No', 'Empty text', 'No items recorded', 'No fields recorded']) await expect(canvas.getByText(text, { exact: true, selector: 'span' })).toBeVisible();
    await expect(canvas.getAllByText('Not reported', { exact: true })).toHaveLength(2);
    await expect(canvas.getByText('0.84', { exact: true })).toBeVisible();
    await userEvent.click(canvas.getByText('Show exact value'));
    await expect(canvas.getByText('0.8400000000000001', { exact: true })).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const DatasetMetadata: Story = {
  args: { title: 'Revision metadata', value: (dataResponses['/api/v1/dataset-revisions/'] as { metadata: unknown }[])[0].metadata },
};

export const NestedRecords: Story = {
  args: { title: 'Recorded gate results', value: [{ name: 'Source integrity', passed: true, metrics: { overlapping_sources: 0 }, reasons: [] }, { name: 'Accuracy', passed: false, metrics: { required: 0.9, actual: 0.82 }, reasons: ['Accuracy is below the required threshold.'], supporting_records: [{ result_id: digest, slices: ['general', 'source grounding'] }] }] },
};

export const LongContent: Story = {
  render: () => <><DataInspector title="Exact source values" value={{ source_uri: 'https://example.test/' + 'long-path/'.repeat(20), text: '<script>alert("untrusted")</script>\nThis source is displayed as text.', sourceDigest: digest }} /><TextContent label="Document text" text={'A readable paragraph with the original line breaks.\n\nA second paragraph with source context.\n' + 'Evidence should remain readable at every viewport width. '.repeat(16)} /></>,
};

export const StructuredResponse: Story = {
  render: () => <><ResponseContent text={'```json\n{"answer":"The source describes split integrity.","verified":false,"source_count":0,"citations":[{"title":"Dataset preparation guide","section":"3.2"}]}\n```'} /><ResponseContent text={'{"answer": "Still streaming…'} /><ResponseContent text="42" /></>,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText('The source describes split integrity.')).toBeVisible();
    await expect(canvas.getByText('No', { exact: true })).toBeVisible();
    await expect(canvas.getByText('0', { exact: true })).toBeVisible();
    await expect(canvas.getByText('{"answer": "Still streaming…', { exact: true })).toBeVisible();
    await expect(canvas.getByText('42', { exact: true })).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ComponentBoard: Story = {
  render: () => <div className="data-story-board"><DataInspector title="Execution evidence" description="Recorded facts from this run." value={evidence} /><div><h2>Evaluation responses</h2><p className="muted">Inspect the prompt, response, and expected result together.</p><EvaluationCase result={failedCase} /><EvaluationCase result={{ ...failedCase, case_id: 'source-summary-02', passed: true, score: 1, candidate_output: failedCase.expected_output, failure_reason: '', baseline_output: 'The source describes split integrity.', baseline_score: 1 }} /></div></div>,
};

export const Narrow: Story = { ...ComponentBoard, decorators: [(Story) => <div className="data-story-narrow"><Story /></div>] };
export const Dark: Story = { ...ComponentBoard, parameters: { demoTheme: 'dark' } };
