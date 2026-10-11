import React, { useEffect, useRef, useState } from 'react';
import { X, Sparkles, BookOpen, Layers, FolderPlus } from 'lucide-react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import type { Project, Team, TokenizerVersion, RegisteredModelVersion } from '../api/resources';

interface ModelOption { id: number; model_id: string; name: string }

export function RegisterTokenizerModal({
  token,
  isOpen,
  onClose,
  onSuccess,
}: {
  token: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (tok: TokenizerVersion) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState('Llama-3-Tokenizer');
  const [vocabSize, setVocabSize] = useState('128256');
  const [specialTokens, setSpecialTokens] = useState('{\n  "bos_token": "<|begin_of_text|>",\n  "eos_token": "<|end_of_text|>"\n}');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      dialogRef.current?.showModal();
    } else {
      dialogRef.current?.close();
    }
  }, [isOpen]);

  function applyPreset(preset: 'llama' | 'mistral' | 'gpt2') {
    if (preset === 'llama') {
      setName('Llama-3-Tokenizer');
      setVocabSize('128256');
      setSpecialTokens('{\n  "bos_token": "<|begin_of_text|>",\n  "eos_token": "<|end_of_text|>"\n}');
    } else if (preset === 'mistral') {
      setName('Mistral-Tokenizer');
      setVocabSize('32000');
      setSpecialTokens('{\n  "bos_token": "<s>",\n  "eos_token": "</s>"\n}');
    } else {
      setName('GPT2-Tokenizer');
      setVocabSize('50257');
      setSpecialTokens('{\n  "bos_token": "<|endoftext|>"\n}');
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    let parsedTokens: Record<string, string> = {};
    try {
      if (specialTokens.trim()) {
        parsedTokens = JSON.parse(specialTokens);
      }
    } catch {
      setError('Special tokens must be valid JSON object.');
      setBusy(false);
      return;
    }

    try {
      const created = await apiRequest<TokenizerVersion>('/api/v1/tokenizers/', token, {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          vocabulary_size: Number(vocabSize),
          special_tokens: parsedTokens,
        }),
      });
      onSuccess(created);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="connection-dialog"
      aria-labelledby="reg-tokenizer-title"
      onCancel={onClose}
      onClose={onClose}
    >
      <div className="dialog-title">
        <h2 id="reg-tokenizer-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <BookOpen size={18} aria-hidden="true" /> Register Tokenizer
        </h2>
        <button className="icon-button" aria-label="Close dialog" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <p className="muted" style={{ margin: '8px 0 16px' }}>
        Declare vocabulary boundaries and special token mappings required for model tokenization.
      </p>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        <button type="button" onClick={() => applyPreset('llama')}>
          <Sparkles size={13} /> Llama 3
        </button>
        <button type="button" onClick={() => applyPreset('mistral')}>
          <Sparkles size={13} /> Mistral
        </button>
        <button type="button" onClick={() => applyPreset('gpt2')}>
          <Sparkles size={13} /> GPT-2
        </button>
      </div>

      <form className="api-key" onSubmit={submit} style={{ marginTop: '0' }}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <label htmlFor="tok-name">Tokenizer Name</label>
        <input
          id="tok-name"
          required
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Llama-3-Tokenizer"
        />

        <label htmlFor="tok-vocab">Vocabulary Size</label>
        <input
          id="tok-vocab"
          required
          type="number"
          min="1"
          max="1000000"
          value={vocabSize}
          onChange={(e) => setVocabSize(e.target.value)}
        />

        <label htmlFor="tok-specials">Special Tokens (JSON)</label>
        <textarea
          id="tok-specials"
          rows={3}
          value={specialTokens}
          onChange={(e) => setSpecialTokens(e.target.value)}
          spellCheck={false}
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' }}>
          <button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button className="primary" type="submit" disabled={busy || !name.trim()}>
            {busy ? 'Registering…' : 'Register Tokenizer'}
          </button>
        </div>
      </form>
    </dialog>
  );
}

