import type { StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import screens from './Screens.stories';
import { DraftStatus } from '../components/Draft';
import { http, HttpResponse } from 'msw';

const meta = { ...screens, title: 'ModelAnvil/Actions/Compact screens' };
export default meta;
type Story = StoryObj<typeof meta>;
const passed = (element: HTMLElement) => { element.dataset.demoVerified = 'passed'; };

export const FirstTrainingSetup: Story = { parameters: { demoRoute: '#training' }, beforeEach(context) {
  screens.beforeEach(context);
  context.msw.use(http.get('/api/v1/training-runs/', () => HttpResponse.json({ results: [], next: null })));
}, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.findByRole('button', { name: 'Use this model' })).resolves.toBeVisible();
  await waitFor(() => expect(canvas.queryByLabelText('Loaded training summary')).not.toBeInTheDocument());
  expect(canvas.queryByRole('complementary', { name: 'Run summary' })).not.toBeInTheDocument();
  expect(canvas.queryByLabelText('Training plan')).not.toBeInTheDocument();
  await waitFor(() => expect(canvas.getAllByRole('button', { name: 'New training run', hidden: true }).length).toBeGreaterThan(0));
  for (const button of canvas.getAllByRole('button', { name: 'New training run', hidden: true })) await expect(button).not.toBeVisible();
  passed(canvasElement);
} };

export const DatasetUpload: Story = { parameters: { demoRoute: '#datasets' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.findByRole('heading', { name: 'Upload and prepare a dataset', level: 2 })).resolves.toBeVisible();
  await expect(canvas.findByText('Assistant Research · Demo', { selector: 'option' })).resolves.toBeInTheDocument();
  const name = canvas.getByLabelText('Dataset name');
  await expect(name).toBeVisible();
  await waitFor(() => expect(name).toBeEnabled());
  await userEvent.type(name, 'My custom examples');
  await expect(canvas.findByText('Draft saved in this tab')).resolves.toBeVisible();
  await expect(canvas.getByLabelText('Validation percentage')).not.toBeVisible();
  await userEvent.click(canvas.getByText('Split and cleanup options', { selector: 'summary' }));
  await expect(canvas.getByLabelText('Validation percentage')).toBeVisible();
  await expect(name).toHaveValue('My custom examples');
  await expect(canvas.getByLabelText('Source file')).toBeEnabled();
  await expect(canvas.getByText('Choose file')).toBeVisible();
  passed(canvasElement);
} };

export const ModelCatalog: Story = { parameters: { demoRoute: '#models' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.findByRole('heading', { name: 'Models', level: 1 })).resolves.toBeVisible();
  await expect(canvas.queryByRole('dialog', { name: 'Add a model' })).not.toBeInTheDocument();
  const add = await canvas.findByRole('button', { name: 'Add model' });
  await waitFor(() => expect(add).toBeEnabled());
  await userEvent.click(add);
  const dialog = await canvas.findByRole('dialog', { name: 'Add a model' });
  await expect(within(dialog).getByRole('button', { name: 'Hugging Face' })).toBeVisible();
  await userEvent.keyboard('{Escape}');
  await waitFor(() => expect(canvas.queryByRole('dialog', { name: 'Add a model' })).not.toBeInTheDocument());
  await expect(canvas.getByText('Model runtime compatibility', { selector: 'summary' })).not.toBeVisible();
  await userEvent.click(canvas.getByText('Advanced', { selector: 'summary' }));
  await userEvent.click(canvas.getByText('Model runtime compatibility', { selector: 'summary' }));
  await expect(canvas.findByText('Anvil Assistant · r8')).resolves.toBeVisible();
  passed(canvasElement);
} };

