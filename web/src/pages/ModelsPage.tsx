import { useCallback, useEffect, useState } from 'react';
import { Button, Dialog, Field, Notice, Section } from '../components/ui';
import { apiPage, errorMessage, nextPagePath } from '../api/client';
import { allResources } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import { EmptyState } from '../components/Feedback';
import { AddModelForm } from '../components/models/AddModelForm';
import { ModelList } from '../components/models/ModelList';
import { ModelInspector } from '../components/models/ModelInspector';
import { ModelImports } from '../components/models/ModelImports';
import { ManualRegistration } from '../components/models/ManualRegistration';
import { useModelImports } from '../components/models/useModelImports';
import { RegisterTokenizerModal, RegisterModelVersionModal } from '../components/PrerequisiteModals';
import type { Model, ModelVersion } from '../api/models';
import './models.css';

const endpoint = '/api/v1/models/';

export function ModelsPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const [models, setModels] = useState<Model[]>([]);
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState('');
  const [reloads, setReloads] = useState(0);
  const [showTokenizerModal, setShowTokenizerModal] = useState(false);
  const [showModelModal, setShowModelModal] = useState(false);
  const imports = useModelImports(token, refreshKey + reloads);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null);
    const [page, list] = await Promise.allSettled([apiPage<Model>(endpoint, token, signal), allResources<ModelVersion>('/api/v1/model-versions/', token, signal)]);
    if (signal?.aborted) return;
    if (page.status === 'fulfilled') { setModels(page.value.results); setNext(page.value.next || null); }
    else { setModels([]); setError(errorMessage(page.reason)); }
    setVersions(list.status === 'fulfilled' ? list.value : []);
    setLoading(false);
  }, [token]);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load, refreshKey]);

  function registered(message: string) { setNotice(message); setAdding(false); setReloads(count => count + 1); void load(); }
  async function more() {
    if (!next) return;
    setLoading(true); setError(null);
    try {
      const page = await apiPage<Model>(nextPagePath(next, endpoint), token);
      setModels(current => [...current, ...page.results.filter(model => !current.some(item => item.model_id === model.model_id))]);
      setNext(page.next || null);
    } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); }
  }

  const needle = query.trim().toLowerCase();
  const filtered = models.filter(model => !needle || `${model.name} ${model.description} ${model.intended_tasks.join(' ')}`.toLowerCase().includes(needle));
  const current = models.find(model => model.model_id === selected) || null;
  const ready = !!token.trim();
  const count = loading || error ? null : filtered.length === models.length ? `${models.length} ${models.length === 1 ? 'model' : 'models'}` : `${filtered.length} of ${models.length} models`;

  return <div className="models-page">
    <Section title="Registered models" actions={<>
      <Field className="models-search" aria-label="Search models" placeholder="Search models" value={query} onChange={event => setQuery(event.target.value)} />
      <Button type="button" variant="primary" disabled={!ready} onClick={() => setAdding(true)}>Add model</Button>
    </>}>
      {notice && <Notice tone="success" role="status">{notice}</Notice>}
      <ResourceState loading={loading && !models.length} error={error} onRetry={() => void load()} />
      <div className={current ? 'models-split models-split-open' : 'models-split'}>
        <div className="models-main">
          {count && <p className="muted models-count">{count}</p>}
          {!loading && !error && !filtered.length && <EmptyState title={models.length ? 'No models match your search.' : 'No models yet'} description={models.length ? undefined : 'Add a model from Hugging Face or local files to start.'} />}
          <ModelList models={filtered} versions={versions} selected={selected} onSelect={id => setSelected(value => value === id ? null : id)} />
          {next && <Button type="button" disabled={loading} onClick={() => void more()}>Load more models</Button>}
        </div>
        {current && <ModelInspector key={current.model_id} model={current} versions={versions} onClose={() => setSelected(null)} />}
      </div>
    </Section>
    <ModelImports imports={imports.imports} busy={imports.busy} error={imports.error} onChange={(item, action) => void imports.change(item, action)} />
    <ManualRegistration token={token} versions={versions} onRegistered={registered} onRegisterTokenizer={() => setShowTokenizerModal(true)} onRegisterModelVersion={() => setShowModelModal(true)} />
    <Dialog title="Add a model" description="Search Hugging Face or import local model files into this project." open={adding} onClose={() => setAdding(false)} size="lg">
      {adding && <AddModelForm token={token} onImported={registered} />}
    </Dialog>
    <RegisterTokenizerModal token={token} isOpen={showTokenizerModal} onClose={() => setShowTokenizerModal(false)} onSuccess={() => registered('Tokenizer registered.')} />
    <RegisterModelVersionModal token={token} isOpen={showModelModal} onClose={() => setShowModelModal(false)} onSuccess={() => registered('Model version registered.')} />
  </div>;
}
