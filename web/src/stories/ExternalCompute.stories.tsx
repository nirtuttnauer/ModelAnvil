import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { http, HttpResponse } from 'msw';
import { ExternalCompute } from '../components/ExternalCompute';
import '../style.css';
import '../premium.css';
import '../pages/operations.css';

let allocations: Record<string, unknown>[] = [];
let submissions: Record<string, unknown>[] = [];
let failFirst = false;
const id = '90000000-0000-4000-8000-000000000001';
const compute = { id: 'runpod', kind: 'compute', name: 'Runpod Pods', digest: 'a'.repeat(64), can_manage: true, can_submit: true, configuration_schema: { properties: { gpu_id: { type: 'string' } } } };
const task = { id: 'uppercase', kind: 'task', name: 'Uppercase', digest: 'b'.repeat(64), can_manage: true, can_submit: true, configuration_schema: { properties: { text: { type: 'string' } } } };

const meta = {
  title: 'ModelAnvil/External Compute', component: ExternalCompute,
  args: { token: 'storybook-demo-only', refreshKey: 0, onChange: () => {} },
  beforeEach() { allocations = []; submissions = []; failFirst = false; compute.can_manage = true; task.can_submit = true; },
  parameters: { msw: { handlers: [http.all('/api/v1/*', async ({ request }) => {
    const path = new URL(request.url).pathname;
    if (request.method === 'GET') {
      const data: Record<string, unknown> = {
        '/api/v1/compute-plugins/': [compute, task], '/api/v1/compute-allocations/': allocations,
        '/api/v1/worker-pools/': [{ id: 1, name: 'GPU pool', status: 'active' }],
        '/api/v1/budget-policies/': [{ policy_id: id, name: 'Allocation budget', enabled: true, unit: 'allocation_seconds' }],
        '/api/v1/compute-plugins/runpod/catalog/': [{ id: 'gpu-1', name: 'H100', memory: 80, dataCenters: [{ id: 'EU-1', name: 'Europe' }] }],
      };
      return path in data ? HttpResponse.json({ results: data[path] }) : HttpResponse.json({ detail: 'Unknown fixture' }, { status: 501 });
    }
    const body = await request.json() as Record<string, unknown>;
    if (path === '/api/v1/compute-allocations/') {
      submissions.push(body);
      if (failFirst && submissions.length === 1) return HttpResponse.json({ detail: 'Synthetic uncertain response' }, { status: 503 });
      const row = { allocation_id: id, request_id: body.request_id, plugin_id: 'runpod', worker_id: 7, pool: 1, state: 'active', provider_status: 'PROVISIONING', worker_connected: false, expires_at: '2026-10-12T20:00:00Z', error_code: '' };
      allocations = [row]; return HttpResponse.json(row, { status: 201 });
    }
    if (path === `/api/v1/compute-allocations/${id}/release/`) {
      allocations = allocations.map(row => ({ ...row, state: 'released', provider_status: 'TERMINATED' }));
      return HttpResponse.json(allocations[0]);
    }
    if (path === '/api/v1/jobs/') {
      submissions.push({ ...body, idempotencyKey: request.headers.get('Idempotency-Key') });
      return HttpResponse.json({ job_id: id }, { status: 201 });
    }
    return HttpResponse.json({ detail: 'Unknown fixture' }, { status: 501 });
  })] } },
} satisfies Meta<typeof ExternalCompute>;
export default meta;
type Story = StoryObj<typeof meta>;

async function choose(canvas: ReturnType<typeof within>, plugin = 'runpod') {
  await waitFor(() => expect(canvas.getByLabelText('Provider or task')).toBeVisible());
  await userEvent.selectOptions(canvas.getByLabelText('Provider or task'), plugin);
  await userEvent.selectOptions(canvas.getByLabelText('Worker pool'), '1');
  await userEvent.selectOptions(canvas.getByLabelText('Budget'), id);
  if (plugin === 'runpod') {
    await waitFor(() => expect(canvas.getByRole('option', { name: 'H100 · 80 GB' })).toBeVisible());
    await userEvent.selectOptions(canvas.getByLabelText('GPU', { exact: true }), 'gpu-1');
    await userEvent.selectOptions(canvas.getByLabelText('Data center'), 'EU-1');
  }
}

export const ProvisionAndRelease: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await choose(canvas);
    await userEvent.click(canvas.getByRole('button', { name: 'Rent GPU' }));
    await waitFor(() => expect(canvas.getByText('No recent heartbeat')).toBeVisible());
    expect(submissions).toHaveLength(1);
    expect(submissions[0].spec).toEqual({ gpu_id: 'gpu-1', gpu_count: 1, disk_gb: 50, cloud: 'SECURE', data_center_ids: ['EU-1'] });
    await userEvent.click(canvas.getByRole('button', { name: 'Release capacity' }));
    await waitFor(() => expect(canvas.getByText('TERMINATED')).toBeVisible());
    expect(canvas.queryByRole('button', { name: 'Release capacity' })).not.toBeInTheDocument();
  },
};

export const CustomTask: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await choose(canvas, 'uppercase');
    await userEvent.clear(canvas.getByRole('textbox'));
    await userEvent.type(canvas.getByRole('textbox'), '{{"text":"hello"}');
    await userEvent.click(canvas.getByRole('button', { name: 'Run task plugin' }));
    await waitFor(() => expect(canvas.getByText('Plugin job submitted. Follow its result in Jobs.')).toBeVisible());
    expect(submissions[0].requirements).toEqual({ task_plugin: 'uppercase', task_plugin_digest: 'b'.repeat(64) });
    expect(submissions[0].payload).toEqual({ configuration: { text: 'hello' } });
    expect(submissions[0].idempotencyKey).toBeTruthy();
  },
};

export const RetryUncertainCreate: Story = {
  beforeEach() { failFirst = true; },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await choose(canvas);
    await userEvent.click(canvas.getByRole('button', { name: 'Rent GPU' }));
    await waitFor(() => expect(canvas.getByRole('alert')).toBeVisible());
    await userEvent.click(canvas.getByRole('button', { name: 'Rent GPU' }));
    await waitFor(() => expect(canvas.getByText('No recent heartbeat')).toBeVisible());
    expect(submissions).toHaveLength(2);
    expect(submissions[0]).toEqual(submissions[1]);
  },
};

export const ReadOnly: Story = {
  beforeEach() { compute.can_manage = false; task.can_submit = false; },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement); await choose(canvas);
    expect(canvas.getByRole('button', { name: 'Rent GPU' })).toBeDisabled();
    expect(canvas.getByText('Renting and releasing capacity requires an organization administrator key.')).toBeVisible();
    expect(submissions).toHaveLength(0);
  },
};