export const WorkflowDetails: Story = { parameters: { demoRoute: '#workflows' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  const trigger = (await canvas.findAllByRole('button', { name: 'Inline details' }))[0];
  await expect(canvas.getByText('Observed execution states', { selector: 'h3' })).not.toBeVisible();
  await userEvent.click(trigger);
  const panel = await canvas.findByRole('complementary', { name: 'Anvil Assistant · SFT demo' });
  await waitFor(() => expect(panel).toHaveFocus());
  await userEvent.keyboard('{Escape}');
  expect(panel).not.toBeInTheDocument();
  await expect(trigger).toHaveFocus();
  await userEvent.click(canvas.getByText('Execution overview', { selector: 'summary' }));
  await expect(canvas.getByRole('heading', { name: 'Observed execution states' })).toBeVisible();
  passed(canvasElement);
} };

export const AuditFilters: Story = { parameters: { demoRoute: '#audit' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.findByRole('heading', { name: 'Events' })).resolves.toBeVisible();
  await expect(canvas.getByLabelText('Actor ID')).not.toBeVisible();
  const toggle = canvas.getByText('More audit filters', { selector: 'summary' });
  await userEvent.click(toggle); await userEvent.type(canvas.getByLabelText('Actor ID'), 'reviewer-42');
  await userEvent.click(toggle); await userEvent.click(toggle);
  await expect(canvas.getByLabelText('Actor ID')).toHaveValue('reviewer-42');
  await userEvent.click(canvas.getByText('Activity overview', { selector: 'summary' }));
  await expect(canvas.getByRole('heading', { name: 'Event volume' })).toBeVisible();
  passed(canvasElement);
} };

export const SourceInspector: Story = { parameters: { demoRoute: '#dataset-bank' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  const inspect = (await canvas.findAllByRole('button', { name: /^Inspect / }))[0];
  await userEvent.click(inspect);
  await waitFor(() => expect(canvas.getByRole('region', { name: 'Source details' })).toHaveFocus());
  passed(canvasElement);
} };

export const RecipeSteps: Story = { parameters: { demoRoute: '#recipes' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  const toggle = await canvas.findByText('2. sample · sample', { selector: 'summary' });
  await expect(canvas.getByLabelText('Sampler seed')).not.toBeVisible();
  await userEvent.click(toggle);
  const seed = canvas.getByLabelText('Sampler seed');
  await userEvent.clear(seed); await userEvent.type(seed, '43');
  await userEvent.click(toggle); await userEvent.click(toggle);
  await expect(seed).toHaveValue(43);
  await expect(canvas.getByRole('img', { name: 'Recipe dependencies; editable list follows', hidden: true })).not.toBeVisible();
  await userEvent.click(canvas.getByText('Recipe dependency map', { selector: 'summary' }));
  await expect(canvas.getByRole('img', { name: 'Recipe dependencies; editable list follows' })).toBeVisible();
  passed(canvasElement);
} };

export const ContextOverrides: Story = { parameters: { demoRoute: '#context-lab' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  const versions = await canvas.findByLabelText('Recipe version');
  await waitFor(() => expect(within(versions).getAllByRole('option').length).toBeGreaterThan(1));
  await userEvent.selectOptions(versions, 'a0000000-0000-4000-8000-000000000001');
  const toggle = canvas.getByText('Override saved context (optional)', { selector: 'summary' });
  await userEvent.click(toggle);
  await userEvent.click(canvas.getByLabelText('Override System', { exact: true }));
  const input = canvas.getByLabelText('System override', { exact: true });
  await userEvent.clear(input); await userEvent.type(input, 'Use the published evidence.');
  await userEvent.click(toggle); await userEvent.click(toggle);
  await expect(input).toHaveValue('Use the published evidence.');
  passed(canvasElement);
} };

export const UnsavedDraft: Story = { render: () => <DraftStatus draft={{ status: 'unsaved', restore() {}, discard() {} }} />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.getByRole('status')).toHaveTextContent('Draft is unsaved');
  await expect(canvas.getByRole('button', { name: 'Discard draft' })).toBeVisible();
  await expect(canvas.getByText(/Drafts use this tab’s session storage/)).toBeVisible();
  passed(canvasElement);
} };
