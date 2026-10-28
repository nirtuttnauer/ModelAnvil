import type { StoryObj } from '@storybook/react-vite';
import { expect, within, userEvent, waitFor } from 'storybook/test';
import { http, HttpResponse } from 'msw';
import screens from './Screens.stories';

const model = 'storybook-markdown-model';
const secondModel = 'storybook-comparison-model';
const conversationId = 'c0000000-0000-4000-8000-000000000001';
const answer = '## Example answer\n\nUse **published data**.\n\n```python\nprint("ready")\n```';
let savedBody: Record<string, unknown> | null = null;

const meta = {
  ...screens,
  title: 'ModelAnvil/Actions/Chat',
  parameters: { demoRoute: '#chat', demoHeading: 'Chat', demoApiPath: '/api/v1/inference/models/' },
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context); savedBody = null;
    let conversations = [{ conversation_id: conversationId, title: 'Markdown example', revision_no: 1,
      messages: [{ role: 'user', content: 'Show an example.' }, { role: 'assistant', content: answer }],
      configuration: { model, device: 'cpu', prompt_format: 'model', temperature: 0, max_tokens: 128 } }];
    let comparisons: Record<string, unknown>[] = [];
    context.msw.use(
      http.get('/api/v1/inference/models/', () => HttpResponse.json({ data: [model, secondModel].map(id => ({ id, name: id === model ? 'Markdown model · Demo' : 'Comparison model · Demo', format: 'safetensors', load_tested: false, chat_template: 'synthetic', devices: ['cpu'], max_tokens: 256, context_limit: 2048 })) })),
      http.get('/api/v1/chat-conversations/', () => HttpResponse.json({ results: conversations, next: null })),
      http.get('/api/v1/chat-comparisons/', () => HttpResponse.json({ results: comparisons, next: null })),
      http.post('/api/v1/inference/chat/completions', async ({ request }) => {
        const body = await request.json() as { model: string };
        const id = 'chatcmpl-' + (body.model === model ? 'a' : 'b').repeat(32);
        const data = [answer.slice(0, 30), answer.slice(30)].map(content => `data: ${JSON.stringify({ id, choices: [{ delta: { content } }] })}\n\n`).join('') + 'data: [DONE]\n\n';
        return new HttpResponse(data, { headers: { 'Content-Type': 'text/event-stream' } });
      }),
      http.post('/api/v1/chat-conversations/', async ({ request }) => {
        const body = await request.json() as typeof conversations[0]; savedBody = body;
        const saved = { ...body, conversation_id: conversationId, revision_no: 1 };
        conversations = [saved]; return HttpResponse.json(saved);
      }),
      http.post('/api/v1/chat-comparisons/', async ({ request }) => {
        const body = await request.json() as { responses: { text: string }[]; messages: unknown[] };
        const saved = { comparison_id: 'c0000000-0000-4000-8000-000000000002', conversation_id: conversationId,
          messages: body.messages, vote: '', created_at: '2026-10-14T10:00:00Z', sides: body.responses.map((response, index) => ({ label: index ? 'B' : 'A', text: response.text })) };
        comparisons = [saved]; return HttpResponse.json(saved);
      }),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;

export const SavedMarkdownResponse: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByText('Saved conversations', { selector: 'summary' }));
    const select = canvas.getByLabelText('Saved conversation', { exact: true });
    await waitFor(() => expect(within(select).getByRole('option', { name: 'Markdown example' })).toBeInTheDocument());
    await userEvent.selectOptions(select, conversationId);
    const transcript = within(canvas.getByRole('log', { name: 'Conversation' }));
    await expect(transcript.findByRole('heading', { name: 'Example answer' })).resolves.toBeVisible();
    await expect(transcript.getByRole('button', { name: 'Copy code' })).toBeVisible();
    await expect(transcript.getByRole('button', { name: 'Copy response' })).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const GenerateMarkdownComparison: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const modelSelect = await canvas.findByLabelText('Model', { exact: true });
    await waitFor(() => expect(within(modelSelect).getAllByRole('option').length).toBe(3));
    await userEvent.selectOptions(modelSelect, model);
    await userEvent.click(canvas.getByText('Generation settings', { selector: 'summary' }));
    await userEvent.selectOptions(canvas.getByLabelText('Compare with'), secondModel);
    await userEvent.type(canvas.getByLabelText('Message', { exact: true }), 'Show the code.');
    await userEvent.click(canvas.getByRole('button', { name: 'Send message' }));
    const comparison = within(await canvas.findByRole('region', { name: 'Saved model comparison' }));
    await expect(comparison.getAllByRole('heading', { name: 'Example answer' })).toHaveLength(2);
    await expect(comparison.getAllByRole('button', { name: 'Copy code' })).toHaveLength(2);
    await expect(comparison.getAllByRole('button', { name: 'Copy response' })).toHaveLength(2);
    await expect(savedBody).toMatchObject({ messages: [{ role: 'user', content: 'Show the code.' }, { role: 'assistant', content: answer }] });
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ChatComposerKeyboard: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const modelSelect = await canvas.findByLabelText('Model', { exact: true });
    await waitFor(() => expect(within(modelSelect).getAllByRole('option').length).toBe(3));
    await userEvent.selectOptions(modelSelect, model);
    const message = canvas.getByLabelText('Message', { exact: true });
    if (window.innerWidth <= 700) {
      expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
      expect(parseFloat(getComputedStyle(message).fontSize)).toBeGreaterThanOrEqual(16);
      for (const label of ['New conversation', 'Export', 'Send message']) {
        expect(canvas.getByRole('button', { name: label }).getBoundingClientRect().height).toBeGreaterThanOrEqual(44);
      }
    }
    await userEvent.type(message, 'First line');
    await userEvent.keyboard('{Shift>}{Enter}{/Shift}');
    await userEvent.type(message, 'Second line');
    await expect(message).toHaveValue('First line\nSecond line');
    expect(savedBody).toBeNull();
    await userEvent.keyboard('{Enter}');
    await expect(canvas.findByText('Conversation saved.')).resolves.toBeVisible();
    const transcript = within(canvas.getByRole('log', { name: 'Conversation' }));
    await expect(transcript.getByRole('heading', { name: 'Example answer' })).toBeVisible();
    await expect(savedBody).toMatchObject({ messages: [{ role: 'user', content: 'First line\nSecond line' }, { role: 'assistant', content: answer }] });
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ActiveJobsPanel: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole('button', { name: 'Active jobs' });
    await userEvent.click(trigger);
    const panel = await canvas.findByRole('complementary', { name: 'Active jobs' });
    const jobs = within(panel);
    expect(panel.closest('dialog')?.matches(':modal')).toBe(window.innerWidth < 1200);
    const bounds = panel.getBoundingClientRect();
    expect(bounds.left).toBeGreaterThanOrEqual(0);
    expect(bounds.right).toBeLessThanOrEqual(document.documentElement.clientWidth);
    expect(bounds.bottom).toBeLessThanOrEqual(window.innerHeight);
    await expect(jobs.findByText('Anvil Assistant · active SFT demo')).resolves.toBeVisible();
    await expect(jobs.getByText('Export candidate metadata')).toBeVisible();
    await expect(jobs.queryByText('Anvil Assistant · evaluation demo')).not.toBeInTheDocument();
    await expect(jobs.getByRole('progressbar', { name: 'Anvil Assistant · active SFT demo progress' })).toHaveAttribute('value', '31');
    if (window.innerWidth < 1200) {
      await userEvent.click(jobs.getByRole('button', { name: 'Close active jobs' }));
      await expect(trigger).toHaveFocus();
      await userEvent.click(trigger);
      await userEvent.tab();
      expect(panel.isConnected).toBe(false);
      expect(canvas.getByRole('dialog', { name: 'Active jobs' }).contains(document.activeElement)).toBe(true);
    }
    await userEvent.click(canvas.getByRole('button', { name: 'Refresh active jobs' }));
    await userEvent.keyboard('{Escape}');
    await expect(canvas.queryByRole('complementary', { name: 'Active jobs' })).not.toBeInTheDocument();
    await expect(trigger).toHaveFocus();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
