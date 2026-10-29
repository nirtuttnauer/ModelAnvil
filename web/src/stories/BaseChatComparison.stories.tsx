import type { StoryObj } from '@storybook/react-vite';
import { delay, http, HttpResponse } from 'msw';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import screens from './Screens.stories';
import { mlResponses } from './ml-fixtures';
import { draftKey, writeDraft } from '../api/drafts';

const baseId = 'b1000000-0000-4000-8000-000000000001', trainedId = 'b1000000-0000-4000-8000-000000000002';
const conversationId = 'b2000000-0000-4000-8000-000000000001';
const baseText = '## Base answer\n\nTry restarting the device.';
const trainedText = '## Trained answer\n\n1. Open **Settings**.\n2. Choose Reset.\n\n```python\nprint("reset")\n```';
const configuration = { model: trainedId, compare_model: baseId, comparison_mode: 'base-trained', device: 'cpu', compare_device: 'cpu', prompt_format: 'model', temperature: 0, max_tokens: 128, seed: 42 };
let inputs: Record<string, unknown>[] = [], pairCount = 0;
const meta = {
  ...screens, title: 'ModelAnvil/Actions/Base chat comparison',
  parameters: { demoRoute: '#chat', demoHeading: 'Chat', demoApiPath: '/api/v1/inference/models/' },
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context); inputs = []; pairCount = 0;
    if (context.parameters.restoreComparison) writeDraft(sessionStorage, draftKey('demo-tenant', '1', 'chat-composer'), { comparisonMode: 'base-trained' }, { comparisonMode: 'blind' });
    const state = context.parameters.compareState;
    const saved = ['saved', 'compact', 'long'].includes(state);
    const samplePrompt = state === 'compact' || state === 'long' ? 'Where should I park my bicycle?' : 'How do I reset?';
    const baseAnswer = state === 'compact' ? 'Use the designated bike rack near the garden entrance.' : state === 'long' ? baseText + '\n\n' + 'Additional base explanation. '.repeat(120) + 'End of base answer.' : baseText;
    const trainedAnswer = state === 'compact' ? 'Use the silver rack beside the cedar shed and bring your own lock.' : state === 'long' ? trainedText + '\n\n' + 'Additional trained explanation. '.repeat(120) + 'End of trained answer.' : trainedText;
    const models = [{ id: baseId, name: 'Base model · Demo', format: 'safetensors', chat_template: 'synthetic', devices: ['cpu'], max_tokens: 256, context_limit: 2048, load_tested: false },
      { id: trainedId, name: 'Trained model · Demo', format: 'safetensors', chat_template: 'synthetic', devices: ['cpu'], max_tokens: 128, context_limit: 2048, load_tested: false, training_run_id: 'demo-training-run', base_model_id: state === 'missing' ? null : baseId }];
    let conversations = saved ? [{ conversation_id: conversationId, title: 'Saved base comparison', revision_no: 1, messages: [{ role: 'user', content: samplePrompt }, { role: 'assistant', content: trainedAnswer }], configuration }] : [];
    const sides = [{ label: 'A', role: 'trained', model: trainedId, name: 'Trained model · Demo', text: trainedAnswer }, { label: 'B', role: 'base', model: baseId, name: 'Base model · Demo', text: baseAnswer }];
    let pairs = saved ? [{ comparison_id: 'b3000000-0000-4000-8000-000000000001', conversation_id: conversationId, messages: [{ role: 'user', content: samplePrompt }], sides, vote: '', created_at: new Date().toISOString() }] : [];
    const run = (mlResponses['/api/v1/training-runs/'] as Record<string, unknown>[])[0];
    run.output_model_version_uuid = trainedId;
    context.msw.use(
      http.get('/api/v1/dataset-revisions/', () => HttpResponse.json({ results: mlResponses['/api/v1/dataset-revisions/'], next: null })),
      http.get('/api/v1/inference/models/', async () => { if (state === 'loading') await delay(800); return HttpResponse.json({ data: state === 'missing' ? models.slice(1) : models }); }),
      http.get('/api/v1/model-versions/:id/', ({ params }) => HttpResponse.json({ id: params.id === trainedId ? 2 : 1, model_version_id: params.id, chat_template: 'synthetic' })),
      http.get('/api/v1/chat-conversations/', () => HttpResponse.json({ results: conversations, next: null })),
      http.get('/api/v1/chat-comparisons/', ({ request }) => HttpResponse.json({ results: new URL(request.url).searchParams.get('view') === 'base-trained' ? pairs : pairs.map(pair => ({ ...pair, sides: pair.sides.map(side => ({ label: side.label, text: side.text })) })), next: null })),
      http.post('/api/v1/inference/chat/completions', async ({ request }) => {
        const body = await request.json() as Record<string, unknown>; inputs.push(body);
        if (state === 'failure' && body.model === baseId) return HttpResponse.json({ error: { message: 'Demo base model memory unavailable' } }, { status: 400 });
        const id = 'chatcmpl-' + inputs.length.toString(16).padStart(32, '0');
        const text = body.model === baseId ? baseAnswer : trainedAnswer;
        let stopped = false;
        return new HttpResponse(new ReadableStream({ async start(controller) {
          for (const content of [text.slice(0, 20), text.slice(20)]) {
            await new Promise(resolve => setTimeout(resolve, state === 'stop' ? 700 : 120)); if (stopped) return;
            controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ id, choices: [{ delta: { content } }] })}\n\n`));
          }
          if (!stopped) { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify({ id, usage: { prompt_tokens: 12, completion_tokens: 20, total_tokens: 32 } })}\n\ndata: [DONE]\n\n`)); controller.close(); }
        }, cancel() { stopped = true; } }), { headers: { 'Content-Type': 'text/event-stream' } });
      }),
      http.post('/api/v1/chat-conversations/', async ({ request }) => {
        const body = await request.json() as typeof conversations[0]; const saved = { ...body, conversation_id: conversationId, revision_no: 1 }; conversations = [saved]; return HttpResponse.json(saved);
      }),
      http.patch('/api/v1/chat-conversations/:id/', async ({ request }) => {
        const body = await request.json() as typeof conversations[0]; const saved = { ...conversations[0], ...body, revision_no: (conversations[0]?.revision_no || 0) + 1 }; conversations = [saved]; return HttpResponse.json(saved);
      }),
      http.post('/api/v1/chat-comparisons/', async ({ request }) => {
        const body = await request.json() as { messages: { role: string; content: string }[] }; pairCount++;
        const pair = { comparison_id: 'b3000000-0000-4000-8000-' + String(pairCount).padStart(12, '0'), conversation_id: conversationId, messages: body.messages, sides, vote: '', created_at: new Date().toISOString() };
        pairs = [pair, ...pairs]; return HttpResponse.json(pair);
      }),
    );
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
const isCompactComparison = () => window.innerWidth <= 700 || window.innerWidth <= 950 && window.innerHeight <= 500;
async function enable(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await waitFor(() => expect(within(canvas.getByLabelText('Model', { exact: true })).getAllByRole('option').length).toBeGreaterThan(1));
  await userEvent.click(canvas.getByRole('button', { name: /^Base vs trained$/ }));
  await waitFor(() => expect(canvas.getByLabelText('Trained model', { exact: true })).toHaveValue(trainedId)); return canvas;
}
async function generate(canvasElement: HTMLElement, prompt = 'How do I reset?') {
  const canvas = within(canvasElement); await userEvent.type(canvas.getByLabelText('Message', { exact: true }), prompt); await userEvent.click(canvas.getByRole('button', { name: 'Send message' }));
  await waitFor(() => expect(canvas.getByText('Base and trained responses saved with the same prompt and generation settings.')).toBeVisible(), { timeout: 6000 });
}
export const GeneratePair: Story = { play: async ({ canvasElement }) => {
  const canvas = await enable(canvasElement); await generate(canvasElement);
  const pair = within(canvas.getByRole('region', { name: 'Base and trained model responses' }));
  const region = pair.getByRole('region', { name: 'Model responses' });
  const columns = within(region);
  const baseBounds = columns.getByRole('article', { name: 'Base model response' }).getBoundingClientRect();
  const trainedBounds = columns.getByRole('article', { name: 'Trained model response' }).getBoundingClientRect();
  expect(region.scrollWidth).toBeLessThanOrEqual(region.clientWidth);
  if (isCompactComparison()) {
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
    const composer = canvas.getByLabelText('Message', { exact: true }).getBoundingClientRect();
    expect(composer.bottom).toBeLessThanOrEqual(window.innerHeight);
    expect(trainedBounds.bottom).toBeLessThan(composer.top);
    for (const bounds of [baseBounds, trainedBounds]) {
      expect(bounds.top).toBeGreaterThanOrEqual(0);
      expect(bounds.bottom).toBeLessThanOrEqual(window.innerHeight);
      expect(bounds.left).toBeGreaterThanOrEqual(0);
      expect(bounds.right).toBeLessThanOrEqual(document.documentElement.clientWidth);
    }
  }
  if (window.innerWidth <= 700 && !(window.innerWidth >= 560 && window.innerHeight <= 500)) {
    expect(Math.abs(baseBounds.left - trainedBounds.left)).toBeLessThan(2);
    expect(trainedBounds.top).toBeGreaterThan(baseBounds.bottom);
  } else {
    expect(Math.abs(baseBounds.top - trainedBounds.top)).toBeLessThan(2);
    expect(trainedBounds.left).toBeGreaterThan(baseBounds.right);
  }
  await expect(pair.getByRole('heading', { name: 'Base model · Demo' })).toBeVisible(); await expect(pair.getByRole('heading', { name: 'Trained model · Demo' })).toBeVisible();
  await expect(pair.getByRole('heading', { name: 'Base answer' })).toBeVisible(); await expect(pair.getByRole('heading', { name: 'Trained answer' })).toBeVisible();
  await expect(pair.getAllByRole('button', { name: 'Copy response' })).toHaveLength(2); await expect(pair.getByRole('button', { name: 'Copy code' })).toBeVisible();
  expect(inputs).toHaveLength(2); expect(inputs[0].model).toBe(baseId); expect(inputs[1].model).toBe(trainedId);
  for (const key of ['messages', 'temperature', 'max_tokens', 'seed', 'prompt_format']) expect(inputs[0][key]).toEqual(inputs[1][key]);
  canvasElement.dataset.demoVerified = 'passed';
} };
export const FreshPromptEachTime: Story = { play: async ({ canvasElement }) => {
  await enable(canvasElement); await generate(canvasElement); await generate(canvasElement, 'How do I restart?');
  expect(inputs).toHaveLength(4); expect(inputs[2].messages).toEqual([{ role: 'user', content: 'How do I restart?' }]); expect(inputs[3].messages).toEqual(inputs[2].messages);
  expect(pairCount).toBe(2); canvasElement.dataset.demoVerified = 'passed';
} };
export const SavedPair: Story = { parameters: { compareState: 'saved' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  if (isCompactComparison() && canvas.queryByRole('button', { name: 'Chat options' })) await userEvent.click(canvas.getByRole('button', { name: 'Chat options' }));
  await userEvent.click(await canvas.findByText('Saved conversations', { selector: 'summary' }));
  await waitFor(() => expect(within(canvas.getByLabelText('Saved conversation', { exact: true })).getByRole('option', { name: 'Saved base comparison' })).toBeInTheDocument());
  await userEvent.selectOptions(canvas.getByLabelText('Saved conversation', { exact: true }), conversationId);
  const pair = within(await canvas.findByRole('region', { name: 'Base and trained model responses' }));
  await expect(pair.findByRole('heading', { name: 'Base answer' })).resolves.toBeVisible(); await expect(pair.getByRole('heading', { name: 'Trained answer' })).toBeVisible();
  expect(inputs).toHaveLength(0); canvasElement.dataset.demoVerified = 'passed';
} };
export const MissingBase: Story = { parameters: { compareState: 'missing' }, play: async ({ canvasElement }) => {
  const canvas = await enable(canvasElement); await expect(canvas.getByText(/The exact base model is unavailable/)).toBeVisible();
  await userEvent.type(canvas.getByLabelText('Message', { exact: true }), 'Prompt'); await expect(canvas.getByRole('button', { name: 'Send message' })).toBeDisabled(); expect(inputs).toHaveLength(0); canvasElement.dataset.demoVerified = 'passed';
} };
export const OneModelFails: Story = { parameters: { compareState: 'failure' }, play: async ({ canvasElement }) => {
  const canvas = await enable(canvasElement); await userEvent.type(canvas.getByLabelText('Message', { exact: true }), 'Prompt'); await userEvent.click(canvas.getByRole('button', { name: 'Send message' }));
  await expect(canvas.findByRole('heading', { name: 'Trained answer' })).resolves.toBeVisible();
  await expect(canvas.getByText('Demo base model memory unavailable')).toBeVisible(); await waitFor(() => expect(canvas.getByRole('button', { name: 'Send message' })).toBeEnabled());
  expect(inputs).toHaveLength(2); expect(pairCount).toBe(0); canvasElement.dataset.demoVerified = 'passed';
} };
export const StopGeneration: Story = { parameters: { compareState: 'stop' }, play: async ({ canvasElement }) => {
  const canvas = await enable(canvasElement); await userEvent.type(canvas.getByLabelText('Message', { exact: true }), 'Prompt'); await userEvent.click(canvas.getByRole('button', { name: 'Send message' }));
  await expect(canvas.findByRole('heading', { name: 'Base answer' })).resolves.toBeVisible(); await userEvent.click(canvas.getByRole('button', { name: /^Stop$/ }));
  await waitFor(() => expect(canvas.getByRole('button', { name: 'Send message' })).toBeEnabled()); expect(inputs).toHaveLength(1); expect(pairCount).toBe(0); canvasElement.dataset.demoVerified = 'passed';
} };
export const FromTraining: Story = { parameters: { demoRoute: '#training?tab=current-run&run=30000000-0000-4000-8000-000000000001' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await userEvent.click(await canvas.findByRole('link', { name: 'Try base vs trained' }));
  await waitFor(() => expect(canvas.getByLabelText('Trained model', { exact: true })).toHaveValue(trainedId));
  await expect(canvas.getByLabelText('Base model', { exact: true })).toHaveValue('Base model · Demo'); canvasElement.dataset.demoVerified = 'passed';
} };
export const Handoff: Story = { parameters: { demoRoute: `#chat?model_version=${trainedId}&compare_base=1` }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await waitFor(() => expect(canvas.getByLabelText('Trained model', { exact: true })).toHaveValue(trainedId));
  await waitFor(() => expect(window.location.hash).toBe('#chat'));
  await generate(canvasElement); canvasElement.dataset.demoVerified = 'passed';
} };
export const RepeatHandoff: Story = { parameters: { demoRoute: `#chat?model_version=${trainedId}&compare_base=1` }, play: async ({ canvasElement }) => {
  await waitFor(() => expect(window.location.hash).toBe('#chat'));
  await generate(canvasElement);
  window.location.hash = `#chat?model_version=${trainedId}&compare_base=1`;
  await waitFor(() => expect(window.location.hash).toBe('#chat'));
  await generate(canvasElement, 'A new question for the same model.');
  expect(inputs).toHaveLength(4);
  canvasElement.dataset.demoVerified = 'passed';
} };
export const LoadingHandoff: Story = { parameters: { compareState: 'loading', demoRoute: `#chat?model_version=${trainedId}&compare_base=1` }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.findByText('Loading models and saved conversations…')).resolves.toBeVisible();
  expect(canvas.queryByText(/The exact base model is unavailable/)).not.toBeInTheDocument();
  expect(canvas.queryByText(/No completed trained models are available/)).not.toBeInTheDocument();
  await waitFor(() => expect(window.location.hash).toBe('#chat'));
  await generate(canvasElement);
  canvasElement.dataset.demoVerified = 'passed';
} };
export const Dark: Story = { ...GeneratePair, parameters: { demoTheme: 'dark' } };
export const LoadingComparison: Story = { parameters: { compareState: 'loading', restoreComparison: true }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await expect(canvas.findByRole('heading', { name: 'Loading base model…' })).resolves.toBeVisible();
  await expect(canvas.getByRole('heading', { name: 'Loading trained model…' })).toBeVisible();
  expect(canvas.queryByRole('heading', { name: 'Base model unavailable' })).not.toBeInTheDocument();
  const models = canvas.getByLabelText('Trained model', { exact: true });
  await waitFor(() => expect(within(models).getAllByRole('option').length).toBeGreaterThan(1));
  if (isCompactComparison()) await userEvent.click(canvas.getByRole('button', { name: 'Chat options' }));
  await userEvent.selectOptions(models, trainedId);
  await expect(canvas.findByRole('heading', { name: 'Base model · Demo' })).resolves.toBeVisible();
  canvasElement.dataset.demoVerified = 'passed';
} };
export const Preview: Story = { play: async ({ canvasElement }) => { await enable(canvasElement); await generate(canvasElement); canvasElement.dataset.demoVerified = 'passed'; } };

