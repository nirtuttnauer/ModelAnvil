import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field, MultilineField, Notice } from '../components/ui';
import { MetricComparison } from '../components/MetricComparison';
import { useCallback, useEffect, useState } from 'react';
import { BookOpen, Layers, Box, ArrowUpRight } from 'lucide-react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ModelCatalog } from '../components/ModelCatalog';
import { ModelCapabilities } from '../components/ModelCapabilities';
import { BarChart, ChartPanel, MetricsChart } from '../components/Charts';
import { runHash } from '../api/runs';
import './ml-pages.css';
import {
  RegisterTokenizerModal,
  RegisterModelVersionModal,
} from '../components/PrerequisiteModals';

interface Model {
  id?: number;
  model_id: string;
  name: string;
  description: string;
  intended_tasks: string[];
}

interface Metric {
  key: string;
  slice_name: string;
  value: number;
  sample_count: number;
  uncertainty_interval: Record<string, unknown>;
}

interface Evaluation {
  execution_evidence?: { level: string; source: string };
  run_id: string;
  candidate_model_version: number;
  status: string;
  metrics: Metric[];
  baseline_metrics?: Metric[];
  completed_at: string | null;
}

const endpoint = '/api/v1/models/';

export function ModelsPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const [models, setModels] = useState<Model[]>([]);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selectedEvaluation, setSelectedEvaluation] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [showCpuForm, setShowCpuForm] = useState(false);
  const [cpuName, setCpuName] = useState('');
  const [cpuSeed, setCpuSeed] = useState('42');
  const [cpuProfile, setCpuProfile] = useState('cpu-character');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tasks, setTasks] = useState('text_generation, reasoning');
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState('');

  const [showTokenizerModal, setShowTokenizerModal] = useState(false);
  const [showModelModal, setShowModelModal] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError(null);
      setEvalError(null);
      const results = await Promise.allSettled([
        apiPage<Model>(endpoint, token, signal),
        apiPage<Evaluation>('/api/v1/evaluation-runs/', token, signal),
      ]);
      if (signal?.aborted) return;
      if (results[0].status === 'fulfilled') {
        setModels(results[0].value.results);
        setNext(results[0].value.next || null);
      } else {
        setModels([]);
        setError(errorMessage(results[0].reason));
      }
      if (results[1].status === 'fulfilled') {
        setEvaluations(results[1].value.results.filter((r) => r.status === 'completed'));
      } else {
        setEvaluations([]);
        setEvalError(errorMessage(results[1].reason));
      }
      setLoading(false);
    },
    [token]
  );

  useEffect(() => {
    const c = new AbortController();
    void load(c.signal);
    return () => c.abort();
  }, [load, refreshKey]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiRequest(endpoint, token, {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim(),
          intended_tasks: [...new Set(tasks.split(',').map((t) => t.trim()).filter(Boolean))],
        }),
      });
      setNotice(`Model “${name.trim()}” registered.`);
      setShowForm(false);
      setName('');
      setDescription('');
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function initializeCpu(e: React.FormEvent) {
    e.preventDefault(); setSubmitting(true); setError(null);
    try {
      const initialized = await apiRequest<{ execution_evidence?: { level: string } }>('/api/v1/model-versions/initialize-cpu/', token, { method: 'POST', body: JSON.stringify({ name: cpuName.trim(), seed: Number(cpuSeed), profile: cpuProfile }) });
      setNotice(initialized.execution_evidence?.level === 'fixture' ? `Demo CPU base “${cpuName.trim()}” registered in this Storybook session.` : `Untrained CPU base “${cpuName.trim()}” initialized with real pinned weights and its compatible tokenizer.`);
      setShowCpuForm(false); setCpuName(''); await load();
    } catch (e) { setError(errorMessage(e)); } finally { setSubmitting(false); }
  }

  async function more() {
    if (!next) return;
    setLoading(true);
    setError(null);
    try {
      const p = await apiPage<Model>(nextPagePath(next, endpoint), token);
      setModels((current) => [
        ...current,
        ...p.results.filter((m) => !current.some((x) => x.model_id === m.model_id)),
      ]);
      setNext(p.next || null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }

  const filtered = models.filter((m) =>
    `${m.name} ${m.description} ${m.intended_tasks.join(' ')}`
      .toLowerCase()
      .includes(query.toLowerCase())
  );

  const evaluatedRun = evaluations.find(r => r.run_id === selectedEvaluation) || evaluations[0];
  const taskCounts = [...new Set(models.flatMap(m => m.intended_tasks))].map(task => ({ label: task, value: models.filter(m => m.intended_tasks.includes(task)).length, color: 0 }));

  return (
    <div className="resource-view ml-page ml-models">
      <details className="workspace-details"><summary>Add or import a model</summary><ModelCatalog token={token} onImported={() => void load()} /></details>
      <details className="workspace-details"><summary>Model runtime compatibility</summary><ModelCapabilities token={token} refreshKey={refreshKey + models.length} /></details>
      <Card className="panel ml-main-panel">
        <div className="panel-title">
          <div>
            <span className="ml-eyebrow">DEVELOP / MODEL REGISTRY</span><h2>Models & checkpoints</h2>
            <p>Registered models, checkpoints, and their intended tasks.</p>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-8)' }}>
            <Button
              type="button"
              disabled={!token.trim()}
              onClick={() => setShowTokenizerModal(true)}
            >
              <BookOpen size={14} /> Tokenizer
            </Button>
            <Button
              type="button"
              disabled={!token.trim()}
              onClick={() => setShowModelModal(true)}
            >
              <Layers size={14} /> Version Checkpoint
            </Button>
            <Button type="button" disabled={!token.trim() || submitting} onClick={() => { setShowCpuForm(v => !v); setShowForm(false); }}>Initialize CPU base</Button>
            <Button
              className="primary"
              disabled={!token.trim()}
              onClick={() => setShowForm((v) => !v)}
            >
              {showForm ? 'Close registration' : 'Register Base Model'}
            </Button>
          </div>
        </div>
        <div className="panel-body">
          <div className="ml-stat-strip" aria-label="Loaded model registry summary">
            <div><span>Registered models</span><strong>{loading ? '—' : models.length}</strong><small>In the loaded registry page</small></div>
            <div><span>Intended tasks</span><strong>{loading ? '—' : taskCounts.length}</strong><small>Declared in model metadata</small></div>
            <div><span>Completed evaluations</span><strong>{loading || evalError ? '—' : evaluations.length}</strong><small>In the loaded evaluation page</small></div>
            <div><span>Evidence scope</span><strong className="ml-stat-text">Recorded</strong><small>Qualification requires independent evidence</small></div>
          </div>
          {notice && (
            <Notice tone="success" className="notice success" role="status">
              {notice}
            </Notice>
          )}
          <Notice as="p" className="notice">Registry state is a recorded label. Metadata registration and fixture results do not establish production model qualification.</Notice><ResourceState loading={loading} error={error} onRetry={() => void load()} />
          {showCpuForm && <form className="form-grid" onSubmit={initializeCpu}><label>CPU base model name<Field required maxLength={180} value={cpuName} onChange={e => setCpuName(e.target.value)} autoFocus /></label><label>CPU runtime profile<select value={cpuProfile} onChange={e => setCpuProfile(e.target.value)}><option value="cpu-character">CPU character SFT</option><option value="cpu-transformer">Small CPU transformer SFT</option></select></label><label>Initialization seed<Field required type="number" min="0" max="2147483647" value={cpuSeed} onChange={e => setCpuSeed(e.target.value)} /></label><p className="muted full-width">Creates real untrained weights with the matching character or byte tokenizer for the selected bounded CPU runtime. Fine-tune this base on a published text revision before evaluating a candidate.</p><div className="actions full-width"><Button className="primary" disabled={submitting || !cpuName.trim()}>{submitting ? 'Initializing…' : 'Create pinned CPU base'}</Button><Button type="button" disabled={submitting} onClick={() => setShowCpuForm(false)}>Cancel</Button></div></form>}
          {showForm && (
            <form className="form-grid" onSubmit={create}>
              <label>
                Model Name
                <Field
                  required
                  maxLength={200}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                />
              </label>
              <label>
                Intended Tasks (comma-separated)
                <Field value={tasks} onChange={(e) => setTasks(e.target.value)} />
              </label>
              <label className="full-width">
                Description
                <MultilineField
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
              <div className="actions full-width">
                <Button className="primary" disabled={submitting || !name.trim()}>
                  {submitting ? 'Registering…' : 'Confirm Registration'}
                </Button>
                <Button type="button" disabled={submitting} onClick={() => setShowForm(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          )}
      <div className="ml-section-heading"><div><span className="ml-eyebrow">RECORDED PERFORMANCE</span><h3>Evaluation evidence</h3><p>Explore one recorded run at a time. Different suites are not treated as comparable.</p></div><label>Evaluation run<select aria-label="Evaluation run to visualize" value={evaluatedRun?.run_id || ''} onChange={e => setSelectedEvaluation(e.target.value)}><option value="" disabled>Select a completed evaluation</option>{evaluations.map((r, index) => <option key={r.run_id} value={r.run_id}>Evaluation {index + 1} · {r.status}</option>)}</select></label></div>
      <ResourceState error={evalError} />
      <div className="visualization-grid">
        <MetricsChart key={evaluatedRun?.run_id || 'none'} metrics={evaluatedRun?.metrics || []} />
        <ChartPanel title="Task coverage" description="Models tagged for each task in the loaded registry."><BarChart data={taskCounts} unit="Registered models" emptyMessage="Register model metadata to inspect declared task coverage." /></ChartPanel>
      </div>
          <div className="ml-section-heading"><div><h3>Model registry</h3><p>Base models and their declared tasks.</p></div></div>
          <div className="toolbar">
            <Field
              aria-label="Search models"
              placeholder="Search by model name, description, or task"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <small className="muted">
              {filtered.length} of {models.length} loaded models
            </small>
          </div>
          {!loading && !error && !filtered.length && (
            <p className="muted">
              {models.length ? 'No models match your search.' : 'No registered models yet.'}
            </p>
          )}
          <div className="model-grid">
            {filtered.map((m) => (
              <article className="model-card" key={m.model_id}>
                <div className="ml-model-heading"><span className="ml-model-icon"><Box size={19} aria-hidden="true" /></span><h3>{m.name}</h3></div>
                <p className="muted">{m.description || 'No description provided.'}</p>
                <div className="actions">
                  {m.intended_tasks.map((t) => (
                    <Badge className="badge" key={t}>
                      {t}
                    </Badge>
                  ))}
                </div>
                <Identifier value={m.model_id} label="Model ID" />
              </article>
            ))}
          </div>
          {next && (
            <Button disabled={loading} onClick={() => void more()}>
              Load more models
            </Button>
          )}
        </div>
      </Card>
      {evaluatedRun && <Card className="panel"><div className="panel-title"><div><h3>Selected evaluation record</h3><p>Recorded evaluation · {evaluatedRun.execution_evidence?.level || 'unknown evidence'} <Identifier value={evaluatedRun.run_id} label="Evaluation run ID" /><Identifier value={evaluatedRun.candidate_model_version} label="Model version record ID" /></p></div><a className="ml-inline-link" href={runHash('evaluation', evaluatedRun.run_id)}>Open evaluation <ArrowUpRight size={15} aria-hidden="true" /></a></div><div className="panel-body"><p className="muted" title={evaluatedRun.execution_evidence?.source}>Recorded uncertainty is shown only when reported by the source. No latency or lineage measurements are inferred from metadata.</p><MetricComparison metrics={evaluatedRun.metrics} baseline={evaluatedRun.baseline_metrics} /></div></Card>}

      <RegisterTokenizerModal
        token={token}
        isOpen={showTokenizerModal}
        onClose={() => setShowTokenizerModal(false)}
        onSuccess={() => {
          setNotice('Tokenizer registered successfully.');
          void load();
        }}
      />

      <RegisterModelVersionModal
        token={token}
        isOpen={showModelModal}
        onClose={() => setShowModelModal(false)}
        onSuccess={() => {
          setNotice('Model version registered successfully.');
          void load();
        }}
      />
    </div>
  );
}
