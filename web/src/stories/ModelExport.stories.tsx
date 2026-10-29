import type { StoryObj } from '@storybook/react-vite';
import { http, HttpResponse } from 'msw';
import { expect, userEvent, within, waitFor } from 'storybook/test';
import screens from './Screens.stories';
import { mlResponses } from './ml-fixtures';

const runId = '30000000-0000-4000-8000-000000000001';
const options = [
  { format: 'native', label: 'Safetensors snapshot (ZIP)', extension: 'zip', description: 'Includes model weights, tokenizer files and provenance. Adapter weights remain separate from the base.' },
  { format: 'adapter', label: 'LoRA adapter only (ZIP)', extension: 'zip', description: 'Requires the exact base model recorded in the provenance.' },
  { format: 'json', label: 'Snapshot manifest (JSON)', extension: 'json', description: 'Artifact references and provenance only; weights are downloaded with the ZIP options.' },
];
const demoZip = 'UEsDBBQAAAAIAKK0Tl1tQqhIfgAAACRFAAAIAAAAREVNTy50eHTty7ENwjAQAMCeKX6CjELjCSB+EYsQo2AE2Z4p6O76K8c2lhxtjjL6flx7v0d+n30fU5x7PHrNNT7Zbst4xWXPaNu8vmvW6VRUVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVX/XX9QSwECFAMUAAAACACitE5dbUKoSH4AAAAkRQAACAAAAAAAAAAAAAAAgAEAAAAAREVNTy50eHRQSwUGAAAAAAEAAQA2AAAApAAAAAAA';
const meta = {
  ...screens, title: 'ModelAnvil/Actions/Model export',
  parameters: { demoRoute: `#training?tab=current-run&run=${runId}`, demoHeading: 'Training', demoApiPath: '/api/v1/training-runs/' },
  beforeEach(context: Parameters<typeof screens.beforeEach>[0]) {
    screens.beforeEach(context);
    const original = (mlResponses['/api/v1/training-runs/'] as Record<string, unknown>[])[0];
    const state = context.parameters.exportState;
    const originalPicker = Object.getOwnPropertyDescriptor(window, 'showSaveFilePicker');
    // Demo exports are small placeholder files; use a normal browser download in the preview.
    Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined });
    let downloads = 0;
    context.msw.use(
      http.get('/api/v1/dataset-revisions/', () => HttpResponse.json({ results: mlResponses['/api/v1/dataset-revisions/'], next: null })),
      http.get('/api/v1/training-runs/', () => HttpResponse.json({ results: [{ ...original, recipe_type: 'lora_adapter',
        status: state === 'active' ? 'running' : 'completed', export_options: state === 'active' ? [] : options,
        runtime: { execution_mode: 'worker', pins: { runtime: 'modelanvil.smollm2-gpu-sft.v1' } } }], next: null })),
      http.get('/api/v1/training-runs/:id/download/', ({ request }) => {
        downloads++;
        if (state === 'retry' && downloads === 1) return HttpResponse.json({ detail: 'Synthetic export failure' }, { status: 503 });
        const selected = new URL(request.url).searchParams.get('export_format');
        if (!options.some(option => option.format === selected)) return HttpResponse.json({ detail: 'Unsupported demo format' }, { status: 400 });
        const bytes = selected === 'json' ? new TextEncoder().encode(JSON.stringify({ demo_only: true, source: 'Synthetic Storybook export. No model weights are included.' })) : Uint8Array.from(atob(demoZip), c => c.charCodeAt(0));
        let cancelled = false;
        const stream = new ReadableStream({ async start(controller) {
          for (let i = 0; i < bytes.length; i += Math.ceil(bytes.length / 4)) {
            await new Promise(resolve => setTimeout(resolve, 350)); if (cancelled) return;
            controller.enqueue(bytes.slice(i, i + Math.ceil(bytes.length / 4)));
          }
          if (!cancelled) controller.close();
        }, cancel() { cancelled = true; } });
        return new HttpResponse(stream, { headers: { 'Content-Type': selected === 'json' ? 'application/json' : 'application/zip',
          ...(state === 'unknown' ? {} : { 'Content-Length': String(bytes.length) }) } });
      }),
    );
    return () => { if (originalPicker) Object.defineProperty(window, 'showSaveFilePicker', originalPicker); else delete (window as unknown as { showSaveFilePicker?: unknown }).showSaveFilePicker; };
  },
};
export default meta;
type Story = StoryObj<typeof meta>;
async function card(canvasElement: HTMLElement) { return within(await within(canvasElement).findByRole('region', { name: 'Model export' })); }
const download = (format = 'native'): Story['play'] => async ({ canvasElement }) => {
  const exportCard = await card(canvasElement);
  await userEvent.selectOptions(exportCard.getByLabelText('Export format'), format);
  await userEvent.click(exportCard.getByRole('button', { name: 'Download export' }));
  await expect(exportCard.findByText(/^Downloading/)).resolves.toBeVisible();
  await waitFor(() => expect(exportCard.getByText('Transfer complete')).toBeVisible(), { timeout: 6000 });
  await expect(exportCard.getByText('Export transferred. Check your browser’s downloads to finish saving.')).toBeVisible();
  canvasElement.dataset.demoVerified = 'passed';
};
export const NativeSnapshot: Story = { play: download() };
export const AdapterOnly: Story = { play: download('adapter') };
export const JsonManifest: Story = { play: download('json') };
export const UnknownSize: Story = { parameters: { exportState: 'unknown' }, play: download() };
export const CancelledDownload: Story = {
  play: async ({ canvasElement }) => {
    const exportCard = await card(canvasElement);
    await userEvent.click(exportCard.getByRole('button', { name: 'Download export' }));
    await expect(exportCard.findByText(/^Downloading/)).resolves.toBeVisible();
    await userEvent.click(exportCard.getByRole('button', { name: 'Cancel download' }));
    await expect(exportCard.findByText('Download cancelled. You can start again.')).resolves.toBeVisible();
    await expect(exportCard.getByRole('button', { name: 'Download export' })).toBeEnabled();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const Retry: Story = {
  parameters: { exportState: 'retry' },
  play: async ({ canvasElement }) => {
    const exportCard = await card(canvasElement);
    await userEvent.click(exportCard.getByRole('button', { name: 'Download export' }));
    await expect(exportCard.findByRole('alert')).resolves.toHaveTextContent('HTTP 503');
    await userEvent.click(exportCard.getByRole('button', { name: 'Retry export' }));
    await waitFor(() => expect(exportCard.getByText('Transfer complete')).toBeVisible(), { timeout: 6000 });
    await expect(exportCard.queryByRole('alert')).not.toBeInTheDocument();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const ActiveRun: Story = { parameters: { exportState: 'active' }, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.findByRole('region', { name: 'Live training progress' })).resolves.toBeVisible();
  await expect(canvas.queryByRole('region', { name: 'Model export' })).not.toBeInTheDocument(); canvasElement.dataset.demoVerified = 'passed';
} };
export const Dark: Story = { ...NativeSnapshot, parameters: { demoTheme: 'dark' } };
export const HistoryExport: Story = { play: async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  await canvas.findByRole('region', { name: 'Model export' });
  await userEvent.click(canvas.getByRole('tab', { name: 'History' }));
  await userEvent.click(canvas.getByRole('button', { name: 'Inspect run' }));
  const exportCard = await card(canvasElement);
  await userEvent.selectOptions(exportCard.getByLabelText('Export format'), 'json');
  await userEvent.click(exportCard.getByRole('button', { name: 'Download export' }));
  await waitFor(() => expect(exportCard.getByText('Transfer complete')).toBeVisible(), { timeout: 6000 });
  canvasElement.dataset.demoVerified = 'passed';
} };
export const Preview: Story = { play: async ({ canvasElement }) => {
  await expect((await card(canvasElement)).getByRole('button', { name: 'Download export' })).toBeVisible(); canvasElement.dataset.demoVerified = 'passed';
} };
