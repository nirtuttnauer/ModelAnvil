import type { StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { http, HttpResponse } from 'msw';
import screens from './Screens.stories';
import { demoRequests } from './demo-network';
import { mlResponses } from './ml-fixtures';
import { workspaceResponses } from './workspace-fixtures';
import { draftKey, writeDraft } from '../api/drafts';
import { legacyGuidedDefaults } from '../api/training-workspace';
import { operationsResponses } from './operations-fixtures';

const versionId = '10000000-0000-4000-8000-000000000002';
const datasetId = '20000000-0000-4000-8000-000000000002';
const runId = '30000000-0000-4000-8000-000000000001';
const evaluationId = '30000000-0000-4000-8000-000000000002';
const releaseId = '60000000-0000-4000-8000-000000000003';
const trainingLineage = [{ run_id: runId, recipe: 'full_sft', status: 'completed', dataset_revision: datasetId, base_model_version: '10000000-0000-4000-8000-000000000007', output_model_version: versionId, recovery_parent: null }];
const meta = {
  ...screens, title: 'ModelAnvil/Actions/Engineering components',
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context);
    const runs = mlResponses['/api/v1/evaluation-runs/'] as Record<string, unknown>[];
    runs[0].baseline_metrics = (runs[0].metrics as Record<string, unknown>[]).map(metric => ({ ...metric, value: Number(metric.value) - 0.05 }));
    const policies = operationsResponses['/api/v1/budget-policies/'] as Record<string, unknown>[];
    policies.push({ policy_id: '50000000-0000-4000-8000-000000000011', name: 'Training steps · Demo', enabled: true, unit: 'training_steps', currency: '', limit_amount: '1000', allowance: { remaining_amount: '790' } });
    const runners = operationsResponses['/api/v1/runner-manifests/'] as Record<string, unknown>[];
    runners[0].compatibility = { ...(runners[0].compatibility as Record<string, unknown>), contract_digest: 'd'.repeat(64) };
    const releases = operationsResponses['/api/v1/release-versions/'] as Record<string, unknown>[];
    releases[0].local_review = { state: 'blocked', evaluation_run: evaluationId, production_qualified: false, criteria: [
      { key: 'held_out_accuracy', required: 0.8, actual: 0.84, passed: true },
      { key: 'license_evidence', required: 'Recorded license authority', actual: null, passed: false },
    ] };
    context.msw.use(
      http.get('/api/v1/dataset-revisions/', () => HttpResponse.json({ results: mlResponses['/api/v1/dataset-revisions/'], next: null })),
      http.get(`/api/v1/model-versions/${versionId}/`, () => HttpResponse.json((mlResponses['/api/v1/model-versions/'] as Record<string, unknown>[])[0])),
      http.get(`/api/v1/model-versions/${versionId}/lineage/`, () => HttpResponse.json({ training_runs: trainingLineage, evaluations: [{ run_id: evaluationId, status: 'completed' }], releases: [{ release_version_id: releaseId, revision_no: 3, status: 'draft' }] })),
      http.get(`/api/v1/dataset-revisions/${datasetId}/`, () => HttpResponse.json((mlResponses['/api/v1/dataset-revisions/'] as Record<string, unknown>[])[0])),
      http.get(`/api/v1/dataset-revisions/${datasetId}/inspect/`, () => HttpResponse.json({ training_runs: trainingLineage, rows: [{ sample_id: 'source-1', text: 'Exact published sample.', assigned_split: 'train' }], total: 1, next_cursor: null, capabilities: { train: true, annotate: true, limits: 'Synthetic published text revision.' } })),
      http.get('/api/v1/audit/:id/resource-state/', () => HttpResponse.json({ state: 'available', reason: 'Synthetic authorized resource.' })),
      http.get('/api/v1/audit/:id/', ({ params }) => {
        const event = (operationsResponses['/api/v1/audit/'] as Record<string, unknown>[]).find(item => item.event_id === params.id);
        return event ? HttpResponse.json(event) : HttpResponse.json({ detail: 'Synthetic event unavailable.' }, { status: 404 });
      }),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
async function ready(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await expect(canvas.findByText('Assistant Research · Demo', { selector: 'option' })).resolves.toBeInTheDocument();
  await waitFor(() => expect(canvas.queryByText('Loading project scope…')).not.toBeInTheDocument());
}
function verified(canvasElement: HTMLElement) { expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0); canvasElement.dataset.demoVerified = 'passed'; }
export const TrainingLaunch: Story = {
  parameters: { demoRoute: '#training', demoHeading: 'Training', demoApiPath: '/api/v1/training-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Advanced settings' }));
    await userEvent.selectOptions(canvas.getByLabelText('Tokenizer version', { exact: true }), '1');
    await userEvent.selectOptions(canvas.getByLabelText('Base model version', { exact: true }), '1');
    await userEvent.selectOptions(canvas.getByLabelText('Prepared dataset revision', { exact: true }), '1');
    await userEvent.selectOptions(canvas.getByLabelText('Worker execution pool'), '1');
    const budget = canvas.getByLabelText('Budget policy & limit'); const options = within(budget).getAllByRole('option').filter(option => (option as HTMLOptionElement).value && !(option as HTMLOptionElement).disabled);
    await userEvent.selectOptions(budget, (options[0] as HTMLOptionElement).value);
    await userEvent.selectOptions(canvas.getByLabelText('Registered training runner'), '1');
    await userEvent.click(canvas.getByRole('button', { name: 'Preview preflight' }));
    const preflight = await canvas.findByRole('region', { name: 'Training preflight' }); await expect(preflight).toHaveFocus();
    await userEvent.click(within(preflight).getByRole('button', { name: 'Launch fine-tuning' }));
    await expect(canvas.findByText(/Training run dispatched successfully/)).resolves.toBeVisible();
    await expect(canvas.getByRole('tab', { name: /Current run/ })).toHaveAttribute('aria-selected', 'true');
    const payload = [...demoRequests].reverse().find(request => request.path === '/api/v1/training-runs/' && request.method === 'POST')?.body;
    await expect(payload).toMatchObject({ base_model_version: 1, dataset_revision: 1, preflight_token: 'storybook-demo-preflight-only' }); verified(canvasElement);
  },
};
export const EvaluationComparison: Story = {
  parameters: { demoRoute: '#evaluation', demoHeading: 'Evaluation', demoApiPath: '/api/v1/evaluation-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    await expect(canvas.findByRole('region', { name: 'Metric comparison table' })).resolves.toBeVisible();
    const start = canvas.getByRole('button', { name: 'New evaluation' }); await waitFor(() => expect(start).toBeEnabled()); await userEvent.click(start);
    await userEvent.selectOptions(canvas.getByLabelText('Evaluation suite version'), '1');
    await userEvent.selectOptions(canvas.getByLabelText('Candidate model', { exact: true }), '1');
    await userEvent.selectOptions(canvas.getByLabelText('Baseline model (optional)', { exact: true }), '2');
    await userEvent.click(canvas.getByRole('button', { name: 'Create evaluation configuration' }));
    await expect(canvas.findByText(/Evaluation configuration created/)).resolves.toBeVisible();
    await expect([...demoRequests].reverse().find(request => request.path === '/api/v1/evaluation-runs/' && request.method === 'POST')?.body).toMatchObject({ suite_version: 1, candidate_model_version: 1, baseline_model_version: 2 }); verified(canvasElement);
  },
};
export const ModelLineage: Story = {
  parameters: { demoRoute: `#resources/model-version/${versionId}`, demoHeading: 'Resource Detail', demoApiPath: `/api/v1/model-versions/${versionId}/` },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    const lineage = await canvas.findByRole('region', { name: 'Resource lineage' });
    await expect(within(lineage).getByRole('link', { name: 'Pinned dataset revision' })).toHaveAttribute('href', `#resources/dataset-revision/${datasetId}`);
    await expect(within(lineage).getByRole('link', { name: 'Recorded evaluation' })).toHaveAttribute('href', `#runs/evaluation/${evaluationId}`);
    await expect(within(lineage).getByRole('link', { name: 'Recorded release' })).toHaveAttribute('href', `#releases?release_version=${releaseId}`); verified(canvasElement);
  },
};
export const DatasetLineage: Story = {
  parameters: { demoRoute: `#resources/dataset-revision/${datasetId}`, demoHeading: 'Resource Detail', demoApiPath: `/api/v1/dataset-revisions/${datasetId}/` },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    const lineage = await canvas.findByRole('region', { name: 'Resource lineage' });
    await expect(within(lineage).getByRole('link', { name: 'Output model version' })).toHaveAttribute('href', `#resources/model-version/${versionId}`);
    await expect(canvas.getAllByText('Exact published sample.').length).toBeGreaterThan(0); verified(canvasElement);
  },
};
export const ReleaseReview: Story = {
  parameters: { demoRoute: '#releases', demoHeading: 'Releases', demoApiPath: '/api/v1/release-versions/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    const select = await canvas.findByLabelText('Release version for SBOM'); await waitFor(() => expect(within(select).getAllByRole('option').length).toBeGreaterThan(1)); await userEvent.selectOptions(select, releaseId);
    const gates = await canvas.findByRole('region', { name: 'Release gate checklist' }); await expect(within(gates).getByText('Missing evidence')).toBeVisible();
    const inspector = canvas.getByRole('complementary', { name: 'Release · r3' });
    await expect(within(inspector).getByText('1 in loaded page')).toBeVisible();
    await expect(canvas.getAllByRole('button', { name: 'Deploy selected locally' }).every(button => (button as HTMLButtonElement).disabled)).toBe(true); verified(canvasElement);
  },
};
export const WorkerInspector: Story = {
  parameters: { demoRoute: '#infrastructure', demoHeading: 'Infrastructure', demoApiPath: '/api/v1/worker-inventory/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    const trigger = await canvas.findByRole('button', { name: 'research-worker-01' }); await userEvent.click(trigger);
    await expect(canvas.getByRole('complementary', { name: 'research-worker-01' })).toHaveFocus(); await userEvent.keyboard('{Escape}'); await expect(canvas.queryByRole('complementary', { name: 'research-worker-01' })).not.toBeInTheDocument(); await expect(trigger).toHaveFocus(); verified(canvasElement);
  },
};
export const AuditInspector: Story = {
  parameters: { demoRoute: '#audit', demoHeading: 'Audit', demoApiPath: '/api/v1/audit/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    const trigger = (await canvas.findAllByRole('button', { name: 'job_lifecycle' }))[0]; await userEvent.click(trigger);
    await expect(canvas.findByRole('complementary', { name: 'job_lifecycle' })).resolves.toHaveFocus(); await userEvent.keyboard('{Escape}'); await expect(canvas.queryByRole('complementary', { name: 'job_lifecycle' })).not.toBeInTheDocument(); await expect(trigger).toHaveFocus(); verified(canvasElement);
  },
};

