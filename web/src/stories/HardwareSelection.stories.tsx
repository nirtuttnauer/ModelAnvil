import type { StoryObj } from '@storybook/react-vite';
import { http, HttpResponse } from 'msw';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import screens from './Screens.stories';
import { mlResponses } from './ml-fixtures';
import { workspaceResponses } from './workspace-fixtures';
import { demoRequests } from './demo-network';

const gib = 1024**3;
const profile = { host_memory_bytes: 8 * gib, accelerator_memory_bytes: 4 * gib,
  accelerator_backends: ['cuda', 'mps'], runtime_contract: 'storybook-hardware-contract', basis: 'Synthetic training profile for UI testing. Preflight checks live headroom and exact inputs.' };
const memory = { weights_bytes: gib, training: profile };
const meta = {
  ...screens, title: 'ModelAnvil/Actions/Model hardware',
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context);
    const models = mlResponses['/api/v1/model-versions/'] as Record<string, unknown>[];
    models[0].capabilities = { ...(models[0].capabilities as object), memory_requirements: memory };
    context.msw.use(
      http.get('/api/v1/dataset-revisions/', () => HttpResponse.json({ results: mlResponses['/api/v1/dataset-revisions/'], next: null })),
      http.get('/api/v1/worker-inventory/', () => HttpResponse.json({ results: [
        { id: 1, name: 'GPU worker · Demo', pool: 1, pool_name: 'Research', status: 'available', connection_state: 'connected', last_heartbeat_at: new Date().toISOString(), capabilities: { training_runtime: profile.runtime_contract, memory_bytes: 16 * gib, gpu_backend: 'cuda', gpu_memory_bytes: 8 * gib, model_import: true } },
        { id: 2, name: 'Small GPU · Demo', pool: 2, pool_name: 'Evaluation', status: 'available', connection_state: 'connected', last_heartbeat_at: new Date().toISOString(), capabilities: { training_runtime: profile.runtime_contract, memory_bytes: 4 * gib, gpu_backend: 'cuda', gpu_memory_bytes: 2 * gib } },
      ], next: null })),
      http.get('/api/v1/fine-tuning/options/', () => HttpResponse.json({ ...(workspaceResponses['/api/v1/fine-tuning/options/'] as { model: object }),
        compute: { available: true, busy: false, device: 'mps:0', message: 'Synthetic local hardware report.', memory_bytes: 16 * gib, memory_observed_at: new Date().toISOString() },
        model: { ...(workspaceResponses['/api/v1/fine-tuning/options/'] as { model: object }).model, memory_requirements: { weights_bytes: null, training: profile } } })),
      http.post('/api/v1/model-imports/inspect/', () => HttpResponse.json({ repo_id: 'storybook/model', revision: 'f'.repeat(40), task: 'text-generation', license: 'apache-2.0', gated: false, architecture: 'llama',
        format: 'safetensors', byte_size: gib + 512, parameters_count: 135000000, files: { 'model.safetensors': {}, 'config.json': {} }, training_supported: true, memory_requirements: memory })),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
function verified(canvasElement: HTMLElement) {
  expect(demoRequests.some(request => request.path === '/api/v1/training-runs/preflight/' && request.method === 'POST')).toBe(false);
  expect(demoRequests.some(request => request.path === '/api/v1/training-runs/' && request.method === 'POST')).toBe(false);
  canvasElement.dataset.demoVerified = 'passed';
}
export const RecommendedModelMemory: Story = {
  parameters: { demoRoute: '#training', demoHeading: 'Training', demoApiPath: '/api/v1/fine-tuning/options/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(await canvas.findByRole('region', { name: 'Model hardware fit' }));
    await waitFor(() => expect(card.getByText('Host memory fits · accelerator memory unknown')).toBeVisible());
    await expect(card.getByText('16 GiB')).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Use this model' })).toBeVisible();
    verified(canvasElement);
  },
};
export const AdvancedModelAndPool: Story = {
  parameters: { demoRoute: '#training', demoHeading: 'Training', demoApiPath: '/api/v1/model-versions/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Advanced settings' }));
    const base = canvas.getByLabelText('Base model version', { exact: true });
    await waitFor(() => expect(within(base).getAllByRole('option').length).toBeGreaterThan(1));
    await userEvent.selectOptions(base, '1');
    await waitFor(() => expect(canvas.getByText('Meets declared memory minimum')).toBeVisible());
    await userEvent.selectOptions(canvas.getByLabelText('Worker execution pool'), '2');
    await expect(canvas.getByText('Memory minimum not met')).toBeVisible();
    await userEvent.selectOptions(canvas.getByLabelText('Recipe type'), 'qlora_adapter');
    await expect(canvas.getByText('Training compatibility unavailable')).toBeVisible();
    verified(canvasElement);
  },
};
export const HubSnapshotMemory: Story = {
  parameters: { demoRoute: '#models', demoHeading: 'Models', demoApiPath: '/api/v1/model-versions/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Hugging Face' }));
    await userEvent.type(canvas.getByLabelText('Repository'), 'storybook/model');
    await userEvent.type(canvas.getByLabelText('Commit revision'), 'f'.repeat(40));
    await userEvent.click(canvas.getByRole('button', { name: 'Inspect snapshot' }));
    const card = within(await canvas.findByRole('region', { name: 'Model hardware fit' }));
    await waitFor(() => expect(card.getByText('Meets declared memory minimum')).toBeVisible());
    await expect(card.getByText('1 GiB')).toBeVisible();
    await expect(card.getByText(/storage measurement, not runtime RAM or VRAM/)).toBeVisible();
    verified(canvasElement);
  },
};
