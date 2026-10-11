import { useCallback, useEffect, useRef, useState } from 'react';
import { MessageSquare, Square, Download, RotateCcw } from 'lucide-react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ChatMessage, LocalModel, streamCompletion, TokenUsage } from '../api/inference';
import './model-workspace.css';
import './ml-pages.css';

interface Conversation { conversation_id: string; title: string; revision_no: number; messages: ChatMessage[]; configuration: Record<string, unknown> }
interface Answer { model: string; text: string; usage: TokenUsage | null; seconds: number; status: string }

export function ChatPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [model, setModel] = useState('');
  const [compare, setCompare] = useState('');
  const [compareDevice, setCompareDevice] = useState('cpu');
  const [prompt, setPrompt] = useState('');
  const [system, setSystem] = useState('');
  const [promptFormat, setPromptFormat] = useState('model');
  const [device, setDevice] = useState('cpu');
  const [temperature, setTemperature] = useState(0);
  const [maxTokens, setMaxTokens] = useState(128);
  const [seed, setSeed] = useState(42);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    const [catalog, history] = await Promise.all([
      apiRequest<{ data: LocalModel[] }>('/api/v1/inference/models/', token, { signal }),
      apiPage<Conversation>('/api/v1/chat-conversations/', token, signal),
    ]);
    if (!signal?.aborted) { setModels(catalog.data); setConversations(history.results); }
  }, [token]);
  useEffect(() => {
    if (!token.trim()) return;
    const c = new AbortController();
    void load(c.signal).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => { c.abort(); controller.current?.abort(); };
  }, [load, refreshKey, token]);
  function select(value: Conversation | null) {
    controller.current?.abort(); setConversation(value); setMessages(value?.messages || []); setAnswers([]); setNotice(''); setError('');
    if (value) {
      const config = value.configuration;
      setModel(String(config.model || '')); setCompare(String(config.compare_model || '')); setDevice(String(config.device || 'cpu')); setCompareDevice(String(config.compare_device || 'cpu'));
      setSystem(String(config.system_prompt || '')); setTemperature(Number(config.temperature || 0)); setMaxTokens(Number(config.max_tokens || 128)); setSeed(Number(config.seed ?? 42));
      setPromptFormat(String(config.prompt_format || 'model'));
    }
  }
  async function run(history: ChatMessage[]) {
    setBusy(true); setError(''); setNotice('');
    const c = new AbortController(); controller.current = c;
    const configuration = { model, compare_model: compare || null, compare_device: compareDevice, device, temperature, max_tokens: maxTokens, seed, system_prompt: system, prompt_format: promptFormat };
    const input = system.trim() ? [{ role: 'system' as const, content: system }, ...history] : history;
    const identifiers = [model, ...(compare ? [compare] : [])];
    const completed: Answer[] = [];
    setMessages(history); setAnswers(identifiers.map(id => ({ model: id, text: '', usage: null, seconds: 0, status: 'pending' })));
    try {
      for (const identifier of identifiers) {
        const started = performance.now();
        const result: Answer = { model: identifier, text: '', usage: null, seconds: 0, status: 'generating' };
        await streamCompletion(token, { model: identifier, messages: input, device: identifier === model ? device : compareDevice, temperature, max_tokens: maxTokens, seed, prompt_format: promptFormat }, c.signal,
          text => { result.text += text; setAnswers(prior => prior.map(a => a.model === identifier ? { ...result } : a)); },
          usage => { result.usage = usage; });
        result.seconds = (performance.now() - started) / 1000; result.status = 'completed'; completed.push({ ...result });
        setAnswers(prior => prior.map(a => a.model === identifier ? { ...result } : a));
      }
      const next = [...history, { role: 'assistant' as const, content: completed[0].text || '[Empty completion]' }];
      setMessages(next);
      const saved = await apiRequest<Conversation>(conversation ? `/api/v1/chat-conversations/${conversation.conversation_id}/` : '/api/v1/chat-conversations/', token,
        { method: conversation ? 'PATCH' : 'POST', signal: c.signal, body: JSON.stringify({ title: history.find(m => m.role === 'user')?.content.slice(0, 180) || 'Conversation',
          messages: next, configuration, ...(conversation ? { revision_no: conversation.revision_no } : {}) }) });
      setConversation(saved); await load(c.signal); setNotice('Conversation saved.');
    } catch (e) {
      if (c.signal.aborted) setNotice('Generation stopped. Partial output was not saved.');
      else setError(errorMessage(e));
      setAnswers(prior => prior.map(a => a.status !== 'completed' ? { ...a, status: c.signal.aborted ? 'stopped' : 'failed' } : a));
    } finally { if (controller.current === c) controller.current = null; setBusy(false); }
  }
  function send(event: React.FormEvent) {
    event.preventDefault(); const text = prompt.trim(); if (!text) return;
    setPrompt(''); void run([...messages, { role: 'user', content: text }]);
  }
  function regenerate() {
    const history = messages.at(-1)?.role === 'assistant' ? messages.slice(0, -1) : messages;
    if (history.at(-1)?.role === 'user') void run(history);
  }
  function exportConversation() {
    const blob = new Blob([JSON.stringify({ conversation, messages, answers }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'modelanvil-conversation.json'; anchor.click(); URL.revokeObjectURL(url);
  }
  return <div className="resource-view ml-page"><section className="panel ml-main-panel">
    <div className="panel-title"><div><h2><MessageSquare size={20} /> Local chat & model arena</h2><p>Run imported snapshots or completed transformer candidates and compare two versions using the same input and settings.</p></div>
      <div className="actions"><button disabled={busy} onClick={() => select(null)}>New conversation</button><button disabled={busy || !messages.length} onClick={exportConversation}><Download size={16} /> Export</button></div></div>
    <div className="panel-body">
      {error && <p className="error-text" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      <div className="form-grid">
        <label>Saved conversation<select value={conversation?.conversation_id || ''} disabled={busy} onChange={e => select(conversations.find(c => c.conversation_id === e.target.value) || null)}><option value="">New conversation</option>{conversations.map(c => <option key={c.conversation_id} value={c.conversation_id}>{c.title}</option>)}</select></label>
        <label>Model<select value={model} required disabled={busy} onChange={e => { setModel(e.target.value); if (e.target.value === compare) setCompare(''); setDevice(models.find(m => m.id === e.target.value)?.format === 'mlx' ? 'mlx:0' : 'cpu'); }}><option value="">Select a model snapshot</option>{models.map(m => <option key={m.id} value={m.id}>{m.name} · {m.format}</option>)}</select></label>
        <label>Compare with<select value={compare} disabled={busy} onChange={e => { setCompare(e.target.value); setCompareDevice(models.find(m => m.id === e.target.value)?.format === 'mlx' ? 'mlx:0' : 'cpu'); }}><option value="">Single model</option>{models.filter(m => m.id !== model).map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        <label>Device<select value={device} disabled={busy} onChange={e => setDevice(e.target.value)}><option value="cpu">CPU</option><option value="mps:0">Apple Silicon GPU (PyTorch)</option><option value="mlx:0">Apple Silicon GPU (MLX)</option></select></label>
        {compare && <label>Comparison device<select value={compareDevice} disabled={busy} onChange={e => setCompareDevice(e.target.value)}><option value="cpu">CPU</option><option value="mps:0">Apple Silicon GPU (PyTorch)</option><option value="mlx:0">Apple Silicon GPU (MLX)</option></select></label>}
      </div>
      <details><summary>Generation settings</summary><div className="form-grid">
        <label>Prompt formatting<select value={promptFormat} disabled={busy} onChange={e => setPromptFormat(e.target.value)}><option value="model">Imported model template</option><option value="plain">Plain text (one user prompt)</option><option value="chatml">ChatML override</option></select></label>
        <label>Imported chat template<textarea readOnly rows={3} value={models.find(m => m.id === model)?.chat_template || 'No chat template in this snapshot.'} /></label>
        <label>System prompt<textarea value={system} maxLength={8000} disabled={busy} onChange={e => setSystem(e.target.value)} placeholder="Requires a model with a chat template" /></label>
        <label>Output tokens<input type="number" value={maxTokens} min={1} max={256} disabled={busy} onChange={e => setMaxTokens(Number(e.target.value))} /></label>
        <label>Temperature<input type="number" value={temperature} min={0} max={2} step={0.1} disabled={busy} onChange={e => setTemperature(Number(e.target.value))} /></label>
        <label>Seed<input type="number" value={seed} min={0} max={2147483647} disabled={busy} onChange={e => setSeed(Number(e.target.value))} /></label>
      </div></details>
      {!models.length && <p className="muted">Import a model from <a href="#models">Models</a> to begin.</p>}
      <div className="chat-transcript" aria-label="Conversation">{messages.filter((m, i) => !(answers.length && i === messages.length - 1 && m.role === 'assistant')).map((message, index) => <article key={index} className={`chat-message chat-${message.role}`}><strong>{message.role}</strong><p>{message.content}</p></article>)}</div>
      {answers.length > 0 && <div className={`chat-arena ${answers.length > 1 ? 'chat-arena-pair' : ''}`}>{answers.map(answer => <article className="detail-box" key={answer.model}><h3>{models.find(m => m.id === answer.model)?.name || answer.model}</h3><p className="chat-output" aria-live="off">{answer.text || (answer.status === 'pending' ? 'Waiting for the local runtime…' : 'Generating…')}</p><p className="muted" role="status">{answer.status}{answer.seconds ? ` · ${answer.seconds.toFixed(2)} seconds including model load` : ''}{answer.usage ? ` · ${answer.usage.prompt_tokens} input / ${answer.usage.completion_tokens} output tokens` : ''}</p></article>)}</div>}
      <form className="chat-composer" onSubmit={send}><label>Message<textarea value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={16000} disabled={busy} required rows={3} /></label>
        <div className="actions"><button className="primary" disabled={busy || !model || !prompt.trim()}>Generate</button><button type="button" disabled={!busy} onClick={() => controller.current?.abort()}><Square size={16} /> Stop</button><button type="button" disabled={busy || !messages.length || !model} onClick={regenerate}><RotateCcw size={16} /> Regenerate</button></div></form>
      <p className="muted">Base models without a chat template accept one user prompt. Arena runs share the same conversation input; scores do not qualify a model for release.</p>
    </div></section></div>;
}
