import { useCallback, useEffect, useState } from 'react';
import { BookOpen, Layers, Box, ArrowUpRight } from 'lucide-react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { ResourceState } from '../components/ResourceState';
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
      const initialized = await apiRequest<{ execution_evidence?: { level: string } }>('/api/v1/model-versions/initialize-cpu/', token, { method: 'POST', body: JSON.stringify({ name: cpuName.trim(), seed: Number(cpuSeed) }) });
      setNotice(initialized.execution_evidence?.level === 'fixture' ? `Demo CPU base “${cpuName.trim()}” registered in this Storybook session.` : `Untrained CPU base “${cpuName.trim()}” initialized with real pinned weights and a compatible character tokenizer.`);
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
      <section className="panel ml-main-panel">
        <div className="panel-title">
          <div>
            <span className="ml-eyebrow">DEVELOP / MODEL REGISTRY</span><h2>Models & checkpoints</h2>
            <p>Registered models, checkpoints, and their intended tasks.</p>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button
              type="button"
              disabled={!token.trim()}
              onClick={() => setShowTokenizerModal(true)}
            >
              <BookOpen size={14} /> Tokenizer
            </button>
            <button
              type="button"
              disabled={!token.trim()}
              onClick={() => setShowModelModal(true)}
            >
              <Layers size={14} /> Version Checkpoint
            </button>
            <button type="button" disabled={!token.trim() || submitting} onClick={() => { setShowCpuForm(v => !v); setShowForm(false); }}>Initialize CPU base</button>
            <button
              className="primary"
              disabled={!token.trim()}
              onClick={() => setShowForm((v) => !v)}
            >
              {showForm ? 'Close registration' : 'Register Base Model'}
            </button>
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
            <div className="notice success" role="status">
              {notice}
            </div>
          )}
          <p className="notice">Registry state is a recorded label. Metadata registration and fixture results do not establish production model qualification.</p><ResourceState loading={loading} error={error} onRetry={() => void load()} />
          {showCpuForm && <form className="form-grid" onSubmit={initializeCpu}><label>CPU base model name<input required maxLength={180} value={cpuName} onChange={e => setCpuName(e.target.value)} autoFocus /></label><label>Initialization seed<input required type="number" min="0" max="2147483647" value={cpuSeed} onChange={e => setCpuSeed(e.target.value)} /></label><p className="muted full-width">Creates real untrained character model weights and an ASCII tokenizer for the bounded CPU runtime. Fine-tune this base on a published text revision before evaluating a candidate.</p><div className="actions full-width"><button className="primary" disabled={submitting || !cpuName.trim()}>{submitting ? 'Initializing…' : 'Create pinned CPU base'}</button><button type="button" disabled={submitting} onClick={() => setShowCpuForm(false)}>Cancel</button></div></form>}
          {showForm && (
            <form className="form-grid" onSubmit={create}>
              <label>
                Model Name
                <input
                  required
                  maxLength={200}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                />
              </label>
              <label>
                Intended Tasks (comma-separated)
                <input value={tasks} onChange={(e) => setTasks(e.target.value)} />
              </label>
              <label className="full-width">
                Description
                <textarea
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </label>
              <div className="actions full-width">
                <button className="primary" disabled={submitting || !name.trim()}>
                  {submitting ? 'Registering…' : 'Confirm Registration'}
                </button>
                <button type="button" disabled={submitting} onClick={() => setShowForm(false)}>
                  Cancel
                </button>
              </div>
            </form>
          )}
      <div className="ml-section-heading"><div><span className="ml-eyebrow">RECORDED PERFORMANCE</span><h3>Evaluation evidence</h3><p>Explore one recorded run at a time. Different suites are not treated as comparable.</p></div><label>Evaluation run<select aria-label="Evaluation run to visualize" value={evaluatedRun?.run_id || ''} onChange={e => setSelectedEvaluation(e.target.value)}><option value="" disabled>Select a completed evaluation</option>{evaluations.map(r => <option key={r.run_id} value={r.run_id}>#{r.candidate_model_version} · {r.run_id.slice(0, 8)}</option>)}</select></label></div>
      <ResourceState error={evalError} />
      <div className="visualization-grid">
        <MetricsChart key={evaluatedRun?.run_id || 'none'} metrics={evaluatedRun?.metrics || []} />
        <ChartPanel title="Task coverage" description="Models tagged for each task in the loaded registry."><BarChart data={taskCounts} unit="Registered models" emptyMessage="Register model metadata to inspect declared task coverage." /></ChartPanel>
      </div>
          <div className="ml-section-heading"><div><h3>Model registry</h3><p>Base models and their declared tasks.</p></div></div>
          <div className="toolbar">
            <input
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
                    <span className="badge" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
                <small className="id-text">{m.model_id}</small>
              </article>
            ))}
          </div>
          {next && (
            <button disabled={loading} onClick={() => void more()}>
              Load more models
            </button>
          )}
        </div>
      </section>
      {evaluatedRun && <section className="panel"><div className="panel-title"><div><h3>Selected evaluation record</h3><p>Model version #{evaluatedRun.candidate_model_version} · {evaluatedRun.run_id.slice(0, 8)} · {evaluatedRun.execution_evidence?.level || 'unknown evidence'}</p></div><a className="ml-inline-link" href={runHash('evaluation', evaluatedRun.run_id)}>Open evaluation <ArrowUpRight size={15} aria-hidden="true" /></a></div><div className="panel-body"><p className="muted" title={evaluatedRun.execution_evidence?.source}>Recorded uncertainty is shown only when reported by the source. No latency or lineage measurements are inferred from metadata.</p>{evaluatedRun.metrics.length > 0 && <div className="table-scroll" tabIndex={0}><table className="resource-table"><thead><tr><th>Metric / slice</th><th>Value</th><th>Samples</th><th>Recorded uncertainty</th></tr></thead><tbody>{evaluatedRun.metrics.map((m, i) => <tr key={i}><td>{m.key} / {m.slice_name}</td><td>{m.value.toLocaleString(undefined, { maximumFractionDigits: 6 })}</td><td>{m.sample_count}</td><td>{m.uncertainty_interval && Object.keys(m.uncertainty_interval).length ? JSON.stringify(m.uncertainty_interval) : 'Not reported'}</td></tr>)}</tbody></table></div>}</div></section>}

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
