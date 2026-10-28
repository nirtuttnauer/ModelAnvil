import { ApiRequestError, apiPath, authHeaders, getActiveProjectId } from './client.ts';

export interface ModelExportOption { format: 'native' | 'adapter' | 'json'; label: string; extension: 'zip' | 'json'; description: string; method?: 'GET' | 'POST' }
export interface ExportProgress { phase: 'choosing' | 'preparing' | 'downloading' | 'complete'; received: number; total: number | null }
export const EXPORT_BUFFER_LIMIT = 256 * 1024**2;
export function exportBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024**2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024**3) return `${(bytes / 1024**2).toFixed(1)} MiB`;
  return `${(bytes / 1024**3).toFixed(2)} GiB`;
}

/** Prefer a disk stream; keep the fallback bounded when the browser has no file picker. */
export async function downloadModelExport(runId: string, option: ModelExportOption, token: string,
  signal: AbortSignal, onProgress: (progress: ExportProgress) => void, evaluationRun?: string): Promise<'saved' | 'browser'> {
  if (!token.trim()) throw new Error('Connect to your workspace before downloading.');
  if (!['native', 'adapter', 'json'].includes(option.format)) throw new Error('Unsupported export format.');
  const project = getActiveProjectId();
  const filename = `modelanvil-${runId}-${option.format}.${option.extension}`;
  const picker = (window as unknown as { showSaveFilePicker?: (options: { suggestedName: string }) => Promise<{ createWritable(): Promise<WritableStream<Uint8Array>> }> }).showSaveFilePicker;
  onProgress({ phase: picker ? 'choosing' : 'preparing', received: 0, total: null });
  const handle = picker ? await picker.call(window, { suggestedName: filename }) : null;
  signal.throwIfAborted();
  onProgress({ phase: 'preparing', received: 0, total: null });
  const headers = authHeaders(token); if (project) headers.set('X-Project-ID', project);
  const query = new URLSearchParams({ export_format: option.format });
  if (evaluationRun) query.set('evaluation_run', evaluationRun);
  const response = await fetch(apiPath(`/api/v1/training-runs/${encodeURIComponent(runId)}/download/?${query}`), { method: option.method === 'POST' ? 'POST' : 'GET', headers, signal, redirect: 'error' });
  if (!response.ok) throw new ApiRequestError(`Export download failed (HTTP ${response.status}).`, response.status);
  const contentType = option.extension === 'json' ? 'application/json' : 'application/zip';
  if (response.headers.get('Content-Type')?.split(';')[0].trim() !== contentType || !response.body) {
    await response.body?.cancel(); throw new Error('The API did not return the selected export format.');
  }
  const length = Number(response.headers.get('Content-Length'));
  const encoded = response.headers.get('Content-Encoding');
  const total = (!encoded || encoded === 'identity') && Number.isSafeInteger(length) && length > 0 ? length : null;
  let received = 0;
  const tooLarge = () => new Error('This export exceeds the browser’s 256 MiB download buffer. Open the app in Chrome or Edge to save directly to disk, or choose a smaller export format.');
  if (!handle && total !== null && total > EXPORT_BUFFER_LIMIT) { await response.body.cancel(); throw tooLarge(); }
  onProgress({ phase: 'downloading', received, total });
  const measured = response.body.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      received += chunk.byteLength;
      if (!handle && received > EXPORT_BUFFER_LIMIT) throw tooLarge();
      onProgress({ phase: 'downloading', received, total }); controller.enqueue(chunk);
    },
  }));
  if (handle) {
    try {
      const destination = await handle.createWritable();
      await measured.pipeTo(destination, { signal });
    } catch (e) { if (!measured.locked) await measured.cancel().catch(() => {}); throw e; }
  } else {
    const reader = measured.getReader(), chunks: Uint8Array<ArrayBuffer>[] = [];
    try {
      while (true) { signal.throwIfAborted(); const { done, value } = await reader.read(); if (done) break; chunks.push(value as Uint8Array<ArrayBuffer>); }
      signal.throwIfAborted();
      const url = URL.createObjectURL(new Blob(chunks, { type: contentType }));
      const link = document.createElement('a'); link.href = url; link.download = filename;
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
  onProgress({ phase: 'complete', received, total });
  return handle ? 'saved' : 'browser';
}
