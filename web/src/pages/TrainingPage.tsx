import { useEffect, useState, useCallback, useRef } from 'react';
import { Plus, XCircle, Play, CheckCircle, RefreshCw } from 'lucide-react';
import { ApiRequestError, apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import {
  RegisterTokenizerModal,
  RegisterModelVersionModal,
} from '../components/PrerequisiteModals';
import type { TokenizerVersion, RegisteredModelVersion } from '../api/resources';
import { runHash } from '../api/runs';
import { ChartPanel, ChartEmpty, LineChart, EventTimeline } from '../components/Charts';
import './ml-pages.css';

interface Tokenizer {
  id: number;
  tokenizer_id: string;
  name: string;
  revision_no: number;
  vocabulary_size?: number;
}

interface ModelVersion {
  id: number;
  model_version_id: string;
  model_name: string;
  revision_no: number;
  state: string;
}

interface DatasetRevision {
  id: number;
  revision_id: string;
  dataset_name?: string;
  revision_no: number;
  manifest_digest: string;
  row_count?: number;
  state: string;
}

interface Runner { id: number; manifest_id: string; name: string; enabled: boolean; compatibility: { contract_digest?: string }; }

interface WorkerPool {
  id: number;
  name: string;
  status: string;
  queue_name?: string;
}

interface BudgetPolicy {
  policy_id: string;
  name: string;
  limit_amount: string;
  unit: string;
}

interface Checkpoint {
  checkpoint_id: string;
  step: number;
  is_valid: boolean;
  state_digest: string;
  weights_manifest?: {
    format?: string;
    weights_sha256?: string;
    weights?: { weights_sha256: string };
    tensors?: Record<string, unknown>;
  };
}

interface Run {
  runtime?: { execution_mode?: string };
  execution_evidence?: { level: string; source: string };
  run_id: string;
  recipe_type: string;
  status: string;
  initialization_seed: number;
  current_step: number;
  total_steps: number;
  latest_loss: number | null;
  dataset_revision: number | null;
  dataset_manifest_digest?: string;
  pool: number | null;
  job: string | null;
  checkpoints: Checkpoint[];
  tokenizer_version: number;
  base_model_version: number | null;
  metrics_log?: Array<{ step: number; loss: number }>;
  output_model_version?: number | null;
  created_at: string;
}

interface InferResult {
  run_id: string;
  verification: {
    is_loadable: boolean;
    format: string;
    weights_sha256: string;
    num_tensors: number;
  };
  inference: {
    is_verified: boolean;
    prompt: string;
    completion: string;
    generated_tokens: string[];
  };
}

interface PreflightCheck {
  check: string;
  category: string;
  status: string;
  blocking: boolean;
  reason: string;
  corrective_action?: string | null;
  detail?: Record<string, unknown>;
}

interface PreflightSample {
  sample_id: string | null;
  text_preview: string;
  token_count: number;
  token_ids: number[];
}

interface RuntimeScopeTarget {
  target_id: string;
  label: string;
  category: string;
  status: string;
  reason: string;
  corrective_action?: string | null;
}

interface PreflightReport {
  status: string;
  recipe_type: string;
  execution_mode: string;
  samples: PreflightSample[];
  checks: PreflightCheck[];
  estimate: {
    known: boolean;
    source: string;
    assumptions: string[];
    units: Record<string, string | null>;
    currency: string | null;
    uncertainty: string;
    parameter_count?: number;
    total_tokens?: number;
    estimated_flops?: number;
    estimated_duration_seconds?: number;
    estimated_cost: { known: boolean; value?: number; reason?: string };
  };
  preflight_token: string | null;
  pins: Record<string, unknown> | null;
  requirements: Record<string, unknown>;
  budget: { unit: string; limit: string; committed: string; remaining: string; requested: number } | null;
  sample_count: number | null;
  capacity_note: string;
  expires_in_seconds: number;
  runtime_scope: { targets: RuntimeScopeTarget[]; available: string[]; unavailable: string[] };
  blocking_checks: string[];
}

export function TrainingPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [tokenizers, setTokenizers] = useState<Tokenizer[]>([]);
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [datasetRevisions, setDatasetRevisions] = useState<DatasetRevision[]>([]);
  const [pools, setPools] = useState<WorkerPool[]>([]);
  const [policies, setPolicies] = useState<BudgetPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const [showForm, setShowForm] = useState(false);

  // Form states
  const [mode, setMode] = useState('worker');
  const [recipe, setRecipe] = useState('full_sft');
  const [runners, setRunners] = useState<Runner[]>([]);
  const [runner, setRunner] = useState('');
  const launchRequest = useRef<{ body: string; key: string } | null>(null);
  const [tokenizer, setTokenizer] = useState('');
  const [base, setBase] = useState('');
  const [selectedDataset, setSelectedDataset] = useState('');
  const [selectedPool, setSelectedPool] = useState('');
  const [selectedPolicy, setSelectedPolicy] = useState('');
  const [seed, setSeed] = useState('42');
  const [steps, setSteps] = useState('50');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Run | null>(null);
  const [preflight, setPreflight] = useState<PreflightReport | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const preflightGeneration = useRef(0);
  const preflightPanel = useRef<HTMLDivElement>(null);
  useEffect(() => { if (preflight) preflightPanel.current?.focus(); }, [preflight]);
  useEffect(() => {
    preflightGeneration.current += 1;
    setPreflight(null); setPreflightBusy(false);
  }, [mode, recipe, tokenizer, base, selectedDataset, selectedPool, selectedPolicy, runner, steps, seed, token, refreshKey]);


  // External inference testing state
  const [inferPrompt, setInferPrompt] = useState('ModelAnvil text fine-tuning candidate evaluation');
  const [inferMaxTokens, setInferMaxTokens] = useState('8');
  const [inferring, setInferring] = useState(false);
  const [inferResult, setInferResult] = useState<InferResult | null>(null);
  const [inferError, setInferError] = useState<string | null>(null);
  const inferenceGeneration = useRef(0);

  useEffect(() => {
    inferenceGeneration.current += 1;
    setInferResult(null); setInferError(null); setInferring(false);
  }, [selected?.run_id]);

  const [showTokenizerModal, setShowTokenizerModal] = useState(false);
  const [showModelModal, setShowModelModal] = useState(false);

  const loadDependencies = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [r, t, m, dRes, pRes, bRes, manifests] = await Promise.all([
        apiPage<Run>('/api/v1/training-runs/', token, signal),
        apiPage<Tokenizer>('/api/v1/tokenizers/', token, signal),
        apiPage<ModelVersion>('/api/v1/model-versions/', token, signal),
        apiPage<DatasetRevision>('/api/v1/dataset-revisions/', token, signal).catch(() => ({ results: [] })),
        apiPage<WorkerPool>('/api/v1/worker-pools/', token, signal).catch(() => ({ results: [] })),
        apiPage<BudgetPolicy>('/api/v1/budget-policies/', token, signal),
        apiPage<Runner>('/api/v1/runner-manifests/', token, signal),
      ]);
      if (!signal?.aborted) {
        setRuns(r.results);
        setSelected((current) =>
          current ? r.results.find((run) => run.run_id === current.run_id) || null : null
        );
        setTokenizers(t.results);
        setModels(m.results);
        setDatasetRevisions((dRes.results || []).filter((d) => d.state === 'published'));
        setPools((pRes.results || []).filter((p) => p.status === 'active'));
        setPolicies((bRes.results || []).filter((p) => p.unit === 'training_steps'));
        setRunners(manifests.results.filter((r) => r.enabled && r.compatibility.contract_digest));
      }
    } catch (e) {
      if (!signal?.aborted) {
        setRuns([]);
        setTokenizers([]);
        setModels([]);
        setError(errorMessage(e));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    const c = new AbortController();
    void loadDependencies(c.signal);
    return () => c.abort();
  }, [loadDependencies, refreshKey, retry]);

  const hasActiveRuns = runs.some((run) => ['pending', 'running'].includes(run.status));
  useEffect(() => {
    if (!hasActiveRuns) return;
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void loadDependencies();
    }, 3000);
    return () => clearInterval(timer);
  }, [hasActiveRuns, loadDependencies]);

  function launchPayload(): Record<string, unknown> {
    return {
      execution_mode: mode, recipe_type: recipe,
      ...(tokenizer ? { tokenizer_version: Number(tokenizer) } : {}),
      ...(recipe === 'scratch_pretraining' ? { base_model_version: null } : base ? { base_model_version: Number(base) } : {}),
      initialization_seed: Number(seed), total_steps: Number(steps),
      ...(selectedDataset ? { dataset_revision: Number(selectedDataset) } : {}),
      ...(mode === 'worker' && selectedPool ? { pool: Number(selectedPool) } : {}),
      ...(mode === 'worker' && selectedPolicy ? { budget_policy_id: selectedPolicy } : {}),
      ...(mode === 'worker' && runner ? { runner_manifest: Number(runner) } : {}),
    };
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (mode === 'worker' && !preflight?.preflight_token) return;
    setBusy(true); setError(null); setNotice('');
    try {
      const payload = { ...launchPayload(), ...(mode === 'worker' ? { preflight_token: preflight?.preflight_token } : {}) };
      const body = JSON.stringify(payload);
      if (launchRequest.current?.body !== body) {
        launchRequest.current = { body, key: crypto.randomUUID() };
      }
      const run = await apiRequest<Run>('/api/v1/training-runs/', token, {
        method: 'POST',
        headers: {
          'Idempotency-Key': launchRequest.current.key,
        },
        body,
      });

      launchRequest.current = null;
      setNotice(`Training run dispatched successfully. State: ${run.status}.`);
      setShowForm(false); setPreflight(null);
      setRuns((current) => [run, ...current]);
      setSelected(run);
    } catch (e) {
      setError(errorMessage(e));
      if (e instanceof ApiRequestError && e.status === 400) setPreflight(null);
    } finally {
      setBusy(false);
    }
  }

  async function cancelRun(runId: string) {
    setBusy(true);
    setError(null);
    try {
      const updated = await apiRequest<Run>(`/api/v1/training-runs/${runId}/cancel/`, token, {
        method: 'POST',
      });
      setNotice(updated.status === 'cancelled' ? 'Run cancelled.' : 'Cancellation requested; waiting for the worker to acknowledge it.');
      setRuns((current) => current.map((r) => (r.run_id === runId ? updated : r)));
      setSelected(updated);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function runExternalInference(runId: string) {
    const generation = inferenceGeneration.current;
    setInferring(true);
    setInferError(null);
    setInferResult(null);
    try {
      const res = await apiRequest<InferResult>(`/api/v1/training-runs/${runId}/infer/`, token, {
        method: 'POST',
        body: JSON.stringify({
          prompt: inferPrompt,
          max_tokens: Number(inferMaxTokens),
        }),
      });
      if (generation === inferenceGeneration.current) setInferResult(res);
    } catch (e) {
      if (generation === inferenceGeneration.current) setInferError(errorMessage(e));
    } finally {
      if (generation === inferenceGeneration.current) setInferring(false);
    }
  }

  async function downloadExport(runId: string) {
    setBusy(true); setError(null);
    try {
      const result = await apiRequest<{ bundle: unknown }>(`/api/v1/training-runs/${runId}/export/`, token, { method: 'POST' });
      const url = URL.createObjectURL(new Blob([JSON.stringify(result.bundle)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = `cpu-sft-${runId}.json`;
      link.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  async function runPreflight() {
    const generation = ++preflightGeneration.current;
    setPreflightBusy(true); setError(null); setPreflight(null);
    try {
      const report = await apiRequest<PreflightReport>('/api/v1/training-runs/preflight/', token, {
        method: 'POST', body: JSON.stringify(launchPayload()),
      });
      if (generation === preflightGeneration.current) setPreflight(report);
    } catch (e) {
      if (generation === preflightGeneration.current) setError(errorMessage(e));
    } finally {
      if (generation === preflightGeneration.current) setPreflightBusy(false);
    }
  }

  const focusRun = selected || runs[0];
  const lossPoints = (focusRun?.metrics_log || []).map(m => ({ x: m.step, y: m.loss }));
  const savedCheckpoints = runs.reduce((sum, run) => sum + run.checkpoints.length, 0);

  return (
    <section className="panel ml-page ml-main-panel ml-training">
      <div className="panel-title" style={{ flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 300px' }}>
          <span className="ml-eyebrow">DEVELOP / TRAINING</span><h2>Training studio</h2>
          <p>Fine-tune on a registered CPU or GPU worker using published text and pinned weights. Preview runtime requirements, then monitor committed steps, checkpoints and usage.</p>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
          <button
            type="button"
            disabled={!token.trim()}
            onClick={() => setShowTokenizerModal(true)}
          >
            <Plus size={14} /> Tokenizer
          </button>
          <button
            type="button"
            disabled={!token.trim()}
            onClick={() => setShowModelModal(true)}
          >
            <Plus size={14} /> Model Version
          </button>
          <button
            className="primary"
            disabled={!token.trim() || loading}
            onClick={() => setShowForm((v) => !v)}
          >
            {showForm ? 'Close setup' : 'New training run'}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <div className="ml-stat-strip" aria-label="Loaded training summary">
          <div><span>Training runs</span><strong>{loading ? '—' : runs.length}</strong><small>In the loaded page</small></div>
          <div><span>Active runs</span><strong>{loading ? '—' : runs.filter(r => ['pending', 'running'].includes(r.status)).length}</strong><small>Pending or running</small></div>
          <div><span>Saved checkpoints</span><strong>{loading ? '—' : savedCheckpoints}</strong><small>Recorded checkpoint artifacts</small></div>
          <div><span>Latest selected loss</span><strong>{focusRun?.latest_loss == null ? '—' : focusRun.latest_loss.toFixed(4)}</strong><small>{focusRun ? `Run ${focusRun.run_id.slice(0, 8)}` : 'Select a recorded run'}</small></div>
        </div>
        <ResourceState loading={loading} error={error} onRetry={() => setRetry((v) => v + 1)} />
        {notice && (
          <div className="notice success" role="status">
            {notice}
          </div>
        )}
        {showForm && (
          <form id="training-launch" className="form-grid" onSubmit={create}>
            <label>Execution
              <select value={mode} onChange={(e) => { setMode(e.target.value); setRecipe('full_sft'); setSelectedPool(''); setSelectedPolicy(''); setRunner(''); }}>
                <option value="worker">Worker text fine-tuning</option>
                <option value="simulation">Synthetic training fixture</option>
              </select>
            </label>
            <label>
              Recipe type
              <select value={recipe} onChange={(e) => setRecipe(e.target.value)}>
                <option value="full_sft">Full parameter SFT</option>
                {mode === 'simulation' && <>
                  <option value="lora_adapter">LoRA adapter fixture</option>
                  <option value="continued_pretraining">Continued pretraining fixture</option>
                  <option value="scratch_pretraining">Scratch pretraining fixture</option>
                </>}
              </select>
            </label>

            <label>
              Tokenizer version
              <div style={{ display: 'flex', gap: '8px' }}>
                <select
                  required
                  value={tokenizer}
                  onChange={(e) => setTokenizer(e.target.value)}
                  style={{ flex: 1 }}
                >
                  <option value="">Select a tokenizer</option>
                  {tokenizers.map((t) => (
                    <option key={t.tokenizer_id} value={t.id}>
                      {t.name} · r{t.revision_no} {t.vocabulary_size ? `(vocab: ${t.vocabulary_size})` : ''}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  style={{ whiteSpace: 'nowrap' }}
                  onClick={() => setShowTokenizerModal(true)}
                >
                  + New
                </button>
              </div>
            </label>

            {recipe !== 'scratch_pretraining' && (
              <label>
                Base model version
                <div style={{ display: 'flex', gap: '8px' }}>
                  <select
                    required
                    value={base}
                    onChange={(e) => setBase(e.target.value)}
                    style={{ flex: 1 }}
                  >
                    <option value="">Select a model version</option>
                    {models.map((m) => (
                      <option key={m.model_version_id} value={m.id}>
                        {m.model_name} · r{m.revision_no} · {m.state}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    style={{ whiteSpace: 'nowrap' }}
                    onClick={() => setShowModelModal(true)}
                  >
                    + New
                  </button>
                </div>
              </label>
            )}

            <p className="muted full-width"><a href="#models">Initialize a CPU base in Models</a> or select a GPU base registered on your worker host. Choose its matching tokenizer.</p>
            <label>
              Prepared dataset revision
              <select
                required={mode === 'worker'}
                value={selectedDataset}
                onChange={(e) => setSelectedDataset(e.target.value)}
              >
                <option value="">Select an immutable published revision</option>
                {datasetRevisions.map((d) => (
                  <option key={d.revision_id} value={d.id}>
                    {d.dataset_name || `Dataset r${d.revision_no}`} · {d.row_count || 0} rows · SHA: {d.manifest_digest.slice(0, 10)}…
                  </option>
                ))}
              </select>
            </label>

            <label>
              Worker execution pool
              <select
                disabled={mode === 'simulation'} required={mode === 'worker'}
                value={selectedPool}
                onChange={(e) => setSelectedPool(e.target.value)}
              >
                <option value="">Select a durable worker pool</option>
                {pools.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.queue_name || 'default queue'})
                  </option>
                ))}
              </select>
            </label>

            <label>
              Budget policy & limit
              <select
                disabled={mode === 'simulation'} required={mode === 'worker'}
                value={selectedPolicy}
                onChange={(e) => setSelectedPolicy(e.target.value)}
              >
                <option value="">Select a training step budget</option>
                {policies.map((p) => (
                  <option key={p.policy_id} value={p.policy_id}>
                    {p.name} (limit: {p.limit_amount} {p.unit})
                  </option>
                ))}
              </select>
            </label>

            {mode === 'worker' && <label>Registered training runner
              <select required value={runner} onChange={(e) => setRunner(e.target.value)}>
                <option value="">Select a runtime manifest</option>
                {runners.map((r) => <option key={r.manifest_id} value={r.id}>{r.name}</option>)}
              </select>
            </label>}

            <label>
              Initialization seed
              <input
                disabled={mode === 'worker'}
                required
                type="number"
                min="0"
                max="2147483647"
                step="1"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
              />
            </label>

            <label>
              Total steps
              <input
                required
                type="number"
                min="1"
                max="1000"
                step="1"
                value={steps}
                onChange={(e) => setSteps(e.target.value)}
              />
            </label>

            <div className="actions full-width">
              {mode === 'simulation' && <button
                className="primary"
                disabled={busy || preflightBusy || !tokenizer || (recipe !== 'scratch_pretraining' && !base)}
              >
                {busy ? 'Creating…' : 'Create CPU training fixture'}
              </button>}
              {mode === 'worker' && <button type="button" disabled={busy || preflightBusy} onClick={runPreflight}>
                {preflightBusy ? 'Checking…' : 'Preview preflight'}
              </button>}
              <button type="button" disabled={busy} onClick={() => setShowForm(false)}>
                Cancel
              </button>
            </div>

            <p className="muted full-width">
              {mode === 'worker' ? `Reserves ${steps} training steps. Preflight resolves the selected runtime's data limits, hardware and storage requirements. Monetary cost is unknown.` : 'Synthetic fixtures use no worker or compute budget.'}
            </p>
          </form>
        )}
        {showForm && preflight && (
          <div ref={preflightPanel} tabIndex={-1} className="detail-box" role="region" aria-label="Training preflight" aria-live="polite" style={{ overflowWrap: 'anywhere' }}>
            <h3>
              Preflight:{' '}
              <span className={`state state-${preflight.status === 'approved' ? 'completed' : 'failed'}`}>
                {preflight.status === 'approved' ? 'Ready to launch' : 'Blocked'}
              </span>
            </h3>
            {preflight.blocking_checks.length > 0 && (
              <p className="muted">
                Blocking checks: {preflight.blocking_checks.join(', ')}
              </p>
            )}
            {preflight.samples.length > 0 && (
              <>
                <h4>Encoded training samples · {preflight.sample_count} total, showing up to 5</h4>
                <ul>
                  {preflight.samples.map((sample, index) => (
                    <li key={`${sample.sample_id ?? 'sample'}-${index}`}>
                      <code>{sample.sample_id ?? `sample ${index + 1}`}</code> · {sample.token_count} tokens ·{' '}
                      {sample.text_preview}
                      <div><strong>Token IDs:</strong> <code>{sample.token_ids.join(', ')}</code></div>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <h4>Checks</h4>
            <ul>
              {preflight.checks.map((check) => (
                <li key={check.check}>
                  <strong>{check.check}</strong> · {check.category} · {check.status}: {check.reason}
                  {check.corrective_action ? ` → ${check.corrective_action}` : ''}
                  {check.detail && Object.keys(check.detail).length > 0 && <details><summary>Check details and units</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(check.detail, null, 2)}</pre></details>}
                </li>
              ))}
            </ul>
            <h4>Resolved requirements</h4>
            <p>{String(preflight.requirements.runtime ?? 'Unresolved runtime')} · {String(preflight.requirements.cpu_slots ?? 'unknown')} worker slot · {typeof preflight.requirements.memory_bytes === 'number' ? `${preflight.requirements.memory_bytes / 1048576} MiB host memory` : 'memory unknown'} · {typeof preflight.requirements.storage_bytes === 'number' ? `${(preflight.requirements.storage_bytes / 1048576).toFixed(2)} MiB projected storage` : 'storage unknown'}.</p>
            {preflight.requirements.accelerator != null && <>
              <p>GPU devices required: {String(preflight.requirements.gpu_count ?? 'unknown')} · training precision: {String(preflight.requirements.precision ?? 'unknown')}.</p>
              <details><summary>Resolved GPU device and capacity source</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(preflight.requirements.accelerator, null, 2)}</pre></details>
            </>}
            <p className="muted">{String(preflight.requirements.storage_assumption ?? 'Resolve the input checks to determine storage requirements.')}</p>
            <details><summary>Resolved recipe parameters</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify({ config: preflight.requirements.config, optimizer: preflight.requirements.optimizer }, null, 2)}</pre></details>
            {preflight.budget && <p>Budget: {preflight.budget.requested} {preflight.budget.unit} requested · {preflight.budget.remaining} remaining of {preflight.budget.limit} · {preflight.budget.committed} already committed.</p>}
            <details><summary>Pinned input revisions and digests</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(preflight.pins, null, 2)}</pre></details>
            <p className="muted">{preflight.capacity_note} Preview expires after {preflight.expires_in_seconds / 60} minutes.</p>
            <h4>Estimate</h4>
            <p>Engine time: {preflight.estimate.known ? preflight.estimate.estimated_duration_seconds?.toPrecision(3) : 'unknown — no matching measured pilot'} · units: {preflight.estimate.units.duration}. Total next-token pairs: {preflight.estimate.total_tokens ?? 'unknown'}.</p>
            <p className="muted">{preflight.estimate.source} · uncertainty: {preflight.estimate.uncertainty}</p>
            <ul>
              {preflight.estimate.assumptions.map((assumption, index) => (
                <li key={index}>{assumption}</li>
              ))}
            </ul>
            {preflight.estimate.estimated_cost.known ? (
              <p>
                Estimated cost: {preflight.estimate.estimated_cost.value} {preflight.estimate.currency || ''}
              </p>
            ) : (
              <p>Estimated cost: unknown — {preflight.estimate.estimated_cost.reason}</p>
            )}
            <button form="training-launch" type="submit" className="primary" disabled={busy || preflightBusy || !preflight.preflight_token}>
              {busy ? 'Launching…' : 'Launch fine-tuning'}
            </button>

          </div>
        )}
        <div className="ml-section-heading"><div><span className="ml-eyebrow">EXPERIMENT MONITOR</span><h3>Loss & checkpoint activity</h3><p>Recorded training loss at committed steps, alongside saved checkpoint artifacts.</p></div><label>Inspect run<select aria-label="Training run to visualize" value={focusRun?.run_id || ''} onChange={e => setSelected(runs.find(r => r.run_id === e.target.value) || null)}><option value="" disabled>Select a training run</option>{runs.map(r => <option key={r.run_id} value={r.run_id}>{r.run_id.slice(0, 8)} · {r.recipe_type} · {r.status}</option>)}</select></label></div>
        <div className="visualization-grid">
          <ChartPanel title="Training loss" description={focusRun ? `${focusRun.run_id.slice(0, 8)} · ${focusRun.execution_evidence?.level || 'unknown evidence'}` : 'Loss from committed training measurements.'}><LineChart series={[{ name: 'Training loss', points: lossPoints }]} xLabel="Committed step" yLabel="Loss" /></ChartPanel>
          <ChartPanel title="Checkpoint timeline" description="Saved artifacts from the selected run.">{focusRun ? <><div className="ml-run-progress"><span>Committed steps</span><strong>{focusRun.current_step} / {focusRun.total_steps}</strong><progress value={focusRun.current_step} max={focusRun.total_steps || 1} aria-label="Selected run committed steps" /></div>{focusRun.checkpoints.length ? <EventTimeline events={focusRun.checkpoints.slice(-5).map(c => ({ label: `Checkpoint · step ${c.step}`, detail: c.state_digest.slice(0, 18) + '…', status: c.is_valid ? 'completed' : 'failed' }))} /> : <ChartEmpty message="No checkpoint artifacts have been recorded for this run." />}</> : <ChartEmpty message="Create a training run to inspect committed steps and checkpoints." />}</ChartPanel>
        </div>
        <div className="ml-section-heading"><div><h3>Run history</h3><p>Inspect inputs, download candidates, and open the durable execution record.</p></div></div>
        {!loading && !error && !runs.length && <p className="muted">No training runs yet.</p>}
        {!!runs.length && (
          <div className="table-scroll" tabIndex={0}>
            <table className="resource-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Recipe</th>
                  <th>State</th>
                  <th>Progress</th>
                  <th>Latest loss</th>
                  <th>Checkpoints</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} className={focusRun?.run_id === r.run_id ? 'ml-selected-row' : undefined}>
                    <td>
                      <a href={runHash('training', r.run_id)}>{r.run_id.slice(0, 8)}</a>
                      <button className="text-button" onClick={() => setSelected(r)}>Inline details</button>
                    </td>
                    <td>{r.recipe_type}</td>
                    <td>
                      <span className={`state state-${r.status}`}>{r.status}</span>
                      <small title={r.execution_evidence?.source}> · {r.execution_evidence?.level || "unknown evidence"}</small>
                    </td>
                    <td>
                      <progress
                        value={r.current_step}
                        max={r.total_steps || 1}
                        aria-label={`Run ${r.run_id} progress`}
                      />{' '}
                      {r.current_step} / {r.total_steps}
                    </td>
                    <td>{r.latest_loss === null ? 'Not reported' : r.latest_loss.toFixed(6)}</td>
                    <td>{r.checkpoints.length} saved</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {selected && (
          <div className="detail-box">
            <div className="actions" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3>Run {selected.run_id}</h3>
                <span className={`state state-${selected.status}`}>{selected.status}</span>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                {selected.status === 'completed' && <button disabled={busy} onClick={() => downloadExport(selected.run_id)}>Download candidate</button>}
                {(selected.status === 'running' || selected.status === 'pending') && (
                  <button
                    type="button"
                    style={{ borderColor: 'var(--color-danger, #e53e3e)', color: 'var(--color-danger, #e53e3e)' }}
                    disabled={busy}
                    onClick={() => cancelRun(selected.run_id)}
                  >
                    <XCircle size={14} /> Cancel run
                  </button>
                )}
                <a href={runHash('training', selected.run_id)}>Open run</a>
                <button onClick={() => setSelected(null)}>Close details</button>
              </div>
            </div>

            <p className="muted">
              Tokenizer #{selected.tokenizer_version} {selected.runtime?.execution_mode === 'worker' ? '· Pinned base weights' : `· Seed ${selected.initialization_seed}`} · Base model{' '}
              {selected.base_model_version ? `#${selected.base_model_version}` : 'Random init'}
              {selected.dataset_manifest_digest ? ` · Dataset digest: ${selected.dataset_manifest_digest.slice(0, 16)}…` : ''}
              {selected.job ? ` · Job: ${selected.job.slice(0, 8)}` : ''}
            </p>

            {/* Checkpoints & Safetensors weights */}
            <h4>Saved checkpoints ({selected.checkpoints.length})</h4>
            {selected.checkpoints.length > 5 && <p className="muted">Showing the latest 5 checkpoints.</p>}
            {selected.checkpoints.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {selected.checkpoints.slice(-5).map((c) => (
                  <div key={c.checkpoint_id} style={{ padding: '8px', background: 'var(--color-bg-secondary, #f8f9fa)', borderRadius: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <strong>Step {c.step}</strong>
                      <span className={`state state-${c.is_valid ? 'completed' : 'failed'}`}>
                        <CheckCircle size={12} style={{ display: 'inline', marginRight: '4px' }} />
                        {c.is_valid ? 'Valid Safetensors' : 'Invalid'}
                      </span>
                    </div>
                    <div className="muted" style={{ fontSize: '11px', marginTop: '4px' }}>
                      Digest: <code>{c.state_digest}</code>
                    </div>
                    {(c.weights_manifest?.weights_sha256 || c.weights_manifest?.weights?.weights_sha256) && (
                      <div className="muted" style={{ fontSize: '11px' }}>
                        Weights SHA-256: <code>{c.weights_manifest?.weights_sha256 || c.weights_manifest?.weights?.weights_sha256}</code>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No checkpoints recorded yet.</p>
            )}

            {/* External Inference Candidate Testing */}
            <div style={{ marginTop: '20px', borderTop: '1px solid var(--color-border, #e2e8f0)', paddingTop: '16px' }}>
              <h4>External Candidate Model Inference</h4>
              <p className="muted" style={{ fontSize: '13px' }}>
                Load the exported weights and decode text in the server CPU runtime. GPU inference uses the independent consumer on the worker host.
              </p>
              <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                <input
                  type="text"
                  aria-label="Inference test prompt"
                  placeholder="Enter test prompt…"
                  value={inferPrompt}
                  onChange={(e) => setInferPrompt(e.target.value)}
                  style={{ flex: 1 }}
                />
                <input
                  type="number"
                  min="1"
                  max="32"
                  aria-label="Maximum generated tokens"
                  value={inferMaxTokens}
                  onChange={(e) => setInferMaxTokens(e.target.value)}
                  style={{ width: '80px' }}
                />
                <button
                  type="button"
                  className="primary"
                  disabled={inferring || !inferPrompt.trim() || selected.status !== 'completed'}
                  onClick={() => runExternalInference(selected.run_id)}
                >
                  {inferring ? <RefreshCw size={14} className="spin" /> : <Play size={14} />} Run inference
                </button>
              </div>

              {inferError && (
                <div className="notice danger" style={{ marginTop: '8px' }}>
                  {inferError}
                </div>
              )}

              {inferResult && (
                <div style={{ marginTop: '12px', padding: '12px', background: 'var(--color-bg-secondary, #f8f9fa)', borderRadius: '6px' }}>
                  <div style={{ display: 'flex', gap: '16px', marginBottom: '8px' }}>
                    <span className="state state-completed">
                      Format: {inferResult.verification.format}
                    </span>
                    <span className="state state-completed">
                      CPU load and inference: {inferResult.verification.is_loadable ? 'Passed' : 'Failed'} · Independent runtime unverified
                    </span>
                    <span className="muted" style={{ fontSize: '12px' }}>
                      Tensors: {inferResult.verification.num_tensors}
                    </span>
                  </div>
                  <div style={{ fontSize: '12px', marginBottom: '6px' }}>
                    <strong>Candidate Weights SHA-256:</strong>{' '}
                    <code>{inferResult.verification.weights_sha256}</code>
                  </div>
                  <div style={{ padding: '8px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '4px', fontFamily: 'monospace', fontSize: '13px' }}>
                    <strong>Prompt:</strong> {inferResult.inference.prompt}
                    <br />
                    <strong>Completion:</strong>{' '}
                    <span style={{ color: 'var(--primary-text)' }}>
                      {inferResult.inference.completion}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <RegisterTokenizerModal
        token={token}
        isOpen={showTokenizerModal}
        onClose={() => setShowTokenizerModal(false)}
        onSuccess={(tok: TokenizerVersion) => {
          setTokenizers((current) => [...current, tok]);
          setTokenizer(String(tok.id));
        }}
      />

      <RegisterModelVersionModal
        token={token}
        isOpen={showModelModal}
        onClose={() => setShowModelModal(false)}
        onSuccess={(mv: RegisteredModelVersion) => {
          setModels((current) => [...current, mv]);
          setBase(String(mv.id));
        }}
      />
    </section>
  );
}
