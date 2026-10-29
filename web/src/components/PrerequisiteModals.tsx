import React, { useEffect, useId, useState } from 'react';
import { Button, Dialog, MultilineField, Notice, Select, TextControl } from './ui';
import { ObjectFields } from './FormEditors';
import { objectInput } from './form-data';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import type { Project, Team, TokenizerVersion, RegisteredModelVersion } from '../api/resources';

interface ModelOption { id: number; model_id: string; name: string }

const TOKENIZER_PRESETS = {
  llama: { name: 'Llama-3-Tokenizer', vocabulary: '128256', tokens: '{\n  "bos_token": "<|begin_of_text|>",\n  "eos_token": "<|end_of_text|>"\n}' },
  mistral: { name: 'Mistral-Tokenizer', vocabulary: '32000', tokens: '{\n  "bos_token": "<s>",\n  "eos_token": "</s>"\n}' },
  gpt2: { name: 'GPT2-Tokenizer', vocabulary: '50257', tokens: '{\n  "bos_token": "<|endoftext|>"\n}' },
} as const;

export function RegisterTokenizerModal({ token, isOpen, onClose, onSuccess }: {
  token: string; isOpen: boolean; onClose: () => void; onSuccess: (tokenizer: TokenizerVersion) => void;
}) {
  const formId = useId();
  const [name, setName] = useState<string>(TOKENIZER_PRESETS.llama.name);
  const [vocabSize, setVocabSize] = useState<string>(TOKENIZER_PRESETS.llama.vocabulary);
  const [specialTokens, setSpecialTokens] = useState<string>(TOKENIZER_PRESETS.llama.tokens);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function applyPreset(preset: keyof typeof TOKENIZER_PRESETS) {
    setName(TOKENIZER_PRESETS[preset].name); setVocabSize(TOKENIZER_PRESETS[preset].vocabulary); setSpecialTokens(TOKENIZER_PRESETS[preset].tokens);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    let parsedTokens: Record<string, unknown>;
    try {
      parsedTokens = objectInput(specialTokens);
      if (Object.values(parsedTokens).some(value => typeof value !== 'string')) throw new Error('Each special token must have a text symbol.');
    } catch (e) { setError(errorMessage(e)); setBusy(false); return; }
    try {
      const created = await apiRequest<TokenizerVersion>('/api/v1/tokenizers/', token, {
        method: 'POST', body: JSON.stringify({ name: name.trim(), vocabulary_size: Number(vocabSize), special_tokens: parsedTokens }),
      });
      onSuccess(created); onClose();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return <Dialog title="Register tokenizer" description="Declare the vocabulary size and special tokens a model version needs." open={isOpen} onClose={onClose}
    footer={<><Button type="button" disabled={busy} onClick={onClose}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || !name.trim()}>{busy ? 'Registering…' : 'Register tokenizer'}</Button></>}>
    <div data-ui="actions">
      <span className="muted">Presets</span>
      <Button type="button" size="sm" onClick={() => applyPreset('llama')}>Llama 3</Button>
      <Button type="button" size="sm" onClick={() => applyPreset('mistral')}>Mistral</Button>
      <Button type="button" size="sm" onClick={() => applyPreset('gpt2')}>GPT-2</Button>
    </div>
    <form id={formId} data-ui="form" onSubmit={submit}>
      {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
      <div data-ui="field-grid">
        <TextControl label="Tokenizer name" required maxLength={100} value={name} onChange={event => setName(event.target.value)} placeholder="Llama-3-Tokenizer" />
        <TextControl label="Vocabulary size" required type="number" min="1" max="1000000" value={vocabSize} onChange={event => setVocabSize(event.target.value)} />
      </div>
      <ObjectFields title="Special tokens" description="Map each token name to its symbol. Presets fill the common tokens." textOnly nameLabel="Token name" valueLabel="Token symbol"
        suggestions={['bos_token', 'eos_token', 'pad_token', 'unk_token']} value={specialTokens} onChange={setSpecialTokens} disabled={busy} />
    </form>
  </Dialog>;
}

const VERSION_PRESETS = {
  llama8b: { architecture: 'modelanvil/llama-3-8b', parameters: '8030000000', license: 'apache-2.0' },
  mistral7b: { architecture: 'modelanvil/mistral-7b', parameters: '7240000000', license: 'apache-2.0' },
  anvil125m: { architecture: 'modelanvil/anvil-scratch-svg-small', parameters: '125000000', license: 'mit' },
} as const;

export function RegisterModelVersionModal({ token, isOpen, onClose, onSuccess }: {
  token: string; isOpen: boolean; onClose: () => void; onSuccess: (version: RegisteredModelVersion) => void;
}) {
  const formId = useId();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [tokenizers, setTokenizers] = useState<TokenizerVersion[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [newModelName, setNewModelName] = useState('');
  const [isCreatingModel, setIsCreatingModel] = useState(false);
  const [selectedTokenizer, setSelectedTokenizer] = useState('');
  const [architectureRef, setArchitectureRef] = useState<string>(VERSION_PRESETS.llama8b.architecture);
  const [parametersCount, setParametersCount] = useState<string>(VERSION_PRESETS.llama8b.parameters);
  const [revisionNo, setRevisionNo] = useState('1');
  const [license, setLicense] = useState<string>(VERSION_PRESETS.llama8b.license);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController();
    Promise.all([apiPage<ModelOption>('/api/v1/models/', token, controller.signal), apiPage<TokenizerVersion>('/api/v1/tokenizers/', token, controller.signal)])
      .then(([modelPage, tokenizerPage]) => {
        if (controller.signal.aborted) return;
        setModels(modelPage.results); setTokenizers(tokenizerPage.results);
        setSelectedModel(current => current || (modelPage.results[0] ? String(modelPage.results[0].id) : ''));
        setSelectedTokenizer(current => current || (tokenizerPage.results[0] ? String(tokenizerPage.results[0].id) : ''));
      })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
  }, [isOpen, token]);

  function applyPreset(preset: keyof typeof VERSION_PRESETS) {
    setArchitectureRef(VERSION_PRESETS[preset].architecture); setParametersCount(VERSION_PRESETS[preset].parameters); setLicense(VERSION_PRESETS[preset].license);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      let modelId: number | '' = selectedModel ? Number(selectedModel) : '';
      if (isCreatingModel && newModelName.trim()) {
        const createdModel = await apiRequest<{ id: number }>('/api/v1/models/', token, {
          method: 'POST', body: JSON.stringify({ name: newModelName.trim(), description: `Model for ${architectureRef}`, intended_tasks: ['text_generation', 'reasoning'] }),
        });
        modelId = createdModel.id;
      }
      if (!modelId) { setError('Select or name a model.'); return; }
      if (!selectedTokenizer) { setError('Select a tokenizer.'); return; }
      const created = await apiRequest<RegisteredModelVersion>('/api/v1/model-versions/', token, {
        method: 'POST', body: JSON.stringify({ model: modelId, tokenizer: Number(selectedTokenizer), revision_no: Number(revisionNo), architecture_ref: architectureRef.trim(), parameters_count: Number(parametersCount), state: 'draft', license_evidence: license.trim() }),
      });
      onSuccess(created); onClose();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return <Dialog title="Register model version" description="Pin a version to an architecture reference and tokenizer. New versions start as drafts." open={isOpen} onClose={onClose}
    footer={<><Button type="button" disabled={busy} onClick={onClose}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || (!selectedModel && !newModelName.trim()) || !selectedTokenizer}>{busy ? 'Registering…' : 'Register model version'}</Button></>}>
    <div data-ui="actions">
      <span className="muted">Presets</span>
      <Button type="button" size="sm" onClick={() => applyPreset('llama8b')}>Llama 3 8B</Button>
      <Button type="button" size="sm" onClick={() => applyPreset('mistral7b')}>Mistral 7B</Button>
      <Button type="button" size="sm" onClick={() => applyPreset('anvil125m')}>Anvil 125M</Button>
    </div>
    <form id={formId} data-ui="form" onSubmit={submit}>
      {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
      <div data-ui="field-grid">
        {isCreatingModel
          ? <TextControl label="New model name" required maxLength={200} value={newModelName} onChange={event => setNewModelName(event.target.value)} placeholder="My custom model" />
          : <Select label="Model" required value={selectedModel} onChange={event => setSelectedModel(event.target.value)}>
            <option value="">Select a model</option>{models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
          </Select>}
        <Select label="Tokenizer version" required value={selectedTokenizer} onChange={event => setSelectedTokenizer(event.target.value)}>
          <option value="">Select a tokenizer</option>{tokenizers.map(item => <option key={item.id} value={item.id}>{item.name} · r{item.revision_no} ({item.vocabulary_size} vocab)</option>)}
        </Select>
        <div data-ui="actions" data-span="full"><Button type="button" variant="quiet" size="sm" onClick={() => setIsCreatingModel(value => !value)}>{isCreatingModel ? 'Use an existing model' : 'Name a new model instead'}</Button></div>
        <div data-span="full"><TextControl label="Architecture reference" required maxLength={200} value={architectureRef} onChange={event => setArchitectureRef(event.target.value)} /></div>
        <TextControl label="Parameter count" required type="number" min="1" value={parametersCount} onChange={event => setParametersCount(event.target.value)} />
        <TextControl label="Revision number" required type="number" min="1" value={revisionNo} onChange={event => setRevisionNo(event.target.value)} />
        <div data-span="full"><TextControl label="License" required value={license} onChange={event => setLicense(event.target.value)} /></div>
      </div>
    </form>
  </Dialog>;
}

export function CreateProjectModal({ token, isOpen, onClose, onSuccess }: {
  token: string; isOpen: boolean; onClose: () => void; onSuccess: (project: Project) => void;
}) {
  const formId = useId();
  const descriptionId = useId();
  const [teamsLoading, setTeamsLoading] = useState(false);
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeam, setSelectedTeam] = useState('');
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const controller = new AbortController(); setTeamsLoading(true);
    apiPage<Team>('/api/v1/teams/', token, controller.signal)
      .then(page => { if (controller.signal.aborted) return; setTeams(page.results); if (page.results[0]) setSelectedTeam(page.results[0].id); })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setTeamsLoading(false); });
    return () => controller.abort();
  }, [isOpen, token]);

  function handleNameChange(value: string) {
    setName(value);
    if (!slug || slug === name.toLowerCase().replace(/[^a-z0-9]+/g, '-')) setSlug(value.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 64));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      let teamId = selectedTeam;
      if (!teamId) {
        // Create a default owning team when the organization has none yet.
        const createdTeam = await apiRequest<Team>('/api/v1/teams/', token, {
          method: 'POST', body: JSON.stringify({ name: 'Core Engineering', slug: 'core-engineering', description: 'Default project owning team' }),
        });
        teamId = createdTeam.id;
      }
      const created = await apiRequest<Project>('/api/v1/projects/', token, {
        method: 'POST', body: JSON.stringify({ team: teamId, name: name.trim(), slug: slug.trim(), description: description.trim() }),
      });
      onSuccess(created); onClose();
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }

  return <Dialog title="Create project" description="A project scopes datasets, models and training runs." open={isOpen} onClose={onClose}
    footer={<><Button type="button" disabled={busy} onClick={onClose}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || teamsLoading || !name.trim() || !slug.trim()}>{busy ? 'Creating…' : 'Create project'}</Button></>}>
    <form id={formId} data-ui="form" onSubmit={submit}>
      {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
      {teams.length > 1 && <Select label="Team" required value={selectedTeam} onChange={event => setSelectedTeam(event.target.value)}
        options={teams.map(team => ({ value: team.id, label: `${team.name} (${team.slug})` }))} />}
      <TextControl label="Project name" required maxLength={200} value={name} onChange={event => handleNameChange(event.target.value)} placeholder="Reasoning and alignment model" autoFocus />
      <TextControl label="Project slug" required maxLength={64} value={slug} onChange={event => setSlug(event.target.value)} placeholder="reasoning-alignment" />
      <div data-ui="control"><label data-ui="control-label" htmlFor={descriptionId}>Description</label><MultilineField id={descriptionId} rows={3} value={description} onChange={event => setDescription(event.target.value)} placeholder="Objective and scope of this project" /></div>
    </form>
  </Dialog>;
}
