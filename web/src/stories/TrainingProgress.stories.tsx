import type { StoryObj } from '@storybook/react-vite';
import { http, HttpResponse } from 'msw';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import screens from './Screens.stories';
import { mlResponses } from './ml-fixtures';

const runId = '30000000-0000-4000-8000-000000000004';
const meta = {
  ...screens, title: 'ModelAnvil/Actions/Training progress',
  parameters: { demoRoute: `#training?tab=current-run&run=${runId}`, demoHeading: 'Training', demoApiPath: '/api/v1/training-runs/' },
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context);
    const original = (mlResponses['/api/v1/training-runs/'] as Record<string, unknown>[]).find(run => run.run_id === runId)!;
    let reads = 0;
    const state = context.parameters.progressState;
    const started = Date.now() - 60000;
    context.msw.use(
      http.get('/api/v1/dataset-revisions/', () => HttpResponse.json({ results: mlResponses['/api/v1/dataset-revisions/'], next: null })),
      http.get('/api/v1/training-runs/', () => {
        reads++;
        if (state === 'interrupted' && reads === 2) return HttpResponse.json({ detail: 'Demo connection interrupted' }, { status: 503 });
        const step = state === 'live' ? Math.min(80, 20 + 10 * (reads - 1)) : ['completed', 'small-loss'].includes(state) ? 80 : state === 'queued' ? 0 : 20;
        const pending = state === 'queued', stopped = state === 'failed' || state === 'cancelled';
        const status = step === 80 ? 'completed' : pending ? 'pending' : stopped ? state : 'running';
        const metrics = state === 'missing' ? [] : Array.from({ length: Math.floor(step / 10) }, (_, i) => ({
          step: (i + 1) * 10, loss: 3 / (i + 1), validation_loss: 3.4 / (i + 1),
          measured_at: new Date(Date.now() - (step - (i + 1) * 10) * 300).toISOString(),
          engine_wall_seconds: 3, updates_since_checkpoint: 10,
        }));
        return HttpResponse.json({ results: [{ ...original, runtime: { execution_mode: state === 'synthetic' ? 'simulation' : 'worker' },
          status, current_step: step, progress_step: pending || stopped || step === 80 ? step : step + 2, total_steps: 80,
          latest_loss: metrics.at(-1)?.loss ?? null, metrics_log: metrics, started_at: pending ? null : new Date(started).toISOString(),
          completed_at: stopped || status === 'completed' ? new Date().toISOString() : null,
          output_model_version: null, output_model_version_uuid: null, quality_summary: state === 'small-loss' ? { selected_step: 80, baseline_loss: 3.838, validation_loss: 0.0003534, validation_examples: 6 } : null,
          checkpoints: metrics.map(row => ({ checkpoint_id: `demo-${row.step}`, step: row.step, is_valid: true, state_digest: 'd'.repeat(64) })) }], next: null });
      }),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
const check = (text: string): Story['play'] => async ({ canvasElement }) => {
  const card = within(await within(canvasElement).findByRole('region', { name: 'Live training progress' }));
  await expect(card.getByText(text, { exact: true })).toBeVisible();
  canvasElement.dataset.demoVerified = 'passed';
};
export const LiveRun: Story = {
  parameters: { progressState: 'live' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const card = within(await canvas.findByRole('region', { name: 'Live training progress' }));
    await expect(card.getByText('27% complete')).toBeVisible();
    await expect(card.getByText(/^About /)).toBeVisible();
    await expect(canvas.getByRole('button', { name: /^Validation loss$/ })).toBeVisible();
    await waitFor(() => expect(card.getByText('40% complete')).toBeVisible(), { timeout: 7000 });
    await expect(card.getByText('30 steps saved in checkpoints · 2 additional steps reported by the worker.')).toBeVisible();
    await expect(canvas.getByRole('button', { name: /^Training loss: Committed step 30,/ })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: /^Validation loss$/ }));
    await expect(canvas.queryByRole('button', { name: /^Validation loss: Committed step 30,/ })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole('button', { name: /^Validation loss$/ }));
    await expect(canvas.getByRole('button', { name: /^Validation loss: Committed step 30,/ })).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const Queued: Story = { parameters: { progressState: 'queued' }, play: check('Waiting to start') };
export const MissingMetrics: Story = { parameters: { progressState: 'missing' }, play: check('Waiting for measured step timings') };
export const Completed: Story = { parameters: { progressState: 'completed' }, play: check('Finished') };
export const SmallValidationLoss: Story = { parameters: { progressState: 'small-loss' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.findByText('Validation loss: 3.838 before training → 0.0003534 for the selected model. Lower is better.')).resolves.toBeVisible();
  canvasElement.dataset.demoVerified = 'passed';
} };
export const Failed: Story = { parameters: { progressState: 'failed' }, play: check('Run stopped') };
export const Cancelled: Story = { parameters: { progressState: 'cancelled' }, play: check('Run stopped') };
export const Synthetic: Story = { parameters: { progressState: 'synthetic' }, play: check('Unavailable for synthetic runs') };
export const InterruptedThenRecovered: Story = {
  parameters: { progressState: 'interrupted' },
  play: async ({ canvasElement }) => {
    const card = within(await within(canvasElement).findByRole('region', { name: 'Live training progress' }));
    await waitFor(() => expect(card.getByText('Updates interrupted')).toBeVisible(), { timeout: 7000 });
    await expect(card.getByText('Waiting for a fresh update')).toBeVisible();
    await expect(card.getByText('27% complete')).toBeVisible();
    await userEvent.click(card.getByRole('button', { name: 'Refresh progress' }));
    await waitFor(() => expect(card.queryByRole('alert')).not.toBeInTheDocument());
    await expect(card.getByText(/^About /)).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const Dark: Story = { parameters: { progressState: 'steady', demoTheme: 'dark' }, play: check('27% complete') };
export const Preview: Story = { parameters: { progressState: 'live' }, play: check('27% complete') };