export function RegisterModelVersionModal({
  token,
  isOpen,
  onClose,
  onSuccess,
}: {
  token: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (mv: RegisteredModelVersion) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [tokenizers, setTokenizers] = useState<TokenizerVersion[]>([]);
  const [selectedModel, setSelectedModel] = useState<number | ''>('');
  const [newModelName, setNewModelName] = useState('');
  const [isCreatingModel, setIsCreatingModel] = useState(false);
  const [selectedTokenizer, setSelectedTokenizer] = useState<number | ''>('');
  const [architectureRef, setArchitectureRef] = useState('modelanvil/llama-3-8b');
  const [parametersCount, setParametersCount] = useState('8030000000');
  const [state, setState] = useState('draft');
  const [revisionNo, setRevisionNo] = useState('1');
  const [license, setLicense] = useState('apache-2.0');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      dialogRef.current?.showModal();
      void loadDependencies();
    } else {
      dialogRef.current?.close();
    }
  }, [isOpen, token]);

  async function loadDependencies() {
    try {
      const [mPage, tPage] = await Promise.all([
        apiPage<ModelOption>('/api/v1/models/', token),
        apiPage<TokenizerVersion>('/api/v1/tokenizers/', token),
      ]);
      setModels(mPage.results);
      if (mPage.results.length > 0 && selectedModel === '') {
        setSelectedModel(mPage.results[0].id);
      }
      setTokenizers(tPage.results);
      if (tPage.results.length > 0 && selectedTokenizer === '') {
        setSelectedTokenizer(tPage.results[0].id);
      }
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  function applyPreset(preset: 'llama8b' | 'mistral7b' | 'anvil125m') {
    if (preset === 'llama8b') {
      setArchitectureRef('modelanvil/llama-3-8b');
      setParametersCount('8030000000');
      setLicense('apache-2.0');
    } else if (preset === 'mistral7b') {
      setArchitectureRef('modelanvil/mistral-7b');
      setParametersCount('7240000000');
      setLicense('apache-2.0');
    } else {
      setArchitectureRef('modelanvil/anvil-scratch-svg-small');
      setParametersCount('125000000');
      setLicense('mit');
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);

    let modelId = selectedModel;
    try {
      if (isCreatingModel && newModelName.trim()) {
        const createdModel = await apiRequest<{ id: number }>('/api/v1/models/', token, {
          method: 'POST',
          body: JSON.stringify({
            name: newModelName.trim(),
            description: `Model for ${architectureRef}`,
            intended_tasks: ['text_generation', 'reasoning'],
          }),
        });
        modelId = createdModel.id;
      }

      if (!modelId) {
        setError('Please select or create a base model.');
        setBusy(false);
        return;
      }

      if (!selectedTokenizer) {
        setError('Please select a tokenizer.');
        setBusy(false);
        return;
      }

      const created = await apiRequest<RegisteredModelVersion>('/api/v1/model-versions/', token, {
        method: 'POST',
        body: JSON.stringify({
          model: modelId,
          tokenizer: selectedTokenizer,
          revision_no: Number(revisionNo),
          architecture_ref: architectureRef.trim(),
          parameters_count: Number(parametersCount),
          state,
          license_evidence: license.trim(),
        }),
      });

      onSuccess(created);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="connection-dialog"
      aria-labelledby="reg-model-title"
      onCancel={onClose}
      onClose={onClose}
    >
      <div className="dialog-title">
        <h2 id="reg-model-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Layers size={18} aria-hidden="true" /> Register Model Version
        </h2>
        <button className="icon-button" aria-label="Close dialog" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <p className="muted" style={{ margin: '8px 0 16px' }}>
        Pin an immutable model checkpoint version with architecture reference and tokenizer.
      </p>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        <button type="button" onClick={() => applyPreset('llama8b')}>
          <Sparkles size={13} /> Llama 3 8B
        </button>
        <button type="button" onClick={() => applyPreset('mistral7b')}>
          <Sparkles size={13} /> Mistral 7B
        </button>
        <button type="button" onClick={() => applyPreset('anvil125m')}>
          <Sparkles size={13} /> Anvil 125M
        </button>
      </div>

      <form className="api-key" onSubmit={submit} style={{ marginTop: '0' }}>
        {error && <p className="notice error" role="alert">{error}</p>}

        {!isCreatingModel ? (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label htmlFor="mv-model">Base Model</label>
              <button
                type="button"
                className="text-button"
                style={{ minHeight: 'unset', padding: '0', fontSize: '12px' }}
                onClick={() => setIsCreatingModel(true)}
              >
                + New model name
              </button>
            </div>
            <select
              id="mv-model"
              required
              value={selectedModel}
              onChange={(e) => setSelectedModel(Number(e.target.value))}
            >
              <option value="">Select a registered model</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} (#{m.id})
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <label htmlFor="mv-new-model">New Model Name</label>
              <button
                type="button"
                className="text-button"
                style={{ minHeight: 'unset', padding: '0', fontSize: '12px' }}
                onClick={() => setIsCreatingModel(false)}
              >
                Use existing model
              </button>
            </div>
            <input
              id="mv-new-model"
              required
              maxLength={200}
              value={newModelName}
              onChange={(e) => setNewModelName(e.target.value)}
              placeholder="e.g. My-Custom-Llama-Model"
            />
          </div>
        )}

        <label htmlFor="mv-tok">Tokenizer Version</label>
        <select
          id="mv-tok"
          required
          value={selectedTokenizer}
          onChange={(e) => setSelectedTokenizer(Number(e.target.value))}
        >
          <option value="">Select a tokenizer</option>
          {tokenizers.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} · r{t.revision_no} ({t.vocabulary_size} vocab)
            </option>
          ))}
        </select>

        <label htmlFor="mv-arch">Architecture Reference</label>
        <input
          id="mv-arch"
          required
          maxLength={200}
          value={architectureRef}
          onChange={(e) => setArchitectureRef(e.target.value)}
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label htmlFor="mv-params">Parameters Count</label>
            <input
              id="mv-params"
              required
              type="number"
              min="1"
              value={parametersCount}
              onChange={(e) => setParametersCount(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="mv-rev">Revision No</label>
            <input
              id="mv-rev"
              required
              type="number"
              min="1"
              value={revisionNo}
              onChange={(e) => setRevisionNo(e.target.value)}
            />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label htmlFor="mv-state">Registry State</label>
            <select id="mv-state" value={state} onChange={(e) => setState(e.target.value)}>
              <option value="draft">Draft</option>
            </select>
          </div>
          <div>
            <label htmlFor="mv-license">License Evidence</label>
            <input
              id="mv-license"
              required
              value={license}
              onChange={(e) => setLicense(e.target.value)}
            />
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
          <button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            className="primary"
            type="submit"
            disabled={busy || (!selectedModel && !newModelName.trim()) || !selectedTokenizer}
          >
            {busy ? 'Registering…' : 'Register Model Version'}
          </button>
        </div>
      </form>
    </dialog>
  );
}

export function CreateProjectModal({
  token,
  isOpen,
  onClose,
  onSuccess,
}: {
  token: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (p: Project) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [selectedTeam, setSelectedTeam] = useState<string>('');
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      dialogRef.current?.showModal();
      void loadTeams();
    } else {
      dialogRef.current?.close();
    }
  }, [isOpen, token]);

  async function loadTeams() {
    try {
      const page = await apiPage<Team>('/api/v1/teams/', token);
      setTeams(page.results);
      if (page.results.length > 0) {
        setSelectedTeam(page.results[0].id);
      }
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  function handleNameChange(val: string) {
    setName(val);
    if (!slug || slug === name.toLowerCase().replace(/[^a-z0-9]+/g, '-')) {
      setSlug(val.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 64));
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);

    let teamId = selectedTeam;
    try {
      if (!teamId) {
        // Auto-create a default core team if none exists
        const createdTeam = await apiRequest<Team>('/api/v1/teams/', token, {
          method: 'POST',
          body: JSON.stringify({
            name: 'Core Engineering',
            slug: 'core-engineering',
            description: 'Default project owning team',
          }),
        });
        teamId = createdTeam.id;
      }

      const created = await apiRequest<Project>('/api/v1/projects/', token, {
        method: 'POST',
        body: JSON.stringify({
          team: teamId,
          name: name.trim(),
          slug: slug.trim(),
          description: description.trim(),
        }),
      });

      onSuccess(created);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="connection-dialog"
      aria-labelledby="create-project-title"
      onCancel={onClose}
      onClose={onClose}
    >
      <div className="dialog-title">
        <h2 id="create-project-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FolderPlus size={18} aria-hidden="true" /> Create Project
        </h2>
        <button className="icon-button" aria-label="Close dialog" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <p className="muted" style={{ margin: '8px 0 16px' }}>
        Create an explicit project scope for your datasets, experiments, and training runs.
      </p>

      <form className="api-key" onSubmit={submit} style={{ marginTop: '0' }}>
        {error && <p className="notice error" role="alert">{error}</p>}

        {teams.length > 1 && (
          <div>
            <label htmlFor="proj-team">Owning Team</label>
            <select
              id="proj-team"
              required
              value={selectedTeam}
              onChange={(e) => setSelectedTeam(e.target.value)}
            >
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.slug})
                </option>
              ))}
            </select>
          </div>
        )}

        <label htmlFor="proj-name">Project Name</label>
        <input
          id="proj-name"
          required
          maxLength={200}
          value={name}
          onChange={(e) => handleNameChange(e.target.value)}
          placeholder="e.g. Reasoning & Alignment Model"
          autoFocus
        />

        <label htmlFor="proj-slug">Project Slug</label>
        <input
          id="proj-slug"
          required
          maxLength={64}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="e.g. reasoning-alignment"
        />

        <label htmlFor="proj-desc">Description</label>
        <textarea
          id="proj-desc"
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Objective and scope of this model project"
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '16px' }}>
          <button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button className="primary" type="submit" disabled={busy || !name.trim() || !slug.trim()}>
            {busy ? 'Creating…' : 'Create Project'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
