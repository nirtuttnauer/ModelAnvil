import { apiPath, ApiRequestError, getActiveProjectId } from './client.ts';

export interface ChatMessage { role: 'system' | 'user' | 'assistant'; content: string }
export interface LocalModel { id: string; name: string; format: string; load_tested: boolean; chat_template: string }
export interface TokenUsage { prompt_tokens: number; completion_tokens: number; total_tokens: number }

export async function streamCompletion(token: string, body: Record<string, unknown>, signal: AbortSignal,
  onText: (text: string) => void, onUsage: (usage: TokenUsage) => void,
  fetchImpl: typeof fetch = fetch): Promise<void> {
  if (!token.trim()) throw new Error('Connect to your workspace before chatting.');
  const headers = new Headers({ Authorization: `Bearer ${token.trim()}`, 'Content-Type': 'application/json' });
  const project = getActiveProjectId();
  if (project) headers.set('X-Project-ID', project);
  const response = await fetchImpl(apiPath('/api/v1/inference/chat/completions'), { method: 'POST', headers,
    body: JSON.stringify({ ...body, stream: true, stream_options: { include_usage: true } }), signal, redirect: 'error' });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new ApiRequestError(error?.error?.details?.map((d: { message: string }) => d.message).join(' ') || error?.error?.message || `Generation failed (${response.status}).`, response.status);
  }
  if (!response.headers.get('Content-Type')?.startsWith('text/event-stream') || !response.body) {
    throw new Error('The inference API did not return a token stream.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '', finished = false;
  try {
    while (!finished) {
      const { value, done } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (pending.length > 65536) throw new Error('Inference event exceeds its size limit.');
      let boundary;
      while ((boundary = pending.indexOf('\n\n')) !== -1) {
        const event = pending.slice(0, boundary); pending = pending.slice(boundary + 2);
        const data = event.split('\n').filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n');
        if (!data) continue;
        if (data === '[DONE]') { finished = true; break; }
        const chunk = JSON.parse(data);
        if (chunk.error) throw new Error(chunk.error.message || 'Local generation failed.');
        const text = chunk.choices?.[0]?.delta?.content;
        if (typeof text === 'string') onText(text);
        if (chunk.usage) onUsage(chunk.usage);
      }
      if (done) {
        if (!finished) throw new Error('Inference stream ended before completion.');
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