export const TrainingModesAndTabs: Story = {
  parameters: { demoRoute: '#training', demoHeading: 'Training', demoApiPath: '/api/v1/training-runs/' },
  beforeEach(context) {
    context.msw.use(http.get('/api/v1/fine-tuning/options/', () => HttpResponse.json({ ...(workspaceResponses['/api/v1/fine-tuning/options/'] as object), compute: { available: true, busy: false, device: 'cpu', message: 'Synthetic local training setup for this interaction story.' } })), http.post('/api/v1/fine-tuning/setup/', () => HttpResponse.json({ inputs: {
      execution_mode: 'worker', recipe_type: 'full_sft', base_model_version: 1, tokenizer_version: 1,
      runner_manifest: 1, pool: 1, budget_policy_id: '50000000-0000-4000-8000-000000000011', initialization_seed: 42,
    } })));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Use this model' }));
    await expect(canvas.findByRole('heading', { name: 'Add your training examples' })).resolves.toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Advanced settings' }));
    await waitFor(() => expect(canvas.getByLabelText('Base model version', { exact: true })).toHaveValue('1'));
    await expect(canvas.getByLabelText('Tokenizer version', { exact: true })).toHaveValue('1');
    await userEvent.selectOptions(canvas.getByLabelText('Prepared dataset revision', { exact: true }), '1');
    await userEvent.selectOptions(canvas.getByLabelText('Training plan', { exact: true }), 'custom');
    await userEvent.clear(canvas.getByLabelText('Total steps')); await userEvent.type(canvas.getByLabelText('Total steps'), '72');
    await userEvent.click(canvas.getByRole('button', { name: 'Preview preflight' }));
    await expect(canvas.findByRole('region', { name: 'Training preflight' })).resolves.toBeVisible();
    await userEvent.clear(canvas.getByLabelText('Total steps')); await userEvent.type(canvas.getByLabelText('Total steps'), '73');
    await waitFor(() => expect(canvas.queryByRole('region', { name: 'Training preflight' })).not.toBeInTheDocument());
    await userEvent.click(canvas.getByRole('button', { name: 'Hide advanced settings' }));
    await expect(canvas.getByRole('heading', { name: 'Model and dataset selected' })).toBeVisible();
    await expect(canvas.getByLabelText('Total steps')).toHaveValue(73);
    await userEvent.click(canvas.getByRole('button', { name: 'Preview preflight' }));
    const simplePreflight = within(await canvas.findByRole('region', { name: 'Training preflight' }));
    await expect(simplePreflight.getByRole('button', { name: 'Launch fine-tuning' })).toBeEnabled();
    const checkDetails = simplePreflight.getByText('Compatibility, capacity and budget details').closest('details');
    await expect(checkDetails).not.toHaveAttribute('open');
    await userEvent.click(simplePreflight.getByText('Compatibility, capacity and budget details'));
    await expect(checkDetails).toHaveAttribute('open');
    await userEvent.click(canvas.getByRole('tab', { name: 'History' }));
    await expect(canvas.getByRole('tabpanel', { name: 'History' })).toBeVisible();
    await userEvent.click(canvas.getAllByRole('button', { name: 'View monitor' })[0]);
    await expect(canvas.getByRole('tab', { name: /Current run/ })).toHaveAttribute('aria-selected', 'true');
    await expect(canvas.getByRole('heading', { name: 'Loss & checkpoint activity' })).toBeVisible();
    const configure = canvas.getByRole('tab', { name: 'Configure' });
    await userEvent.click(configure); await userEvent.keyboard('{End}');
    await expect(canvas.getByRole('tab', { name: 'History' })).toHaveFocus();
    await userEvent.keyboard('{Home}'); await expect(configure).toHaveFocus();
    await expect(canvas.getByLabelText('Total steps')).toHaveValue(73);
    await userEvent.click(canvas.getByRole('button', { name: 'Advanced settings' }));
    await expect(canvas.getByLabelText('Prepared dataset revision', { exact: true })).toHaveValue('1');
    await expect(canvas.getByLabelText('Base model version', { exact: true })).toHaveValue('1');
    verified(canvasElement);
  },
};

