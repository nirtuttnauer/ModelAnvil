import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within, userEvent, waitFor } from 'storybook/test';
import { App } from '../main';
import { demoHandlers, demoRequests, resetDemoRequests, type DemoState } from './demo-network';
import { resetMlFixtures } from './ml-fixtures';
import { resetWorkspaceFixtures } from './workspace-fixtures';
import { resetDataFixtures } from './data-fixtures';
import { resetOperationsFixtures } from './operations-fixtures';
import { resetDraftMemory } from '../components/Draft';
import './storybook.css';

const meta = {
  title: 'ModelAnvil/Screens',
  component: App,
  parameters: { demoRoute: '#overview' },
  beforeEach({ msw, parameters }) {
    resetDraftMemory();
    resetDemoRequests();
    resetWorkspaceFixtures();
    resetMlFixtures();
    resetOperationsFixtures();
    resetDataFixtures();
    for (const key of Object.keys(sessionStorage)) if (key.startsWith('modelanvil.draft.v1:')) sessionStorage.removeItem(key);
    localStorage.setItem('modelanvil_token', 'storybook-demo-only');
    localStorage.setItem('modelanvil_active_project', '1');
    localStorage.setItem('modelanvil_onboarding_collapsed', 'true');
    localStorage.setItem('modelanvil_theme', parameters.demoTheme ?? 'light');
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${parameters.demoRoute}`);
    delete document.getElementById('storybook-root')?.dataset.demoVerified;
    msw.use(...demoHandlers(parameters.demoState as DemoState));
  },
  decorators: [(Story, context) => <><div className="storybook-demo-banner" role="note">DEMO WORKSPACE · Synthetic data · Actions stay in this Storybook session</div><Story key={context.id} /></>],
  play: async ({ canvasElement, parameters }) => {
    const canvas = within(canvasElement);
    await expect(canvas.findByRole('heading', { name: parameters.demoHeading, level: 1 })).resolves.toBeVisible();
    await waitFor(() => expect(canvas.getByText('Assistant Research · Demo', { selector: 'option' })).toBeInTheDocument());
    await waitFor(() => expect(demoRequests.some(r => r.path === parameters.demoApiPath && r.status === 200)).toBe(true));
    await waitFor(() => expect(canvas.queryAllByRole('alert')).toHaveLength(0));
    await waitFor(() => expect(canvas.queryByText('Loading workspace data…')).not.toBeInTheDocument());
    await expect(demoRequests.filter(r => r.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
    canvasElement.dataset.demoRoute = parameters.demoRoute;
  },
} satisfies Meta<typeof App>;
export default meta;
type Story = StoryObj<typeof meta>;
const apiPaths: Record<string, string> = { Overview: 'training-runs', 'Dataset Bank': 'dataset-bank/sources', Datasets: 'datasets', Annotation: 'labeling-campaigns', Models: 'models', Training: 'fine-tuning/options', Alignment: 'alignment-runs', Evaluation: 'evaluation-runs', Workflows: 'jobs', RAG: 'index-versions', 'Context Lab': 'context-recipe-versions', Releases: 'release-versions', Infrastructure: 'worker-inventory', Budgets: 'usage-events/summary', Audit: 'audit', 'Run Detail': 'run-details/training/30000000-0000-4000-8000-000000000001' };
const route = (name: string, hash?: string) => ({ demoHeading: name === 'Overview' ? 'Project overview' : name === 'RAG' ? 'Retrieval workbench' : name, demoApiPath: `/api/v1/${apiPaths[name]}/`, demoRoute: hash ?? `#${name.toLowerCase().replaceAll(' ', '-')}` });
export const Overview: Story = { name: '01 · Overview', parameters: route('Overview') };
export const DatasetBank: Story = { name: '02 · Dataset Bank', parameters: route('Dataset Bank') };
export const Datasets: Story = { name: '03 · Datasets', parameters: route('Datasets') };
export const Annotation: Story = { name: '04 · Annotation', parameters: route('Annotation', '#annotation?campaign=60000000-0000-4000-8000-000000000001') };
export const Models: Story = { name: '05 · Models', parameters: route('Models') };
export const Training: Story = { name: '06 · Training', parameters: route('Training') };
export const Alignment: Story = { name: '07 · Alignment', parameters: route('Alignment') };
export const Evaluation: Story = { name: '08 · Evaluation', parameters: route('Evaluation') };
export const Workflows: Story = { name: '09 · Workflows', parameters: route('Workflows') };
export const Rag: Story = {
  name: '10 · RAG', parameters: route('RAG'),
  play: async ({ canvasElement, parameters }) => {
    const canvas = within(canvasElement);
    const index = await canvas.findByLabelText('Index version');
    await waitFor(() => expect(within(index).getAllByRole('option').length).toBeGreaterThan(1));
    await userEvent.selectOptions(index, '60000000-0000-4000-8000-000000000061');
    await userEvent.type(canvas.getByPlaceholderText('Search indexed knowledge chunks…'), 'dataset split integrity');
    await userEvent.click(canvas.getByRole('button', { name: 'Run query' }));
    await waitFor(() => expect(canvas.getAllByRole('button', { name: /Inspect source/ }).length).toBeGreaterThan(0));
    await expect(canvas.getByRole('heading', { name: 'Retrieval ranking' })).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
    canvasElement.dataset.demoRoute = parameters.demoRoute;
  },
};
export const ContextLab: Story = {
  name: '11 · Context Lab', parameters: route('Context Lab'),
  play: async ({ canvasElement, parameters }) => {
    const canvas = within(canvasElement);
    const recipe = await canvas.findByLabelText('Recipe version');
    await waitFor(() => expect(within(recipe).getAllByRole('option').length).toBeGreaterThan(1));
    await userEvent.selectOptions(recipe, 'a0000000-0000-4000-8000-000000000001');
    await userEvent.click(canvas.getByRole('button', { name: 'Compile Context Recipe' }));
    await expect(canvas.findByLabelText('Exact compiled prompt')).resolves.toBeVisible();
    await expect(canvas.getByText('Estimated token allocation')).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
    canvasElement.dataset.demoRoute = parameters.demoRoute;
  },
};
export const Releases: Story = { name: '12 · Releases', parameters: route('Releases') };
export const Infrastructure: Story = { name: '13 · Infrastructure', parameters: route('Infrastructure') };
export const Budgets: Story = { name: '14 · Budgets', parameters: route('Budgets') };
export const Audit: Story = { name: '15 · Audit', parameters: route('Audit') };
export const RunDetail: Story = { name: '16 · Run Detail', parameters: route('Run Detail', '#runs/training/30000000-0000-4000-8000-000000000001') };
export const Recipes: Story = { name: '17 · Recipes', parameters: { demoRoute: '#recipes', demoHeading: 'Recipes', demoApiPath: '/api/v1/recipes/' } };
export const Specialists: Story = { name: '18 · Specialists', parameters: { demoRoute: '#specialists', demoHeading: 'Specialists', demoApiPath: '/api/v1/specialists/' } };
export const RagAuthoring: Story = {
  name: '17 · RAG authoring', parameters: route('RAG'),
  play: async ({ canvasElement, parameters }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole('button', { name: 'Import documents & build index' })).toBeEnabled());
    await userEvent.click(canvas.getByRole('button', { name: 'Import documents & build index' }));
    await userEvent.selectOptions(canvas.getByLabelText('Knowledge base', { exact: true }), '60000000-0000-4000-8000-000000000051');
    await userEvent.type(canvas.getByLabelText('Document title'), 'Storybook source note');
    await userEvent.type(canvas.getByLabelText('Document text'), 'A synthetic note demonstrating pinned lexical index membership.');
    await userEvent.click(canvas.getByRole('button', { name: 'Build lexical index' }));
    await waitFor(() => expect(canvas.getByText(/Index r7 ready/)).toBeVisible());
    await userEvent.type(canvas.getByPlaceholderText('Search indexed knowledge chunks…'), 'membership');
    await userEvent.click(canvas.getByRole('button', { name: 'Run query' }));
    await waitFor(() => expect(canvas.getAllByText('A synthetic note demonstrating pinned lexical index membership.').length).toBeGreaterThan(0));
    await expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed'; canvasElement.dataset.demoRoute = parameters.demoRoute;
  },
};
export const ContextAuthoring: Story = {
  name: '18 · Context authoring', parameters: route('Context Lab'),
  play: async ({ canvasElement, parameters }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'New context recipe' }));
    await userEvent.type(canvas.getByLabelText('Recipe name'), 'Storybook grounded assistant');
    await userEvent.type(canvas.getByLabelText('System instruction'), 'Use supplied source evidence.');
    await userEvent.type(canvas.getByLabelText('Evidence template'), 'This recipe exists only in the demo session.');
    await userEvent.type(canvas.getByLabelText('Question template'), 'What is the source?');
    await userEvent.click(canvas.getByRole('button', { name: 'Save context recipe' }));
    await waitFor(() => expect(canvas.getByRole('button', { name: 'Compile Context Recipe' })).toBeEnabled());
    await userEvent.click(canvas.getByRole('button', { name: 'Compile Context Recipe' }));
    await expect(canvas.findByLabelText('Exact compiled prompt')).resolves.toHaveTextContent('This recipe exists only in the demo session.');
    await expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed'; canvasElement.dataset.demoRoute = parameters.demoRoute;
  },
};
