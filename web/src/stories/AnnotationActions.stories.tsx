import type { StoryObj } from '@storybook/react-vite';
import { expect, fn, userEvent, waitFor, within } from 'storybook/test';
import { http, HttpResponse } from 'msw';
import screens from './Screens.stories';
import { dataResponses } from './data-fixtures';
import type { AnnotationTask, Review } from '../api/annotation';

const campaignId = '60000000-0000-4000-8000-000000000001';
const batchId = '60000000-0000-4000-8000-000000000010';
const modelId = '10000000-0000-4000-8000-000000000002';
const id = (number: number) => `61000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
const sourceId = (number: number) => `019a3621-4d78-7bd0-8e43-${String(number).padStart(12, '0')}`;
const stamp = '2026-10-18T08:00:00Z';
const classes = ['Helpful', 'Needs correction', 'Off topic'];
function fixtureCampaign() {
  return {
    ...structuredClone(dataResponses[`/api/v1/labeling-campaigns/${campaignId}/`] as Record<string, unknown>),
    campaign_id: campaignId, name: 'Annotation interaction review', status: 'active', current_cycle: 0,
    max_cycles: 3, active_model_id: modelId, label_schema: { kind: 'classification', classes },
    snapshots: [], configuration: { audit_sample_refs: [] },
    batches: [{ batch_id: batchId, cycle_no: 1, status: 'reviewing', sample_count: 55, reviewed_count: 0, approved_count: 0, drafting_model_id: modelId }],
  };
}
let campaigns = [fixtureCampaign()];
let tasks: AnnotationTask[] = [];
let reviews: Array<{ taskId: string; body: Record<string, unknown> }> = [];
let pages: number[] = [];
let histories: Record<string, Review[]> = {};
let conflictOnce = false;
function record(task: AnnotationTask, label: string, revision: number): Review {
  return { record_id: id(5000 + revision), revision_no: revision, reviewer_id: 'api_key:demo',
    human_label: { label }, original_prediction: task.content.draft_prediction || {}, decision: 'corrected', created_at: stamp };
}
function responseTask(task: AnnotationTask, request: Request, blind = false) {
  const result = structuredClone(task);
  if (blind || new URL(request.url).searchParams.get('blind') === '1') {
    delete result.content.draft_prediction; delete result.content.arena_vote; delete result.content.comparison_origin;
    if (result.latest_review) result.latest_review = { ...result.latest_review, human_label: {}, original_prediction: {} };
  }
  return result;
}

const meta = {
  ...screens,
  title: 'ModelAnvil/Actions/Annotation',
  parameters: { demoRoute: `#annotation?campaign=${campaignId}`, demoHeading: 'Annotation', demoApiPath: '/api/v1/labeling-campaigns/' },
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context);
    campaigns = [fixtureCampaign()]; reviews = []; pages = []; histories = {};
    conflictOnce = !!context.parameters.annotationConflict;
    tasks = Array.from({ length: 55 }, (_, index) => ({
      task_id: id(index + 1), sample_ref: context.parameters.annotationOpaqueSamples ? sourceId(index + 1) : `sample-${index + 1}`, assigned_reviewer: '', needs_adjudication: false,
      status: 'drafted', latest_review: null,
      content: { text: index === 50 ? 'Needle source content beyond the first page' : `Source for sample ${index + 1}`,
        draft_prediction: { predicted_label: 'Helpful', model_version_id: modelId },
        arena_vote: { choice: 'Helpful' }, comparison_origin: { winner: 'Helpful' } },
    }));
    context.msw.use(
      http.get('/api/v1/labeling-campaigns/', () => HttpResponse.json({ results: campaigns, next: null, count: campaigns.length })),
      http.get('/api/v1/labeling-campaigns/:campaignId/', ({ params }) => HttpResponse.json(campaigns.find(campaign => campaign.campaign_id === params.campaignId))),
      http.post('/api/v1/labeling-campaigns/', async ({ request }) => {
        const body = await request.json() as { name: string; classes: string[] };
        const created = { ...fixtureCampaign(), campaign_id: id(9000), name: body.name, active_model_id: '',
          label_schema: { kind: 'classification', classes: body.classes }, batches: [] };
        campaigns.unshift(created);
        return HttpResponse.json(created, { status: 201 });
      }),
      http.get('/api/v1/labeling-batches/:batchId/tasks/', ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get('cursor') || 1); pages.push(page);
        return HttpResponse.json({ results: tasks.slice((page - 1) * 50, page * 50).map(task => responseTask(task, request)),
          count: tasks.length, next: page === 1 ? `/api/v1/labeling-batches/${batchId}/tasks/?cursor=2${new URL(request.url).searchParams.get('blind') === '1' ? '&blind=1' : ''}` : null });
      }),
      http.get('/api/v1/annotation-tasks/:taskId/', ({ request, params }) => HttpResponse.json(responseTask(tasks.find(task => task.task_id === params.taskId)!, request))),
      http.get('/api/v1/annotation-tasks/:taskId/assignment/', () => HttpResponse.json({ reviewers: [{ principal_id: 'api_key:demo', name: 'Demo reviewer' }] })),
      http.get('/api/v1/annotation-tasks/:taskId/history/', ({ request, params }) => {
        const rows = histories[String(params.taskId)] || [];
        const blind = new URL(request.url).searchParams.get('blind') === '1';
        return HttpResponse.json({ results: rows.map(row => blind ? { ...row, human_label: {}, original_prediction: {} } : row), next: null, count: rows.length });
      }),
      http.post('/api/v1/annotation-tasks/:taskId/review/', async ({ request, params }) => {
        const task = tasks.find(item => item.task_id === params.taskId)!;
        const body = await request.json() as { human_label: { label: string }; expected_revision: number; blind_review?: boolean };
        reviews.push({ taskId: task.task_id, body });
        if (conflictOnce) {
          conflictOnce = false; task.latest_review = record(task, 'Off topic', 1); task.status = 'completed';
          histories[task.task_id] = [task.latest_review]; campaigns[0].batches[0].reviewed_count = 1;
          return HttpResponse.json({ error: { code: 'conflict', message: 'Another reviewer changed this task. Refresh before submitting again.' } }, { status: 409 });
        }
        if (body.expected_revision !== (task.latest_review?.revision_no || 0) + 1) return HttpResponse.json({ detail: 'Stale review' }, { status: 409 });
        if (!task.latest_review) campaigns[0].batches[0].reviewed_count++;
        task.latest_review = record(task, body.human_label.label, body.expected_revision); task.status = 'completed';
        histories[task.task_id] = [...histories[task.task_id] || [], task.latest_review];
        return HttpResponse.json(responseTask(task, request, body.blind_review), { status: 201 });
      }),
      http.post('/api/v1/annotation-tasks/:taskId/escalate/', ({ request, params }) => {
        const task = tasks.find(item => item.task_id === params.taskId)!; task.needs_adjudication = true;
        return HttpResponse.json(responseTask(task, request));
      }),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