export const TrainingDraftMigration: Story = {
  parameters: { demoRoute: '#training', demoHeading: 'Training', demoApiPath: '/api/v1/training-runs/' },
  beforeEach() {
    writeDraft(sessionStorage, draftKey('demo-tenant', '1', 'guided-fine-tune'), {
      ...legacyGuidedDefaults, stage: 3, steps: 73, preset: 'custom', modelName: 'Saved model', name: 'Saved dataset', runId,
      inputsJson: JSON.stringify({ execution_mode: 'worker', recipe_type: 'full_sft', base_model_version: 1, tokenizer_version: 1,
        runner_manifest: 1, pool: 1, budget_policy_id: '50000000-0000-4000-8000-000000000011', initialization_seed: 42 }),
      revisionJson: JSON.stringify({ id: 1, dataset_name: 'Saved dataset', row_count: 10, metadata: { split_counts: { train: 8, validation: 1, test: 1 } } }),
    }, legacyGuidedDefaults);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    await waitFor(() => expect(canvas.getByRole('tab', { name: /Current run/ })).toHaveAttribute('aria-selected', 'true'));
    await waitFor(() => expect(canvas.getByLabelText('Current training run')).toHaveValue(runId));
    await userEvent.click(canvas.getByRole('tab', { name: 'Configure' }));
    await expect(canvas.getByLabelText('Total steps')).toHaveValue(73);
    await userEvent.click(canvas.getByRole('button', { name: 'Advanced settings' }));
    await expect(canvas.getByLabelText('Base model version', { exact: true })).toHaveValue('1');
    await expect(canvas.getByLabelText('Prepared dataset revision', { exact: true })).toHaveValue('1');
    await expect(sessionStorage.getItem(draftKey('demo-tenant', '1', 'guided-fine-tune'))).toBeNull();
    verified(canvasElement);
  },
};

export const TrainingCurrentRunAndHistory: Story = {
  parameters: { demoRoute: '#training?tab=current-run', demoHeading: 'Training', demoApiPath: '/api/v1/training-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await ready(canvasElement);
    const activeId = '30000000-0000-4000-8000-000000000004';
    await waitFor(() => expect(canvas.getByLabelText('Current training run')).toHaveValue(activeId));
    await userEvent.click(canvas.getByRole('button', { name: 'Cancel run' }));
    await expect(canvas.findByText('Run cancelled.')).resolves.toBeVisible();
    await userEvent.click(canvas.getByRole('tab', { name: 'History' }));
    await expect(canvas.getAllByText('cancelled', { selector: '.state' }).length).toBeGreaterThan(0);
    await userEvent.click(canvas.getAllByRole('button', { name: 'Inspect run' })[0]);
    await expect(canvas.getByRole('heading', { name: 'Training run 2' })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Close details' }));
    await expect(canvas.queryByRole('heading', { name: 'Training run 2' })).not.toBeInTheDocument();
    verified(canvasElement);
  },
};