async function openCompactSaved(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await userEvent.click(await canvas.findByText('Saved conversations', { selector: 'summary' }));
  await waitFor(() => expect(within(canvas.getByLabelText('Saved conversation', { exact: true })).getByRole('option', { name: 'Saved base comparison' })).toBeInTheDocument());
  await userEvent.selectOptions(canvas.getByLabelText('Saved conversation', { exact: true }), conversationId);
  await expect(canvas.findByRole('article', { name: 'Trained model response' })).resolves.toBeVisible();
  if (isCompactComparison()) {
    const composer = canvas.getByLabelText('Message', { exact: true }).getBoundingClientRect();
    for (const name of ['Base model response', 'Trained model response']) {
      const bounds = canvas.getByRole('article', { name }).getBoundingClientRect();
      expect(bounds.top).toBeGreaterThanOrEqual(0);
      expect(bounds.bottom).toBeLessThan(composer.top);
    }
    expect(composer.bottom).toBeLessThanOrEqual(window.innerHeight);
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
  }
  return canvas;
}
export const CompactSaved: Story = { parameters: { compareState: 'compact' }, play: async ({ canvasElement }) => {
  const canvas = await openCompactSaved(canvasElement);
  await expect(canvas.getByText('Use the silver rack beside the cedar shed and bring your own lock.')).toBeVisible();
  if (isCompactComparison()) for (const name of ['Base answer text', 'Trained answer text']) {
    const text = canvas.getByRole('region', { name });
    expect(text.scrollHeight).toBeLessThanOrEqual(text.clientHeight + 1);
  }
  canvasElement.dataset.demoVerified = 'passed';
} };
export const CompactLongAnswers: Story = { parameters: { compareState: 'long' }, play: async ({ canvasElement }) => {
  const canvas = await openCompactSaved(canvasElement);
  if (isCompactComparison()) for (const name of ['Base answer text', 'Trained answer text']) {
    const text = canvas.getByRole('region', { name });
    expect(text.scrollHeight).toBeGreaterThan(text.clientHeight);
    expect(text).toHaveAttribute('tabindex', '0');
    expect(text.textContent).toContain(name === 'Base answer text' ? 'End of base answer.' : 'End of trained answer.');
  }
  canvasElement.dataset.demoVerified = 'passed';
} };
export const CompactDark: Story = { ...CompactSaved, parameters: { compareState: 'compact', demoTheme: 'dark' } };
export const CompactOptions: Story = { parameters: { compareState: 'compact' }, play: async ({ canvasElement }) => {
  const canvas = await openCompactSaved(canvasElement);
  const message = canvas.getByLabelText('Message', { exact: true });
  await userEvent.type(message, 'A follow-up question');
  if (isCompactComparison()) await userEvent.click(canvas.getByRole('button', { name: 'Chat options' }));
  await userEvent.click(canvas.getByText('Generation settings', { selector: 'summary' }));
  await userEvent.clear(canvas.getByLabelText('Temperature'));
  await userEvent.type(canvas.getByLabelText('Temperature'), '0.4');
  if (isCompactComparison()) {
    await userEvent.click(canvas.getByRole('button', { name: 'Chat options' }));
    await waitFor(() => expect(message.getBoundingClientRect().bottom).toBeLessThanOrEqual(window.innerHeight));
  }
  expect(message).toHaveValue('A follow-up question');
  expect(canvas.getByLabelText('Temperature')).toHaveValue(0.4);
  if (isCompactComparison()) await userEvent.click(canvas.getByRole('button', { name: 'Chat options' }));
  await userEvent.click(canvasElement.querySelector('.chat-comparison-input > summary')!);
  await expect(canvas.getByRole('group', { name: 'Shared comparison input' })).toBeVisible();
  await expect(canvas.getByRole('combobox', { name: /Saved prompt comparison/ })).toBeVisible();
  canvasElement.dataset.demoVerified = 'passed';
} };
