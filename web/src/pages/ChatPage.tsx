import { Button, Disclosure, Field, Menu, MenuSection, MultilineField, SegmentedControl, Select, TextControl } from '../components/ui';
import { ConversationDialogs } from '../components/chat/ConversationDialogs';
import { ToolsChat } from './ToolsChat';
import { ResearchChat } from './ResearchChat';
import { SavedConversations } from '../components/chat/SavedConversations';
import { modelDisplayName, referenceInputError } from '../api/chat-input';
import { comparisonInput, matchedBaseModel, sharedOutputLimit, trainedChatModels } from '../api/chat-comparison';
import { allResources } from '../api/resources';
import { useResourceHandoff } from '../components/ResourceHandoff';
import { TextContent } from '../components/DataInspector';
import { ChatResponseContent, CopyResponseButton } from '../components/MarkdownResponse';
import { useDraft, DraftIndicator } from '../components/Draft';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Square, Download, RotateCcw, ArrowUp, Bot, User, Plus, SlidersHorizontal, MoreHorizontal, Pencil, Trash2 } from 'lucide-react';
import { apiRequest, errorMessage } from '../api/client';
import { ChatMessage, LocalModel, streamCompletion, TokenUsage } from '../api/inference';
import './chat-page.css';

interface Conversation { conversation_id: string; title: string; revision_no: number; messages: ChatMessage[]; configuration: Record<string, unknown> }
interface Answer { model: string; text: string; usage: TokenUsage | null; seconds: number; status: string; requestId?: string; error?: string; role?: 'base' | 'trained'; name?: string }
interface Comparison { review_campaign_id?: string | null; comparison_id: string; conversation_id: string; messages: ChatMessage[]; vote: string; created_at: string;
  sides: { label: string; text: string; model?: string; role?: 'base' | 'trained'; name?: string; usage?: TokenUsage; elapsed_seconds?: number; configuration?: Record<string, unknown> }[] }

const DEVICE_LABELS: Record<string, string> = { cpu: 'CPU', 'mps:0': 'Apple Silicon GPU (PyTorch)', 'mlx:0': 'Apple Silicon GPU (MLX)' };
const UNSAVED = ['unsaved', 'expired', 'unavailable'];

function answerText(answer: Answer, idle: string): string {
  return answer.text || (answer.status === 'idle' ? idle : answer.status === 'completed' ? 'The model stopped without generating text.'
    : answer.status === 'failed' || answer.status === 'stopped' ? 'No completed response.' : answer.status === 'pending' ? 'Waiting for the local runtime…' : 'Generating…');
}
function answerMeta(answer: Answer): string {
  return `${answer.status}${answer.seconds ? ` · ${answer.seconds.toFixed(2)} seconds including model load` : ''}${answer.usage ? ` · ${answer.usage.prompt_tokens} input / ${answer.usage.completion_tokens} output tokens` : ''}`;
}

