import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { http, HttpResponse } from 'msw';
import { RunDetailPage } from '../pages/RunDetailPage';
import { DraftScope } from '../components/Draft';
import { workspaceResponses } from './workspace-fixtures';
import '../design-system/index.css';

const id = '30000000-0000-4000-8000-000000000001';
const path = `/api/v1/run-details/training/${id}/`;
let reads = 0;
const detail = workspaceResponses[path] as Record<string, unknown>;
const attempts = Array.from({ length: 60 }, (_, index) => ({
  attempt_id: `synthetic-attempt-${index}`, job_id: '40000000-0000-4000-8000-000000000001',
  worker: `Synthetic worker ${index}`, worker_status: 'offline', status: 'expired', progress: 0.4,
  error: 'Synthetic lost lease; prior evidence retained.', lease_expires_at: null,
  started_at: '2026-10-11T09:15:00Z', completed_at: '2026-10-11T09:24:00Z', has_result: false,
}));
const meta = {
  title: 'ModelAnvil/Run recovery', component: RunDetailPage,
  args: { token: 'storybook-demo-only', kind: 'training', runId: id },
  decorators: [(Story) => <DraftScope.Provider value={{ organization: 'synthetic-recovery', project: '1' }}><Story /></DraftScope.Provider>],
  beforeEach() { reads = 0; },
  parameters: { msw: { handlers: [http.get('/api/v1/run-details/training/:id/*', ({ request }) => {
    const url = new URL(request.url);
    if (url.pathname.endsWith('/attempts/')) {
      const following = url.searchParams.has('cursor');
      return HttpResponse.json({ count: 60, results: following ? attempts.slice(50) : attempts.slice(0, 50),
        next: following ? null : `${path}attempts/?cursor=synthetic-next`, previous: null });
    }
    reads += 1;
    if (reads === 2) return HttpResponse.json({ detail: 'Synthetic transient connection failure.' }, { status: 503 });
    return HttpResponse.json({ ...detail, observed: { ...(detail.observed as object), state: 'running' } });
  })] } },
} satisfies Meta<typeof RunDetailPage>;
export default meta;
type Story = StoryObj<typeof meta>;

export const LongHistoryAndConnectionRecovery: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByText(/^Attempts \(/, { selector: 'summary' }));
    const more = await canvas.findByRole('button', { name: 'Load more attempts' });
    await userEvent.click(more);
    await waitFor(() => expect(canvas.getByText('Synthetic worker 59', { exact: true })).toBeVisible());
    expect(canvas.queryByRole('button', { name: 'Load more attempts' })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByText('Recovery note', { selector: 'summary' }));
    const note = canvas.getByRole('textbox', { name: 'What you observed and what you tried' });
    await userEvent.clear(note); await userEvent.type(note, 'Preserve my recovery investigation.');
    await waitFor(() => expect(canvas.getByText(/Live updates interrupted/)).toBeVisible(), { timeout: 15000 });
    expect(note).toHaveValue('Preserve my recovery investigation.');
    expect(canvas.getByText('Synthetic worker 59', { exact: true })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(canvas.queryByText(/Live updates interrupted/)).not.toBeInTheDocument());
    expect(note).toHaveValue('Preserve my recovery investigation.');
    expect(canvas.getByText('Synthetic worker 59', { exact: true })).toBeVisible();
    expect(canvas.queryByRole('button', { name: 'Load more attempts' })).not.toBeInTheDocument();
    canvasElement.dataset.demoVerified = 'true';
  },
};