const queueButton = (canvas: ReturnType<typeof within>, number: number) => canvas.getByRole('button', { name: new RegExp(`^sample-${number} `) });
const editor = (canvas: ReturnType<typeof within>, number: number) => canvas.getByRole('region', { name: `Review sample sample-${number}` });

export const QueueKeyboardAndDrafts: Story = {
  name: 'Paginated queue, keyboard save, and preserved drafts',
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.findByText('55 of 55 samples')).resolves.toBeVisible();
    await expect(pages).toEqual(expect.arrayContaining([1, 2]));
    await userEvent.type(canvas.getByLabelText('Find sample'), 'Needle source content');
    await expect(canvas.findByText('1 of 55 samples')).resolves.toBeVisible();
    await userEvent.click(queueButton(canvas, 51));
    await userEvent.clear(canvas.getByLabelText('Find sample'));
    editor(canvas, 51).focus();
    await userEvent.keyboard('2{Control>}{Enter}{/Control}');
    await waitFor(() => expect(editor(canvas, 52)).toBeVisible());
    await expect(reviews[0].body).toMatchObject({ expected_revision: 1, human_label: { label: 'Needs correction' } });
    await userEvent.click(queueButton(canvas, 51));
    await expect(canvas.getByRole('radio', { name: /Needs correction/ })).toBeChecked();
    await userEvent.click(queueButton(canvas, 52));
    await userEvent.click(canvas.getByRole('radio', { name: /Off topic/ }));
    await userEvent.click(queueButton(canvas, 53));
    await userEvent.click(queueButton(canvas, 52));
    await expect(canvas.getByRole('radio', { name: /Off topic/ })).toBeChecked();
    await expect(reviews).toHaveLength(1);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ConflictRecovery: Story = {
  name: 'Preserve draft through concurrent review conflict',
  parameters: { annotationConflict: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.findByText('55 of 55 samples')).resolves.toBeVisible();
    await userEvent.click(canvas.getByRole('checkbox', { name: 'Next awaiting sample after save' }));
    await userEvent.click(canvas.getByRole('radio', { name: /Needs correction/ }));
    await userEvent.click(canvas.getByRole('button', { name: 'Save label' }));
    await expect(canvas.findByRole('button', { name: 'Refresh latest review' })).resolves.toBeVisible();
    await expect(canvas.getByRole('radio', { name: /Needs correction/ })).toBeChecked();
    await expect(canvas.getByRole('button', { name: 'Save label' })).toBeDisabled();
    await userEvent.click(canvas.getByRole('button', { name: 'Refresh latest review' }));
    const keep = await canvas.findByRole('button', { name: 'Keep my label against latest revision' });
    await waitFor(() => expect(keep).toBeEnabled());
    await expect(canvas.getByRole('button', { name: 'Save label' })).toBeDisabled();
    await userEvent.click(keep);
    await userEvent.click(canvas.getByRole('button', { name: 'Save label' }));
    await waitFor(() => expect(reviews).toHaveLength(2));
    await expect(reviews[1].body).toMatchObject({ expected_revision: 2, human_label: { label: 'Needs correction' } });
    await expect(canvas.findByText('Review saved for sample-1.')).resolves.toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const IndependentReviewAndEscalation: Story = {
  name: 'Independent review stays blind after save and escalation',
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.findByText('55 of 55 samples')).resolves.toBeVisible();
    await expect(canvas.getByRole('radio', { name: /Helpful/ })).toBeChecked();
    await userEvent.click(canvas.getByRole('checkbox', { name: /Independent review/ }));
    await waitFor(() => expect(canvas.getByRole('radio', { name: /Helpful/ })).not.toBeChecked());
    await expect(canvas.queryByText('Original imported prediction')).not.toBeInTheDocument();
    await expect(canvas.queryByRole('button', { name: 'Accept draft' })).not.toBeInTheDocument();
    await expect(canvas.queryByText('Arena vote')).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole('radio', { name: /Needs correction/ }));
    await userEvent.click(canvas.getByRole('button', { name: 'Save label & next' }));
    await waitFor(() => expect(editor(canvas, 2)).toBeVisible());
    await expect(canvas.getByRole('radio', { name: /Helpful/ })).not.toBeChecked();
    await expect(reviews[0].body).toMatchObject({ blind_review: true, human_label: { label: 'Needs correction' } });
    await userEvent.click(canvas.getByRole('button', { name: 'Escalate review' }));
    await expect(canvas.findByText(/This task has an escalated or conflicting review/)).resolves.toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Save label & next' })).toBeDisabled();
    await expect(canvas.queryByText('Original imported prediction')).not.toBeInTheDocument();
    await expect(canvas.queryByRole('button', { name: 'Accept draft' })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText('Show samples'), 'flagged');
    await expect(canvas.findByText('1 of 55 samples')).resolves.toBeVisible();
    await expect(queueButton(canvas, 2)).toHaveTextContent('Needs adjudication');
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const CreateAndImportFiles: Story = {
  name: 'Create campaign, append JSON and JSONL, and reject duplicates',
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.findByText('55 of 55 samples')).resolves.toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'New campaign' }));
    await userEvent.type(canvas.getByLabelText('Campaign name'), 'File import regression');
    await userEvent.click(canvas.getByRole('button', { name: 'Create campaign' }));
    const upload = await canvas.findByLabelText('Sample file (JSON or JSONL, up to 1 MB)');
    await userEvent.upload(upload, new File([JSON.stringify([{ id: 'json-1', text: 'JSON source' }])], 'samples.json', { type: 'application/json' }));
    await expect(canvas.findByText('1 samples added from samples.json. Review them before opening the batch.')).resolves.toBeVisible();
    await userEvent.upload(upload, new File(['{"id":"jsonl-2","text":"JSONL source"}\n'], 'samples.jsonl', { type: 'application/x-ndjson' }));
    await expect(canvas.findByText('1 samples added from samples.jsonl. Review them before opening the batch.')).resolves.toBeVisible();
    await expect(canvas.getByRole('group', { name: 'Sample 1' })).toBeVisible();
    await expect(canvas.getByRole('group', { name: 'Sample 2' })).toBeVisible();
    await userEvent.upload(upload, new File(['[{"id":"json-1","text":"Duplicate source"}]'], 'duplicate.json', { type: 'application/json' }));
    await expect(canvas.findByText('Duplicate sample id: json-1.')).resolves.toBeVisible();
    await expect(canvas.getAllByRole('group', { name: /^Sample \d+$/ })).toHaveLength(2);
    await expect(within(canvas.getByRole('group', { name: 'Sample 1' })).getByLabelText('Source text')).toHaveValue('JSON source');
    await expect(within(canvas.getByRole('group', { name: 'Sample 2' })).getByLabelText('Source text')).toHaveValue('JSONL source');
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const OpaqueSampleIdentity: Story = {
  name: 'Opaque source references keep stable sample names and separate copy controls',
  parameters: { annotationOpaqueSamples: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.findByText('55 of 55 samples')).resolves.toBeVisible();
    const currentEditor = within(canvas.getByRole('region', { name: 'Review sample Sample 1' }));
    await expect(currentEditor.getByRole('heading', { name: /^Sample 1\b/, level: 3 })).toBeVisible();
    await expect(canvas.queryByText(sourceId(1), { exact: true })).not.toBeInTheDocument();
    await expect(canvas.queryByText(id(1), { exact: true })).not.toBeInTheDocument();
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    const write = fn(async (_value: string) => {});
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: write } });
    try {
      await userEvent.click(currentEditor.getByRole('button', { name: 'Copy Source sample ID' }));
      await waitFor(() => expect(write).toHaveBeenNthCalledWith(1, sourceId(1)));
      await expect(within(document.body).getByText(sourceId(1), { selector: 'code' })).toBeVisible();
      await userEvent.click(currentEditor.getByRole('button', { name: 'Copy Annotation task ID' }));
      await waitFor(() => expect(write).toHaveBeenNthCalledWith(2, id(1)));
      await expect(within(document.body).getByText(id(1), { selector: 'code' })).toBeVisible();
      await expect(sourceId(1)).not.toBe(id(1));
      await userEvent.type(canvas.getByLabelText('Find sample'), 'Sample 51');
      await expect(canvas.findByText('1 of 55 samples')).resolves.toBeVisible();
      await userEvent.click(canvas.getByRole('button', { name: /^Sample 51 Awaiting review$/ }));
      await expect(canvas.getByRole('region', { name: 'Review sample Sample 51' })).toBeVisible();
      await expect(canvas.getByRole('heading', { name: /^Sample 51\b/, level: 3 })).toBeVisible();
      await expect(pages).toEqual(expect.arrayContaining([1, 2]));
      canvasElement.dataset.demoVerified = 'passed';
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original);
      else Reflect.deleteProperty(navigator, 'clipboard');
    }
  },
};