export function ChatPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const selectionDraft = useDraft('chat-selection', { conversationId: '' });
  const [conversationId, setConversationId] = selectionDraft.field('conversationId');
  const conversation = conversations.find(c => c.conversation_id === conversationId) || null;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const draft = useDraft('chat-composer', { model: '', compare: '', comparisonMode: 'blind', compareDevice: 'cpu', prompt: '', system: '', promptFormat: 'model', device: 'cpu', temperature: 0, maxTokens: 128, seed: 42, renameTitle: '' }, conversationId || 'new');
  const [comparisonMode, setComparisonMode] = draft.field('comparisonMode');
  const baseComparison = comparisonMode === 'base-trained' || draft.status === 'empty' && conversation?.configuration.comparison_mode === 'base-trained';
  const [nextSelection, setNextSelection] = useState<{ model: string; paired: boolean } | null>(null);
  const [namedComparisons, setNamedComparisons] = useState<Comparison[]>([]);
  const [model, setModel] = draft.field('model');
  const [compare, setCompare] = draft.field('compare');
  const [compareDevice, setCompareDevice] = draft.field('compareDevice');
  const [prompt, setPrompt] = draft.field('prompt');
  const [system, setSystem] = draft.field('system');
  const [promptFormat, setPromptFormat] = draft.field('promptFormat');
  const [device, setDevice] = draft.field('device');
  const [temperature, setTemperature] = draft.field('temperature');
  const [maxTokens, setMaxTokens] = draft.field('maxTokens');
  const [seed, setSeed] = draft.field('seed');
  const [renameTitle, setRenameTitle] = draft.field('renameTitle');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const optionsId = useId(), systemId = useId(), templateId = useId();
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [answerInput, setAnswerInput] = useState<ChatMessage[]>([]);
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [voteBusy, setVoteBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [handoffModel, setHandoffModel] = useState<{ id: string; hasTemplate: boolean; compareBase: boolean } | null>(null);
  const stream = useRef<HTMLDivElement>(null);
  const followOutput = useRef(true);
  useEffect(() => {
    if (stream.current && followOutput.current) stream.current.scrollTop = stream.current.scrollHeight;
  }, [messages, answers, conversationId, baseComparison]);
  const selectedModel = models.find(m => m.id === model);
  const selectedCompare = models.find(m => m.id === compare);
  const devices = selectedModel?.devices || ['cpu'];
  const comparisonDevices = selectedCompare?.devices || ['cpu'];
  const trainedModels = trainedChatModels(models);
  const pairedBase = matchedBaseModel(selectedModel, models);
  const pairReady = !!pairedBase && compare === pairedBase.id;
  useEffect(() => {
    if (!baseComparison) return;
    setCompare(pairedBase?.id || '');
    if (pairedBase && selectedModel) {
      setMaxTokens(value => Math.min(value, sharedOutputLimit(selectedModel, pairedBase)));
    }
  }, [model, models, baseComparison]);
  useEffect(() => {
    if (!nextSelection || conversationId) return;
    setModel(nextSelection.model); setComparisonMode(nextSelection.paired ? 'base-trained' : 'blind'); setCompare('');
    const trained = models.find(value => value.id === nextSelection.model), base = matchedBaseModel(trained, models);
    setPromptFormat(trained?.chat_template && (!nextSelection.paired || base?.chat_template) ? 'model' : 'plain');
    setTemperature(0); setNextSelection(null);
  }, [nextSelection, conversationId, models]);
  useEffect(() => { if (!selectedModel) return; if (!devices.includes(device)) setDevice(devices[0]); if (selectedModel?.max_tokens) setMaxTokens(v => Math.min(v, selectedModel.max_tokens!, Math.max(1, (selectedModel.context_limit || 2048) - 8))); }, [model, models]);
  useEffect(() => { if (!selectedCompare) return; if (!comparisonDevices.includes(compareDevice)) setCompareDevice(comparisonDevices[0]); }, [compare, models]);
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    const [catalog, history, pairs] = await Promise.all([
      apiRequest<{ data: LocalModel[] }>('/api/v1/inference/models/', token, { signal }),
      allResources<Conversation>('/api/v1/chat-conversations/', token, signal).then(results => ({ results })),
      allResources<Comparison>('/api/v1/chat-comparisons/', token, signal).then(results => ({ results })),
    ]);
    if (!signal?.aborted) { setModels(catalog.data); setConversations(history.results); setComparisons(pairs.results); }
  }, [token]);
  useEffect(() => {
    if (!token.trim()) return;
    const c = new AbortController(); setLoading(true);
    void load(c.signal).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => { c.abort(); controller.current?.abort(); };
  }, [load, refreshKey, token]);
  useEffect(() => {
    if (!baseComparison || !token.trim()) return;
    const c = new AbortController();
    void allResources<Comparison>('/api/v1/chat-comparisons/?view=base-trained', token, c.signal)
      .then(values => { if (!c.signal.aborted) setNamedComparisons(values); })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => c.abort();
  }, [baseComparison, token, refreshKey]);
  function select(value: Conversation | null) {
    setOptionsOpen(false); setRenameOpen(false); setDeleteOpen(false);
    controller.current?.abort(); controller.current = null; setBusy(false); setConversationId(value?.conversation_id || ''); setMessages(value?.messages || []); setAnswers([]); setNotice(''); setError('');
    setComparison(comparisons.find(c => c.conversation_id === value?.conversation_id) || null);
  }
  useEffect(() => {
    setMessages(conversation?.messages || []);
    if (!conversation || draft.status !== 'empty') return;
    const config = conversation.configuration;
    setComparisonMode(config.comparison_mode === 'base-trained' ? 'base-trained' : 'blind');
    setModel(String(config.model || '')); setCompare(String(config.compare_model || '')); setDevice(String(config.device || 'cpu')); setCompareDevice(String(config.compare_device || 'cpu'));
    setSystem(String(config.system_prompt || '')); setTemperature(Number(config.temperature || 0)); setMaxTokens(Number(config.max_tokens || 128)); setSeed(Number(config.seed ?? 42)); setPromptFormat(String(config.prompt_format || 'model'));
  }, [conversation?.conversation_id]);

  async function run(history: ChatMessage[]) {
    if (controller.current || baseComparison && !pairReady) return;
    const generationHistory = comparisonInput(history, baseComparison);
    const inputMessages = system.trim() ? [{ role: 'system', content: system }, ...generationHistory] : generationHistory;
    const inputError = referenceInputError(selectedModel, inputMessages, maxTokens, temperature, promptFormat) || referenceInputError(selectedCompare, inputMessages, maxTokens, temperature, promptFormat);
    if (inputError) { setError(inputError); return; }
    followOutput.current = true;
    setBusy(true); setError(''); setNotice(''); setComparison(null);
    const c = new AbortController(); controller.current = c;
    const configuration = { model, compare_model: compare || null, comparison_mode: comparisonMode, compare_device: compareDevice, device, temperature, max_tokens: maxTokens, seed, system_prompt: system, prompt_format: promptFormat };
    const input = system.trim() ? [{ role: 'system' as const, content: system }, ...generationHistory] : generationHistory;
    setAnswerInput(input);
    const identifiers = baseComparison ? [compare, model] : [model, ...(compare ? [compare] : [])];
    const completed: Answer[] = [];
    setMessages(history); setAnswers(identifiers.map(id => ({ model: id, text: '', usage: null, seconds: 0, status: 'pending', role: baseComparison ? id === model ? 'trained' : 'base' : undefined })));
    let saveState = 'No completed output has been saved.';
    try {
      for (const identifier of identifiers) {
        const started = performance.now();
        const result: Answer = { model: identifier, text: '', usage: null, seconds: 0, status: 'generating', role: baseComparison ? identifier === model ? 'trained' : 'base' : undefined };
        if (c.signal.aborted || controller.current !== c) return;
        setAnswers(prior => prior.map(a => a.model === identifier ? { ...result } : a));
        try {
          result.requestId = await streamCompletion(token, { model: identifier, messages: input, device: identifier === model ? device : compareDevice, temperature, max_tokens: maxTokens, seed, prompt_format: promptFormat }, c.signal,
            text => { result.text += text; if (controller.current === c) setAnswers(prior => prior.map(a => a.model === identifier ? { ...result } : a)); },
            usage => { result.usage = usage; });
          if (c.signal.aborted || controller.current !== c) return;
          result.seconds = (performance.now() - started) / 1000; result.status = 'completed'; completed.push({ ...result });
          setAnswers(prior => prior.map(a => a.model === identifier ? { ...result } : a));
        } catch (e) {
          if (c.signal.aborted) throw e;
          result.status = 'failed'; result.error = errorMessage(e); result.seconds = (performance.now() - started) / 1000;
          if (controller.current === c) setAnswers(prior => prior.map(a => a.model === identifier ? { ...result } : a));
          if (!baseComparison) throw e;
        }
      }
      if (completed.length !== identifiers.length) throw new Error('Both responses must complete before this comparison can be saved. The completed response is still available below.');
      const primary = completed.find(answer => answer.model === model)!;
      const next = [...history, { role: 'assistant' as const, content: primary.text || '[Empty completion]' }];
      setMessages(next);
      const saved = await apiRequest<Conversation>(conversation ? `/api/v1/chat-conversations/${conversation.conversation_id}/` : '/api/v1/chat-conversations/', token,
        { method: conversation ? 'PATCH' : 'POST', signal: c.signal, body: JSON.stringify({ title: history.find(m => m.role === 'user')?.content.slice(0, 180) || 'Conversation',
          messages: next, configuration, ...(conversation ? { revision_no: conversation.revision_no } : {}) }) });
      if (c.signal.aborted || controller.current !== c) return;
      saveState = 'Conversation saved. Comparison save has not been confirmed.';
      setConversations(prior => [saved, ...prior.filter(v => v.conversation_id !== saved.conversation_id)]);
      setPrompt(''); setConversationId(saved.conversation_id);
      if (completed.length === 2) {
        const pair = await apiRequest<Comparison>(`/api/v1/chat-comparisons/${baseComparison ? '?view=base-trained' : ''}`, token, { method: 'POST', signal: c.signal,
          body: JSON.stringify({ conversation_id: saved.conversation_id, messages: input,
            responses: completed.map(answer => ({ request_id: answer.requestId, text: answer.text })) }) });
        if (c.signal.aborted || controller.current !== c) return;
        saveState = 'Conversation and informal comparison saved.'; setComparison(pair);
        if (baseComparison) setNamedComparisons(prior => [pair, ...prior.filter(value => value.comparison_id !== pair.comparison_id)]);
      }
      await load(c.signal);
      if (controller.current === c) setNotice(baseComparison ? 'Base and trained responses saved with the same prompt and generation settings.' : completed.length === 2 ? 'Conversation and comparison saved. Choose your preferred response to reveal the model names.' : 'Conversation saved.');
    } catch (e) {
      if (controller.current !== c) return;
      if (c.signal.aborted) setNotice(`Generation stopped. Partial output was not saved. ${saveState}`);
      else { setError(errorMessage(e)); setNotice(saveState); }
      setAnswers(prior => prior.map(a => a.status !== 'completed' ? { ...a, status: c.signal.aborted ? 'stopped' : 'failed' } : a));
    } finally { if (controller.current === c) { controller.current = null; setBusy(false); } }
  }
  function send(event: React.FormEvent) {
    event.preventDefault(); const text = prompt.trim(); if (!text || busy || voteBusy || !model || baseComparison && !pairReady) return;
    void run(messages.at(-1)?.role === 'user' && messages.at(-1)?.content === text ? messages : [...messages, { role: 'user', content: text }]);
  }
  function regenerate() {
    const history = messages.at(-1)?.role === 'assistant' ? messages.slice(0, -1) : messages;
    if (history.at(-1)?.role === 'user') void run(history);
  }
  function exportConversation() {
    const blob = new Blob([JSON.stringify({ conversation, messages, answers, comparisons: comparisons.filter(c => c.conversation_id === conversation?.conversation_id) }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'modelanvil-conversation.json'; anchor.click(); URL.revokeObjectURL(url);
  }
  async function recordVote(vote: string) {
    if (!comparison) return;
    setVoteBusy(true); setError('');
    try {
      const saved = await apiRequest<Comparison>(`/api/v1/chat-comparisons/${comparison.comparison_id}/vote/`, token,
        { method: 'POST', body: JSON.stringify({ vote }) });
      setComparison(saved); setComparisons(prior => prior.map(c => c.comparison_id === saved.comparison_id ? saved : c));
      setNotice('Preference saved with the exact generated responses.');
    } catch (e) { setError(errorMessage(e)); }
    finally { setVoteBusy(false); }
  }
  async function renameConversation(event: React.FormEvent) {
    event.preventDefault(); if (!conversation || !renameTitle.trim()) return;
    setBusy(true); setError('');
    try {
      const saved = await apiRequest<Conversation>(`/api/v1/chat-conversations/${conversation.conversation_id}/`, token, { method: 'PATCH', body: JSON.stringify({ title: renameTitle.trim(), revision_no: conversation.revision_no }) });
      setConversations(prior => prior.map(c => c.conversation_id === saved.conversation_id ? saved : c)); setRenameTitle(''); setRenameOpen(false); setNotice('Conversation renamed.');
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function deleteConversation() {
    if (!conversation) return;
    setBusy(true); setError('');
    try { await apiRequest(`/api/v1/chat-conversations/${conversation.conversation_id}/`, token, { method: 'DELETE' }); draft.discard(); select(null); await load(); setNotice('Conversation deleted.'); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function sendToReview() {
    if (!comparison) return;
    setVoteBusy(true); setError('');
    try { const result = await apiRequest<{ campaign_id: string }>(`/api/v1/chat-comparisons/${comparison.comparison_id}/review-batch/`, token, { method: 'POST', body: '{}' }); window.location.hash = `#annotation?campaign=${result.campaign_id}`; }
    catch (e) { setError(errorMessage(e)); } finally { setVoteBusy(false); }
  }
  const handoffError = useResourceHandoff(token, (kind, value) => { if (kind === 'model-version') {
    select(null); setHandoffModel({ id: value.model_version_id || '', hasTemplate: !!value.chat_template, compareBase: new URLSearchParams(window.location.hash.split('?')[1]).get('compare_base') === '1' });
  } });
  useEffect(() => {
    if (!handoffModel || conversationId || !models.length) return;
    const base = matchedBaseModel(models.find(value => value.id === handoffModel.id), models);
    setModel(handoffModel.id); setCompare(handoffModel.compareBase ? base?.id || '' : ''); setComparisonMode(handoffModel.compareBase ? 'base-trained' : 'blind'); setSystem('');
    setPromptFormat(handoffModel.hasTemplate && (!handoffModel.compareBase || base?.chat_template) ? 'model' : 'plain'); setTemperature(0);
    setNotice(handoffModel.compareBase ? 'Your trained model and its recorded base are selected. Test the same prompt on both.' : 'Your model is selected and ready. Ask a question from your dataset, then try a new example.');
    // Consume the handoff so reloading restores the saved conversation instead of starting over.
    const query = new URLSearchParams(window.location.hash.split('?')[1]);
    query.delete('model_version'); query.delete('compare_base');
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#chat${query.size ? `?${query}` : ''}`);
    setHandoffModel(null);
  }, [handoffModel, conversationId, models]);
  function changeView(paired: boolean) {
    const candidate = paired ? trainedModels.find(value => value.id === model) || trainedModels.find(value => matchedBaseModel(value, models)) || trainedModels[0] : selectedModel;
    select(null); setHandoffModel(null); setNextSelection({ model: candidate?.id || '', paired });
  }
  function chooseModel(id: string) {
    setHandoffModel(null); setModel(id);
    const candidate = models.find(m => m.id === id);
    setPromptFormat(candidate?.chat_template && (!baseComparison || matchedBaseModel(candidate, models)?.chat_template) ? 'model' : 'plain');
    if (candidate?.format === 'cpu-reference') setTemperature(0);
    if (id === compare) setCompare('');
    setDevice(candidate?.format === 'mlx' ? 'mlx:0' : 'cpu');
  }
  const savedNamed = comparison?.sides.some(side => side.role) ? comparison : namedComparisons.filter(pair => pair.conversation_id === conversationId).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const namedAnswers: Answer[] = answers.length ? answers : (savedNamed?.sides || []).filter(side => side.role && side.model).sort((a, b) => a.role === b.role ? 0 : a.role === 'base' ? -1 : 1).map(side => ({ model: side.model!, name: side.name, role: side.role, text: side.text, usage: side.usage || null, seconds: side.elapsed_seconds || 0, status: 'completed' }));
  const comparisonAnswers: Answer[] = namedAnswers.length ? namedAnswers : [
    { model: pairedBase?.id || 'base', name: pairedBase?.name || (loading ? 'Loading base model…' : 'Base model unavailable'), role: 'base', text: '', usage: null, seconds: 0, status: 'idle' },
    { model: selectedModel?.id || 'trained', name: selectedModel?.name || (loading ? 'Loading trained model…' : 'Choose a trained model'), role: 'trained', text: '', usage: null, seconds: 0, status: 'idle' },
  ];
  const draftUnsaved = UNSAVED.includes(draft.status);
  const showOptions = optionsOpen || !!error || !!handoffError || baseComparison && !loading && !pairReady || draftUnsaved;
  const singleAnswer = !comparison && answers.length === 1 ? answers[0] : null;
  const comparisonInputMessages = answers.length ? answerInput : savedNamed?.messages || [];
  const view: 'chat' | 'compare' = baseComparison ? 'compare' : 'chat';
  const [workspace, setWorkspace] = useState<'conversation' | 'tools' | 'research'>('conversation');
  const locked = busy || voteBusy;
  const deviceOptions = (values: string[]) => values.map(value => ({ value, label: DEVICE_LABELS[value] || value }));

  return <div className={`chat-page${baseComparison ? ' chat-page-comparison' : ''}`} data-options-open={showOptions}>
    <div className="chat-toolbar">
      <SegmentedControl label="Chat view" value={workspace === 'conversation' ? view : workspace} onChange={next => { if (next === 'tools' || next === 'research') setWorkspace(next); else { setWorkspace('conversation'); changeView(next === 'compare'); } }}
        options={[{ value: 'chat', label: 'Chat', disabled: locked }, { value: 'compare', label: 'Base vs trained', disabled: locked }, { value: 'tools', label: 'Tools', disabled: locked }, { value: 'research', label: 'Documents & research', disabled: locked }]} />
      <Select className="chat-model-select" aria-label={baseComparison ? 'Trained model' : 'Model'} value={model} required disabled={busy} onChange={event => chooseModel(event.target.value)}>
        <option value="">{baseComparison ? 'Select a trained model' : 'Select a model'}</option>
        {(baseComparison ? trainedModels : models).map(m => <option key={m.id} value={m.id}>{modelDisplayName(m.name)}</option>)}
      </Select>
      {baseComparison && <Field className="chat-base-field" aria-label="Base model" readOnly value={pairedBase ? modelDisplayName(pairedBase.name) : loading ? 'Loading base model…' : 'Base model unavailable for chat'} />}
      <div className="chat-toolbar-actions">
        <Button type="button" disabled={locked} onClick={() => select(null)}><Plus size={16} aria-hidden="true" />New conversation</Button>
        <Menu label="Conversation actions" icon={<MoreHorizontal size={18} aria-hidden="true" />}>
          <MenuSection>
            <Button type="button" variant="quiet" disabled={busy || !messages.length} onClick={exportConversation}><Download size={16} aria-hidden="true" />Export conversation</Button>
            <Button type="button" variant="quiet" disabled={!conversation || locked} onClick={() => { setRenameTitle(conversation?.title || ''); setRenameOpen(true); }}><Pencil size={16} aria-hidden="true" />Rename conversation…</Button>
            <Button type="button" variant="quiet" disabled={!conversation || locked} onClick={() => setDeleteOpen(true)}><Trash2 size={16} aria-hidden="true" />Delete conversation…</Button>
          </MenuSection>
        </Menu>
        {baseComparison && <Button className="chat-mobile-options" type="button" variant="quiet" icon aria-label="Chat options" title="Chat options" aria-expanded={showOptions} aria-controls={optionsId} onClick={() => setOptionsOpen(value => !value)}><SlidersHorizontal size={17} aria-hidden="true" /></Button>}
      </div>
    </div>
    {workspace === 'tools' ? <ToolsChat key={`tools-${token}`} token={token} refreshKey={refreshKey} /> : workspace === 'research' ? <ResearchChat key={`research-${token}`} token={token} refreshKey={refreshKey} /> : <>
    <div className="chat-options" id={optionsId}>
      <SavedConversations conversations={conversations} selectedId={conversation?.conversation_id || ''} locked={locked} open={historyOpen} onToggle={setHistoryOpen}
        onSelect={id => { select(conversations.find(c => c.conversation_id === id) || null); setHistoryOpen(false); }} />
      <Disclosure summary="Generation settings" variant="quiet">
        <div data-ui="field-grid" className="chat-settings-grid">
          {!baseComparison && <Select label="Compare with" value={compare} disabled={busy} onChange={event => { setCompare(event.target.value); setCompareDevice(models.find(m => m.id === event.target.value)?.format === 'mlx' ? 'mlx:0' : 'cpu'); }}>
            <option value="">Single model</option>{models.filter(m => m.id !== model).map(m => <option key={m.id} value={m.id}>{modelDisplayName(m.name)}</option>)}
          </Select>}
          <Select label="Device" value={device} disabled={busy} onChange={event => setDevice(event.target.value)} options={deviceOptions(devices)} />
          {compare && <Select label="Comparison device" value={compareDevice} disabled={busy} onChange={event => setCompareDevice(event.target.value)} options={deviceOptions(comparisonDevices)} />}
          <Select label="Prompt formatting" value={promptFormat} disabled={busy} onChange={event => setPromptFormat(event.target.value)}
            options={[{ value: 'model', label: 'Imported model template' }, { value: 'plain', label: 'Plain text (one user prompt)' }, { value: 'chatml', label: 'ChatML override' }]} />
          <TextControl label="Output tokens" type="number" value={maxTokens} min={1} max={baseComparison ? sharedOutputLimit(selectedModel, pairedBase) : selectedModel?.max_tokens || 256} disabled={busy} onChange={event => setMaxTokens(Number(event.target.value))} />
          <TextControl label="Temperature" type="number" value={temperature} min={0} max={2} step={0.1} disabled={busy} onChange={event => setTemperature(Number(event.target.value))} />
          <TextControl label="Seed" type="number" value={seed} min={0} max={2147483647} disabled={busy} onChange={event => setSeed(Number(event.target.value))} />
          <div data-ui="control" data-span="full"><label data-ui="control-label" htmlFor={systemId}>System prompt</label><MultilineField id={systemId} rows={2} value={system} maxLength={8000} disabled={busy} onChange={event => setSystem(event.target.value)} placeholder="Requires a model with a chat template" /></div>
        </div>
        {selectedModel && <p className="muted">Context {selectedModel.context_limit?.toLocaleString() ?? 'not reported'} · output ≤{selectedModel.max_tokens ?? 256} tokens.</p>}
        <Disclosure summary="Model details" variant="quiet">
          <div data-ui="control"><label data-ui="control-label" htmlFor={templateId}>Chat template</label><MultilineField id={templateId} readOnly rows={3} value={selectedModel?.chat_template || 'No chat template in this model.'} /></div>
          <p className="muted">Base models without a chat template accept one user prompt. Comparisons use the same input and settings.</p>
        </Disclosure>
      </Disclosure>
    </div>
    {handoffError && <p className="error-text" role="alert">{handoffError}</p>}
    {error && <p className="error-text" role="alert">{error}</p>}
    {notice && <p className={namedAnswers.length ? 'chat-notice chat-notice-saved' : 'chat-notice'} role="status">{notice}</p>}
    {loading && <p className="muted" role="status">Loading models and saved conversations…</p>}
    {baseComparison && !loading && !pairReady && <p className="muted" role="status">{pairedBase ? 'Preparing the base model comparison…' : trainedModels.length ? 'The exact base model is unavailable. Choose another trained model or restore its base in Models.' : 'No completed trained models are available for comparison. Complete a training run first.'}</p>}
    {!loading && !models.length && <p className="muted">Import a model from <a href="#models">Models</a> to begin.</p>}
    <div className="chat-stream" ref={stream} onScroll={event => { const area = event.currentTarget; followOutput.current = area.scrollHeight - area.scrollTop - area.clientHeight < 80; }}>
      {!baseComparison && <div className="chat-transcript" role="log" aria-label="Conversation" aria-busy={busy}>
        {!messages.length && !answers.length && <div className="chat-empty"><span className="chat-empty-icon"><Bot size={28} aria-hidden="true" /></span><h2>What would you like to try?</h2><p>{model ? 'Ask your model a question, or try an example from your dataset.' : 'Choose a model above, then send your first message.'}</p></div>}
        {messages.filter((m, i) => !(answers.length && i === messages.length - 1 && m.role === 'assistant')).map((message, index) => <article key={index} className={`chat-message chat-${message.role}`}>
          <header className="chat-message-author">{message.role === 'user' ? <User size={17} aria-hidden="true" /> : <Bot size={17} aria-hidden="true" />}<strong>{message.role === 'user' ? 'You' : message.role === 'assistant' ? 'Assistant' : 'System'}</strong></header>
          {message.role === 'assistant' ? <ChatResponseContent text={message.content} /> : <TextContent text={message.content} />}
        </article>)}
        {singleAnswer && <article className="chat-message chat-assistant" aria-label="Assistant response">
          <header className="chat-message-author"><Bot size={17} aria-hidden="true" /><strong>Assistant</strong><span>{modelDisplayName(selectedModel?.name || singleAnswer.model)}</span></header>
          <ChatResponseContent copyable={!!singleAnswer.text} text={singleAnswer.text || (singleAnswer.status === 'completed' ? 'The model stopped without generating text.' : singleAnswer.status === 'failed' || singleAnswer.status === 'stopped' ? 'No completed response.' : 'Thinking…')} />
          <span className="chat-reply-status" role="status">{singleAnswer.status === 'generating' || singleAnswer.status === 'pending' ? 'Generating a response…' : singleAnswer.status === 'failed' ? 'Response failed' : singleAnswer.status === 'stopped' ? 'Generation stopped' : ''}</span>
          {singleAnswer.seconds > 0 && <Disclosure summary="Response details" variant="quiet"><p className="muted">{singleAnswer.seconds.toFixed(2)} seconds including model load{singleAnswer.usage ? ` · ${singleAnswer.usage.prompt_tokens} input / ${singleAnswer.usage.completion_tokens} output tokens` : ''}</p></Disclosure>}
        </article>}
      </div>}
      {baseComparison && <section className="chat-model-comparison" aria-label="Base and trained model responses">
        <div className="chat-comparison-heading"><h2>Base vs trained responses</h2><p>Same prompt and settings in a fresh context. Answers generate one at a time.</p></div>
        {comparisonInputMessages.length > 0 && <Disclosure className="chat-comparison-input" variant="quiet" summary={<span>Prompt: {comparisonInputMessages.filter(message => message.role === 'user').at(-1)?.content}</span>}>
          <div role="group" aria-label="Shared comparison input">{comparisonInputMessages.map((message, index) => <article className="chat-message chat-user" key={index}><strong>{message.role === 'system' ? 'System instructions' : 'Shared prompt'}</strong><TextContent text={message.content} /></article>)}</div>
          {!answers.length && savedNamed && <Select label="Saved prompt comparison" value={savedNamed.comparison_id} disabled={busy} onChange={event => setComparison(namedComparisons.find(pair => pair.comparison_id === event.target.value) || null)}
            options={namedComparisons.filter(pair => pair.conversation_id === conversationId && pair.sides.some(side => side.role)).map(pair => ({ value: pair.comparison_id, label: new Date(pair.created_at).toLocaleString() }))} />}
        </Disclosure>}
        <div className="chat-comparison-columns" role="region" aria-label="Model responses"><div className="chat-arena chat-arena-pair">{comparisonAnswers.map(answer => <article className={`chat-message chat-comparison-card chat-comparison-${answer.role}`} key={answer.model} aria-label={answer.role === 'base' ? 'Base model response' : 'Trained model response'}>
          <header><div><p data-ui="kicker">{answer.role === 'base' ? 'Base model' : 'Trained model'}</p><h3>{modelDisplayName(answer.name || models.find(value => value.id === answer.model)?.name || answer.model)}</h3></div>{answer.text && <CopyResponseButton text={answer.text} />}</header>
          <div className="chat-comparison-text" role="region" aria-label={`${answer.role === 'base' ? 'Base' : 'Trained'} answer text`} tabIndex={0}><ChatResponseContent copyable={false} text={answerText(answer, 'Send a message below. The response will appear here.')} /></div>
          {answer.error && <p role="alert" className="error-text">{answer.error}</p>}
          {answer.status !== 'idle' && <p className={`muted chat-comparison-status chat-comparison-status-${answer.status}`} role="status">{answerMeta(answer)}</p>}
        </article>)}</div></div>
      </section>}
      {comparison && !baseComparison && <section className="chat-saved-comparison" aria-label="Saved model comparison">
        <div className="chat-saved-comparison-head">
          <Select label="Saved comparison" value={comparison.comparison_id} disabled={locked} onChange={event => setComparison(comparisons.find(c => c.comparison_id === event.target.value) || null)}
            options={comparisons.filter(c => c.conversation_id === conversation?.conversation_id).map(c => ({ value: c.comparison_id, label: `${new Date(c.created_at).toLocaleString()} · ${c.vote || 'Not voted'}` }))} />
          <Button type="button" disabled={locked} onClick={() => void sendToReview()}>{comparison.review_campaign_id ? 'Open independent review batch' : 'Send comparison to independent review'}</Button>
        </div>
        <Disclosure summary="Comparison input" variant="quiet">{comparison.messages.map((message, index) => <p key={index}><strong>{message.role}</strong>: {message.content}</p>)}</Disclosure>
        <div className="chat-arena chat-arena-pair">{comparison.sides.map(side => <article className="chat-message chat-comparison-card" key={side.label}><h2>Response {side.label}{side.name ? ` · ${side.name}` : ''}</h2><ChatResponseContent text={side.text} />{side.usage && <p className="muted">{side.usage.prompt_tokens} input / {side.usage.completion_tokens} output tokens</p>}</article>)}</div>
        <fieldset className="chat-vote"><legend>Which response do you prefer?</legend>
          <div data-ui="actions">{[['A', 'Prefer A'], ['B', 'Prefer B'], ['tie', 'Tie'], ['neither', 'Neither']].map(([vote, label]) => <Button type="button" key={vote} disabled={locked || !!comparison.vote} onClick={() => void recordVote(vote)}>{label}</Button>)}</div>
          {comparison.vote && <p role="status">Recorded preference: {comparison.vote}. Model identities are revealed above.</p>}
          <p className="muted">This comparison is informal. An arena vote does not become qualified human feedback.</p>
        </fieldset>
      </section>}
      {!comparison && !baseComparison && answers.length > 1 && <div className="chat-arena chat-arena-pair">{answers.map((answer, index) => <article className="chat-message chat-comparison-card" key={answer.model}><h2>Response {index + 1}</h2><ChatResponseContent copyable={!!answer.text} text={answerText(answer, '')} /><p className="muted" role="status">{answerMeta(answer)}</p></article>)}</div>}
    </div>
    <form className="chat-composer" onSubmit={send}>
      <label className="chat-composer-box"><span className="chat-visually-hidden">Message</span>
        <MultilineField aria-label="Message" aria-describedby="chat-keyboard-hint" placeholder={baseComparison ? 'Ask both models…' : 'Message your model…'} value={prompt} onChange={event => setPrompt(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} maxLength={16000} disabled={busy} required rows={1} />
      </label>
      <div className="chat-composer-footer">
        <small id="chat-keyboard-hint">Enter to send · Shift + Enter for a new line</small>
        <div data-ui="actions">
          {busy ? <Button type="button" onClick={() => controller.current?.abort()}><Square size={16} aria-hidden="true" />Stop</Button>
            : <Button type="button" variant="quiet" title="Regenerate" disabled={voteBusy || !messages.length || !model || baseComparison && !pairReady} onClick={regenerate}><RotateCcw size={16} aria-hidden="true" />Regenerate</Button>}
          <Button variant="primary" aria-label="Send message" disabled={locked || !model || !prompt.trim() || baseComparison && !pairReady}>Send<ArrowUp size={17} aria-hidden="true" /></Button>
        </div>
      </div>
    </form>
    {draftUnsaved && <DraftIndicator draft={draft} disabled={locked} />}
    </>}
    <ConversationDialogs title={conversation?.title} busy={busy} renameOpen={renameOpen} renameTitle={renameTitle} deleteOpen={deleteOpen}
      onRenameTitle={setRenameTitle} onRename={renameConversation} onCloseRename={() => setRenameOpen(false)} onDelete={() => { setDeleteOpen(false); void deleteConversation(); }} onCloseDelete={() => setDeleteOpen(false)} />
  </div>;
}
