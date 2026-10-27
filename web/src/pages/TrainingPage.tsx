import { EvidenceLabel } from '../components/EvidenceLabel';
import { ContinuedCorpusBuilder } from '../components/ContinuedCorpusBuilder';
import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field, Notice, RecordTable, Tab } from '../components/ui';
import { GuidedFineTune } from '../components/GuidedFineTune';
import { GuidedDecision } from '../components/GuidedDecision';
import { ModelHardwareFit } from '../components/ModelHardwareFit';
import { TrainingRunProgress } from '../components/TrainingRunProgress';
import { ModelExport } from '../components/ModelExport';
import { PreparedDatasetPreview } from '../components/TrainingDatasetPreview';
import type { ModelExportOption } from '../api/model-export';
import { trainingLossSeries } from '../api/training-progress';
import { useHardwareInventory } from '../components/useHardwareInventory';
import { workerHardware } from '../api/model-hardware';
import { guidedPlan, readGuidedValue, type GuidedInputs, type GuidedRevision } from '../api/guided-training';
import { trainingDefaults, legacyGuidedDefaults, preparedTrainingFields, migrateGuidedTraining, trainingStepCount, trainingLaunchPayload, trainingTab, latestTrainingRun, type TrainingTab } from '../api/training-workspace';
import { PreflightChecklist, type PreflightReport } from '../components/PreflightChecklist';
import { ResourcePicker } from '../components/ResourcePicker';
import { resourceHash } from '../api/resource-routes';
import { comparisonBlockers } from '../api/run-comparison';
import { DataInspector } from '../components/DataInspector';
import { allResources } from '../api/resources';
import { useResourceHandoff } from '../components/ResourceHandoff';
import { useDraft, DraftStatus } from '../components/Draft';
import { useEffect, useState, useCallback, useRef } from 'react';
import { XCircle, Play, CheckCircle, RefreshCw } from 'lucide-react';
import { ApiRequestError, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { PrerequisiteActions } from '../components/PrerequisiteActions';
import type { ModelCapabilities } from '../api/resources';
import { runHash } from '../api/runs';
import { ChartPanel, ChartEmpty, LineChart, EventTimeline } from '../components/Charts';
import './ml-pages.css';
import './training-workspace.css';

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
  architecture_ref?: string;
  revision_no: number;
  state: string;
  capabilities?: ModelCapabilities;
}

interface DatasetRevision {
  id: number;
  revision_id: string;
  dataset_name?: string;
  revision_no: number;
  manifest_digest: string;
  row_count?: number;
  state: string;
  metadata?: GuidedRevision['metadata'] & { preparation_kind?: string };
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
  enabled: boolean;
  currency: string;
  allowance?: { remaining_amount: string };
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
  runtime?: { execution_mode?: string; setup_check?: boolean; purpose?: string; pins?: { runtime?: string }; independent_evaluation?: { status: string; passed: boolean; reason?: string; report?: Record<string, unknown> } };
  execution_evidence?: { level: string; source: string };
  run_id: string;
  recipe_type: string;
  status: string;
  initialization_seed: number;
  current_step: number;
  progress_step?: number;
  total_steps: number;
  latest_loss: number | null;
  dataset_revision: number | null;
  dataset_manifest_digest?: string;
  pool: number | null;
  job: string | null;
  checkpoints: Checkpoint[];
  tokenizer_version: number;
  base_model_version: number | null;
  metrics_log?: Array<{ step: number; loss: number; measured_at?: string; gradient_norm?: number; tokens_per_second?: number; prediction_frames_per_second?: number; validation_prediction_frames?: number;
    engine_wall_seconds?: number; updates_since_checkpoint?: number;
    gpu_allocated_bytes?: number; peak_allocated_bytes?: number | null; gpu_utilization_percent?: number | null; trainable_parameters?: number; total_parameters?: number; validation_loss?: number; validation_prediction_tokens?: number }>;
  output_model_version?: number | null;
  output_model_version_uuid?: string | null;
  export_options?: ModelExportOption[];
  quality_summary?: { selected_step: number; baseline_loss: number | null; validation_loss: number | null; validation_examples: number } | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
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

export function TrainingPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const hardware = useHardwareInventory(token, refreshKey);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runsRefreshedAt, setRunsRefreshedAt] = useState(0);
  const [progressError, setProgressError] = useState<string | null>(null);
  const [tokenizers, setTokenizers] = useState<Tokenizer[]>([]);
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [datasetRevisions, setDatasetRevisions] = useState<DatasetRevision[]>([]);
  const [pools, setPools] = useState<WorkerPool[]>([]);
  const [policies, setPolicies] = useState<BudgetPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [retry, setRetry] = useState(0);
  const draft = useDraft('training', trainingDefaults);
  const legacy = useDraft('guided-fine-tune', legacyGuidedDefaults);
  const [advanced, setAdvanced] = draft.field('showForm');
  const [preset, setPreset] = draft.field('preset');
  const [revisionJson, setRevisionJson] = draft.field('revisionJson');
  const [modelName, setModelName] = draft.field('modelName');
  const [currentRunId, setCurrentRunId] = draft.field('currentRunId');
  const [project] = draft.field('project');
  const [launchKey, setLaunchKey] = draft.field('launchKey');
  const [launchInputs, setLaunchInputs] = draft.field('launchInputs');
  const [setupBusy, setSetupBusy] = useState(false);
  const [routeHash, setRouteHash] = useState(window.location.hash);
  const tab = trainingTab(routeHash);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const tabPanel = useRef<HTMLDivElement>(null);
  function navigateTab(next: TrainingTab, runId?: string) {
    const query = new URLSearchParams(window.location.hash.split('?')[1]);
    query.set('tab', next);
    query.delete('run');
    query.delete('model_version');
    query.delete('dataset_revision');
    if (runId) query.set('run', runId);
    window.location.hash = `training?${query}`;
    setRouteHash(window.location.hash);
  }
  useEffect(() => {
    function syncTab() { setRouteHash(window.location.hash); }
    window.addEventListener('hashchange', syncTab);
    return () => window.removeEventListener('hashchange', syncTab);
  }, []);
  // Consume the previous guided draft once; both modes now edit the training draft.
  useEffect(() => {
    if (!['saved', 'restored'].includes(legacy.status)) return;
    if (draft.status === 'empty') {
      const values = Object.fromEntries(Object.keys(legacyGuidedDefaults).map(key => [key, legacy.field(key as keyof typeof legacyGuidedDefaults)[0]])) as typeof legacyGuidedDefaults;
      const migrated = migrateGuidedTraining(values);
      for (const key of Object.keys(trainingDefaults) as Array<keyof typeof trainingDefaults>) draft.field(key)[1](migrated[key]);
      if (migrated.currentRunId) navigateTab('current-run', migrated.currentRunId);
    }
    legacy.discard();
  }, [legacy.status, draft.status]);

  // Form states
  const [learningRate, setLearningRate] = draft.field('learningRate'), [validationInterval, setValidationInterval] = draft.field('validationInterval');
  const [pilotSteps, setPilotSteps] = draft.field('pilotSteps'), [comparisonIds, setComparisonIds] = draft.field('comparisonIds');
  const [pilotReport, setPilotReport] = useState<PreflightReport | null>(null);
  const [pilotBusy, setPilotBusy] = useState(false);
  const [mode, setMode] = draft.field('mode');
  const [demoAcknowledged, setDemoAcknowledged] = useState(false);
  const [recipe, setRecipe] = draft.field('recipe');
  const [runners, setRunners] = useState<Runner[]>([]);
  const [runner, setRunner] = draft.field('runner');
  const [tokenizer, setTokenizer] = draft.field('tokenizer');
  const [base, setBase] = draft.field('base');
  const [selectedDataset, setSelectedDataset] = draft.field('selectedDataset');
  const [selectedPool, setSelectedPool] = draft.field('selectedPool');
  const [selectedPolicy, setSelectedPolicy] = draft.field('selectedPolicy');
  const [seed, setSeed] = draft.field('seed');
  const [manualSteps, setSteps] = draft.field('steps');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Run | null>(null);
  const uploadedRevision = readGuidedValue<GuidedRevision>(revisionJson);
  const registeredRevision = datasetRevisions.find(revision => String(revision.id) === selectedDataset);
  const revision = uploadedRevision && String(uploadedRevision.id) === selectedDataset ? uploadedRevision :
    registeredRevision?.metadata && registeredRevision.row_count != null ? registeredRevision as GuidedRevision : null;
  const configuration = { ...trainingDefaults, mode, recipe, base, tokenizer, runner, selectedDataset, selectedPool, selectedPolicy,
    seed, steps: manualSteps, learningRate, validationInterval, preset, project };
  const steps = trainingStepCount(configuration, revision);
  const plan = guidedPlan(revision, recipe === 'lora_adapter');
  const selectedModel = models.find(model => String(model.id) === base);
  const trainingCapability = selectedModel?.capabilities?.train;
  const audioProfile = selectedModel?.architecture_ref === 'modelanvil.speecht5-cpu-output-head.v1';
  const visionProfile = selectedModel?.architecture_ref?.startsWith('modelanvil.smolvlm-') || false;
  useEffect(() => {
    if (audioProfile) { setRecipe('tts_output_head'); setPreset('custom'); setSteps('3'); setSeed('42'); }
    if (visionProfile) { setRecipe('lora_adapter'); setPreset('custom'); setSteps('3'); setSeed('42'); }
  }, [base, visionProfile, audioProfile]);
  const modelLabel = modelName || selectedModel?.model_name || '';
  const datasetLabel = registeredRevision?.dataset_name || (revision?.dataset_name ?? '');
  const canReview = !!tokenizer && (recipe === 'scratch_pretraining' || !!base) && Number.isInteger(steps) && steps > 0 && steps <= (audioProfile ? 10 : visionProfile ? 20 : 3000) &&
    (mode === 'simulation' || !!selectedDataset && !!selectedPool && !!selectedPolicy && !!runner);
  const focusRun = latestTrainingRun(runs, currentRunId);
  const visionRun = focusRun?.runtime?.pins?.runtime?.startsWith('modelanvil.smolvlm-') || false;
  const audioRun = focusRun?.runtime?.pins?.runtime === 'modelanvil.speecht5-cpu-output-head.v1';
  const visualEvaluation = focusRun?.runtime?.independent_evaluation;
  const detailRun = tab === 'current-run' ? focusRun : selected;
  function prepareModel(inputs: GuidedInputs, name: string) {
    const fields = preparedTrainingFields(inputs, name);
    for (const key of Object.keys(fields) as Array<keyof typeof fields>) draft.field(key)[1](fields[key]);
    setPreset('recommended');
    void loadDependencies();
  }
  function prepareDataset(value: GuidedRevision) {
    setSelectedDataset(String(value.id)); setRevisionJson(JSON.stringify(value)); setPreset('recommended');
    void loadDependencies();
  }
  const [preflight, setPreflight] = useState<PreflightReport | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const preflightGeneration = useRef(0);
  useEffect(() => {
    preflightGeneration.current += 1;
    setPreflight(null); setPreflightBusy(false); setPilotReport(null); setPilotBusy(false);
  }, [mode, recipe, tokenizer, base, selectedDataset, selectedPool, selectedPolicy, runner, steps, seed, learningRate, validationInterval, pilotSteps, token, refreshKey]);


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
  }, [detailRun?.run_id]);

  const [openTokenizer, setOpenTokenizer] = useState(0);

  const loadDependencies = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [r, t, m, dRes, pRes, bRes, manifests] = await Promise.all([
        allResources<Run>('/api/v1/training-runs/', token, signal).then(results => ({ results })),
        allResources<Tokenizer>('/api/v1/tokenizers/', token, signal).then(results => ({ results })),
        allResources<ModelVersion>('/api/v1/model-versions/', token, signal).then(results => ({ results })),
        allResources<DatasetRevision>('/api/v1/dataset-revisions/', token, signal).then(results => ({ results })).catch(() => ({ results: [] })),
        allResources<WorkerPool>('/api/v1/worker-pools/', token, signal).then(results => ({ results })).catch(() => ({ results: [] })),
        allResources<BudgetPolicy>('/api/v1/budget-policies/', token, signal).then(results => ({ results })),
        allResources<Runner>('/api/v1/runner-manifests/', token, signal).then(results => ({ results })),
      ]);
      if (!signal?.aborted) {
        setRuns(r.results);
        setRunsRefreshedAt(Date.now()); setProgressError(null);
        setSelected((current) =>
          current ? r.results.find((run) => run.run_id === current.run_id) || null : null
        );
        setTokenizers(t.results);
        setModels(m.results);
        setDatasetRevisions((dRes.results || []).filter((d) => d.state === 'published'));
        setPools((pRes.results || []).filter((p) => p.status === 'active'));
        setPolicies((bRes.results || []).filter((p) => p.enabled && p.unit === 'training_steps' && !p.currency));
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

  useEffect(() => {
    const id = new URLSearchParams(routeHash.split('?')[1]).get('run');
    if (!id) return;
    if (tab === 'current-run') setCurrentRunId(id);
    else if (tab === 'history') setSelected(runs.find(run => run.run_id === id) || null);
  }, [routeHash, runs]);

  const progressRequest = useRef(false);
  const refreshProgress = useCallback(async (signal?: AbortSignal) => {
    if (progressRequest.current) return;
    progressRequest.current = true;
    try {
      const values = await allResources<Run>('/api/v1/training-runs/', token, signal);
      if (!signal?.aborted) {
        setRuns(values); setRunsRefreshedAt(Date.now()); setProgressError(null);
        setSelected(current => current ? values.find(run => run.run_id === current.run_id) || null : null);
      }
    } catch (e) { if (!signal?.aborted) setProgressError(errorMessage(e)); }
    finally { progressRequest.current = false; }
  }, [token]);
  const hasActiveRuns = runs.some((run) => ['pending', 'running'].includes(run.status));
  useEffect(() => {
    if (!hasActiveRuns) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refreshProgress(controller.signal);
    }, 3000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [hasActiveRuns, refreshProgress]);

  const referenceRuntime = ['modelanvil.cpu-character-sft.v1', 'modelanvil.general-transformer-sft.v1'].includes(models.find(m => String(m.id) === base)?.architecture_ref || '');
  function launchPayload() { return trainingLaunchPayload(configuration, steps, referenceRuntime); }
  function requestKey(inputs: Record<string, unknown>) {
    const fingerprint = JSON.stringify(inputs);
    if (launchKey && launchInputs === fingerprint) return launchKey;
    const key = crypto.randomUUID(); setLaunchKey(key); setLaunchInputs(fingerprint); return key;
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!canReview || setupBusy || pilotBusy || (mode === 'simulation' && !demoAcknowledged) || (mode === 'worker' && (preflight?.status !== 'approved' || !preflight.preflight_token))) return;
    setBusy(true); setError(null); setNotice('');
    try {
      const inputs = launchPayload();
      const key = requestKey(inputs);
      const body = JSON.stringify({ ...inputs, ...(mode === 'worker' ? { preflight_token: preflight?.preflight_token } : {}) });
      const run = await apiRequest<Run>('/api/v1/training-runs/', token, {
        method: 'POST',
        headers: {
          'Idempotency-Key': key,
        },
        body,
      });

      setLaunchKey(''); setLaunchInputs('');
      setCurrentRunId(run.run_id);
      setNotice('Training run dispatched successfully. Follow its live progress below.');
      setPreflight(null); navigateTab('current-run', run.run_id); requestAnimationFrame(() => tabPanel.current?.focus());
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
      if (tab === 'current-run') setCurrentRunId(runId);
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

  async function runPreflight() {
    if (!canReview || setupBusy) return;
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

  async function previewPilot() {
    const generation = ++preflightGeneration.current;
    setPilotBusy(true); setError(null); setPilotReport(null);
    try { const report = await apiRequest<PreflightReport>('/api/v1/training-runs/preflight/', token, { method: 'POST', body: JSON.stringify({ ...launchPayload(), total_steps: Number(pilotSteps), purpose: 'pilot' }) }); if (generation === preflightGeneration.current) setPilotReport(report); }
    catch (e) { if (generation === preflightGeneration.current) setError(errorMessage(e)); } finally { if (generation === preflightGeneration.current) setPilotBusy(false); }
  }
  async function launchPilot() {
    if (pilotReport?.status !== 'approved' || !pilotReport.preflight_token || !canReview || busy || setupBusy || pilotBusy) return;
    setPilotBusy(true); setError(null);
    try {
      const inputs = { ...launchPayload(), total_steps: Number(pilotSteps), purpose: 'pilot' };
      const key = requestKey(inputs);
      const body = JSON.stringify({ ...inputs, preflight_token: pilotReport.preflight_token });
      const run = await apiRequest<Run>('/api/v1/training-runs/', token, { method: 'POST', headers: { 'Idempotency-Key': key }, body });
      setLaunchKey(''); setLaunchInputs(''); setPilotReport(null); setRuns(current => [run, ...current]); setSelected(run); setCurrentRunId(run.run_id); navigateTab('current-run', run.run_id);
      setNotice(`Real metered pilot queued: ${pilotSteps} optimizer steps. Monetary cost remains unknown unless priced usage is recorded.`);
    } catch (e) { setError(errorMessage(e)); } finally { setPilotBusy(false); }
  }
  const compared = comparisonIds.split(',').filter(Boolean).map(id => runs.find(run => run.run_id === id)).filter((run): run is Run => !!run);
  const compareBlocked = comparisonBlockers(compared);
  const handoffError = useResourceHandoff(token, (kind, value) => {
    if (kind === 'model-version') { setBase(String(value.id)); setTokenizer(String(value.tokenizer || '')); setModelName(''); setPreset('custom'); setAdvanced(true); }
    else {
      setSelectedDataset(String(value.id));
      const metadata = value.metadata;
      if (value.revision_id && typeof value.row_count === 'number' && metadata?.split_counts) {
        setRevisionJson(JSON.stringify({ id: value.id, revision_id: value.revision_id, row_count: value.row_count, dataset_name: value.dataset_name || 'Approved snapshot', metadata: { split_counts: metadata.split_counts, source_group_count: metadata.source_group_count || 0 } }));
      } else setRevisionJson('');
      setAdvanced(false); setPreset('recommended'); draft.field('guidedStage')[1](2);
    }
    setPreflight(null);
  });
  const lossSeries = trainingLossSeries(focusRun?.metrics_log);
  const savedCheckpoints = runs.reduce((sum, run) => sum + run.checkpoints.length, 0);
  const tabs: Array<{ value: TrainingTab; label: string }> = [{ value: 'configure', label: 'Configure' }, { value: 'current-run', label: 'Current run' }, { value: 'history', label: 'History' }];
  const locked = busy || setupBusy || pilotBusy;
  const historicalRuns = [...runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const runLabel = (id: string) => `Training run ${runs.findIndex(run => run.run_id === id) + 1}`;
  const exportPanel = detailRun?.status === 'completed' ? <ModelExport key={`export-${detailRun.run_id}`} runId={detailRun.run_id}
    options={detailRun.export_options || []} token={token} checkpointStep={detailRun.quality_summary?.selected_step ?? detailRun.total_steps}
    synthetic={detailRun.runtime?.execution_mode === 'simulation'} evidence={detailRun.execution_evidence} /> : null;

  const runDetail = detailRun ? (
          <div className="detail-box">
            <div className="actions" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3>{runLabel(detailRun.run_id)} <Identifier value={detailRun.run_id} label="Run ID" /></h3>
                <Badge className={`state state-${detailRun.status}`}>{detailRun.status}</Badge>
                <EvidenceLabel evidence={detailRun.execution_evidence} />
              </div>
              <div style={{ display: 'flex', gap: 'var(--space-8)' }}>
                {tab === 'history' && detailRun.status === 'completed' && detailRun.output_model_version_uuid && <a className="primary" href={`#chat?model_version=${encodeURIComponent(detailRun.output_model_version_uuid)}`}>Try your model</a>}
                {tab === 'history' && detailRun.status === 'completed' && detailRun.output_model_version_uuid && detailRun.base_model_version && <a href={`#chat?model_version=${encodeURIComponent(detailRun.output_model_version_uuid)}&compare_base=1`}>Compare with base model</a>}
                {(detailRun.status === 'running' || detailRun.status === 'pending') && (
                  <Button
                    type="button"
                    style={{ borderColor: 'var(--error)', color: 'var(--error)' }}
                    disabled={busy}
                    onClick={() => cancelRun(detailRun.run_id)}
                  >
                    <XCircle size={14} /> Cancel run
                  </Button>
                )}
                <a href={runHash('training', detailRun.run_id)}>Open run</a>
                {tab === 'history' && <Button onClick={() => { setSelected(null); navigateTab('history'); }}>Close details</Button>}
              </div>
            </div>

            {tab === 'history' && exportPanel}

            <p className="muted">
              Tokenizer {tokenizers.find(t => t.id === detailRun.tokenizer_version)?.name || 'version'} <Identifier value={String(detailRun.tokenizer_version)} label="Tokenizer record ID" /> {detailRun.runtime?.execution_mode === 'worker' ? '· Pinned base weights' : `· Seed ${detailRun.initialization_seed}`} · Base model{' '}
              {detailRun.base_model_version ? <>{models.find(m => m.id === detailRun.base_model_version)?.model_name || 'Pinned version'} <Identifier value={String(detailRun.base_model_version)} label="Base model record ID" /></> : 'Random init'}
              {detailRun.dataset_manifest_digest && <> · Dataset manifest <Identifier value={detailRun.dataset_manifest_digest} label="Dataset manifest digest" /></>}
              {detailRun.job && <> · Job <Identifier value={detailRun.job} label="Job ID" /></>}
            </p>

            {detailRun.quality_summary && <Notice className="notice"><h4>Training result</h4>
              <p>Selected checkpoint: step {detailRun.quality_summary.selected_step} of {detailRun.total_steps}.</p>
              {detailRun.quality_summary.validation_loss != null && detailRun.quality_summary.baseline_loss != null ? <>
                <p>Validation loss: {detailRun.quality_summary.baseline_loss.toLocaleString(undefined, { maximumSignificantDigits: 4 })} before training → {detailRun.quality_summary.validation_loss.toLocaleString(undefined, { maximumSignificantDigits: 4 })} for the selected model. Lower is better.</p>
                <p>{detailRun.quality_summary.validation_loss < detailRun.quality_summary.baseline_loss ? 'Validation improved.' : 'Validation did not improve.'} Based on {detailRun.quality_summary.validation_examples} validation examples; check actual answers too.</p>
              </> : <p>No validation examples were available. Test the model on independent examples before using it for real work.</p>}
            </Notice>}
            {/* Checkpoints & Safetensors weights */}
            <h4>Saved checkpoints ({detailRun.checkpoints.length})</h4>
            {detailRun.checkpoints.length > 5 && <p className="muted">Showing the latest 5 checkpoints.</p>}
            {detailRun.checkpoints.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
                {detailRun.checkpoints.slice(-5).map((c) => (
                  <div key={c.checkpoint_id} style={{ padding: 'var(--space-8)', background: 'var(--surface-subtle)', borderRadius: '4px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <strong>Step {c.step}</strong>
                      <Badge className={`state state-${c.is_valid ? 'completed' : 'failed'}`}>
                        <CheckCircle size={12} style={{ display: 'inline', marginRight: 'var(--space-4)' }} />
                        {c.is_valid ? 'Valid Safetensors' : 'Invalid'}
                      </Badge>
                    </div>
                    <div className="muted" style={{ fontSize: '11px', marginTop: 'var(--space-4)' }}>
                      State digest <Identifier value={c.state_digest} label="Checkpoint state digest" />
                    </div>
                    {(c.weights_manifest?.weights_sha256 || c.weights_manifest?.weights?.weights_sha256) && (
                      <div className="muted" style={{ fontSize: '11px' }}>
                        Weights SHA-256 <Identifier value={c.weights_manifest?.weights_sha256 || c.weights_manifest?.weights?.weights_sha256 || ''} label="Weights SHA-256" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No checkpoints recorded yet.</p>
            )}

            {/* External Inference Candidate Testing */}
            {detailRun.runtime?.pins?.runtime?.startsWith('modelanvil.smolvlm-') ? <p className="muted">Vision candidates require an image. {detailRun.output_model_version_uuid && <a href={`#chat?model_version=${encodeURIComponent(detailRun.output_model_version_uuid)}`}>Open image chat</a>}</p> : <details style={{ marginTop: 'var(--space-20)', borderTop: '1px solid var(--color-border, #e2e8f0)', paddingTop: 'var(--space-16)' }}>
              <summary>Advanced inference check</summary>
              <p className="muted" style={{ fontSize: 'var(--type-13)' }}>
                Load the exported weights and decode text in the server CPU runtime. GPU inference uses the independent consumer on the worker host.
              </p>
              <div className="training-inference-controls">
                <Field
                  type="text"
                  aria-label="Inference test prompt"
                  placeholder="Enter test prompt…"
                  value={inferPrompt}
                  onChange={(e) => setInferPrompt(e.target.value)}
                  style={{ flex: 1 }}
                />
                <Field
                  type="number"
                  min="1"
                  max="32"
                  aria-label="Maximum generated tokens"
                  value={inferMaxTokens}
                  onChange={(e) => setInferMaxTokens(e.target.value)}
                  style={{ width: '80px' }}
                />
                <Button
                  type="button"
                  className="primary"
                  disabled={inferring || !inferPrompt.trim() || detailRun.status !== 'completed'}
                  onClick={() => runExternalInference(detailRun.run_id)}
                >
                  {inferring ? <RefreshCw size={14} className="spin" /> : <Play size={14} />} Run inference
                </Button>
              </div>

              {inferError && (
                <Notice className="notice danger" style={{ marginTop: 'var(--space-8)' }}>
                  {inferError}
                </Notice>
              )}

              {inferResult && (
                <div style={{ marginTop: 'var(--space-12)', padding: 'var(--space-12)', background: 'var(--color-bg-secondary, #f8f9fa)', borderRadius: 'var(--radius-6)' }}>
                  <div style={{ display: 'flex', gap: 'var(--space-16)', marginBottom: 'var(--space-8)' }}>
                    <Badge className="state state-completed">
                      Format: {inferResult.verification.format}
                    </Badge>
                    <Badge className="state state-completed">
                      CPU load and inference: {inferResult.verification.is_loadable ? 'Passed' : 'Failed'} · Independent runtime unverified
                    </Badge>
                    <span className="muted" style={{ fontSize: 'var(--type-12)' }}>
                      Tensors: {inferResult.verification.num_tensors}
                    </span>
                  </div>
                  <div style={{ fontSize: 'var(--type-12)', marginBottom: 'var(--space-6)' }}>
                    <strong>Candidate Weights SHA-256:</strong>{' '}
                    <Identifier value={inferResult.verification.weights_sha256} label="Verified weights SHA-256" />
                  </div>
                  <div style={{ padding: 'var(--space-8)', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '4px', fontFamily: 'monospace', fontSize: 'var(--type-13)' }}>
                    <strong>Prompt:</strong> {inferResult.inference.prompt}
                    <br />
                    <strong>Completion:</strong>{' '}
                    <span style={{ color: 'var(--primary-text)' }}>
                      {inferResult.inference.completion}
                    </span>
                  </div>
                </div>
              )}
            </details>}
          </div>
        ) : null;

  return (
    <>
    <div className="page-actions">
      <PrerequisiteActions token={token} openTokenizer={openTokenizer} onTokenizer={tokenizer => { setTokenizers(current => [...current, tokenizer]); setTokenizer(String(tokenizer.id)); }} onVersion={version => { setModels(current => [...current, version]); setBase(String(version.id)); setModelName(''); }} />
      <Button className="primary" hidden={tab === 'configure'} disabled={!token.trim() || loading} onClick={() => { navigateTab('configure'); draft.field('guidedStage')[1](base && selectedDataset ? 2 : 0); }}>Configure a run</Button>
    </div>
    <Card className="panel ml-page ml-main-panel ml-training">
      <div className="panel-body">
        <div className="training-tabs" role="tablist" aria-label="Training workspace">
          {tabs.map((item, index) => <Tab key={item.value} ref={element => { tabRefs.current[index] = element; }}
            type="button" role="tab" id={`training-tab-${item.value}`} aria-controls={`training-panel-${item.value}`}
            aria-selected={tab === item.value} tabIndex={tab === item.value ? 0 : -1}
            onClick={() => navigateTab(item.value)} onKeyDown={event => {
              const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
              if (next !== null) { event.preventDefault(); navigateTab(tabs[next].value); tabRefs.current[next]?.focus(); }
            }}>{item.label}{item.value === 'current-run' && hasActiveRuns && <span className="training-live-dot" aria-label="Training active" />}</Tab>)}
        </div>
        {(loading || runs.length > 0) && <div className="ml-stat-strip" aria-label="Loaded training summary">
          <div><span>Training runs</span><strong>{loading ? '—' : runs.length}</strong><small>All accessible recorded runs</small></div>
          <div><span>Active runs</span><strong>{loading ? '—' : runs.filter(r => ['pending', 'running'].includes(r.status)).length}</strong><small>Pending or running</small></div>
          <div><span>Saved checkpoints</span><strong>{loading ? '—' : savedCheckpoints}</strong><small>Recorded checkpoint artifacts</small></div>
          <div><span>Latest selected loss</span><strong>{focusRun?.latest_loss == null ? '—' : focusRun.latest_loss.toFixed(4)}</strong><small>{focusRun ? runLabel(focusRun.run_id) : 'Select a recorded run'}</small></div>
        </div>}
        <>{handoffError && <p role="alert">{handoffError}</p>}</><ResourceState loading={loading} error={error} onRetry={() => setRetry((v) => v + 1)} />
        {notice && (
          <Notice tone="success" className="notice success" role="status">
            {notice}
          </Notice>
        )}
        <div id="training-panel-configure" role="tabpanel" aria-labelledby="training-tab-configure" hidden={tab !== 'configure'}>
          <div className="training-config-heading"><div><h3>Configure your training run</h3><p>Simple and advanced settings share the same saved configuration.</p></div>
            <Button type="button" aria-expanded={advanced} aria-controls="training-advanced-settings" disabled={locked || preflightBusy}
              onClick={() => { setAdvanced(value => !value); if (advanced) draft.field('guidedStage')[1](base && selectedDataset ? 2 : base ? 1 : 0); }}>{advanced ? 'Hide advanced settings' : 'Advanced settings'}</Button>
          </div>
          <div className={`training-config-layout${advanced || base && selectedDataset ? '' : ' training-config-guided'}`}>
            <div className="training-config-fields">
              <div hidden={advanced || mode !== 'worker'}><GuidedFineTune token={token} draft={draft} modelLabel={modelLabel} datasetLabel={datasetLabel} datasetRevisionId={registeredRevision?.revision_id || revision?.revision_id}
                onModelPrepared={prepareModel} onDatasetPrepared={prepareDataset} onBusyChange={setSetupBusy} /></div>
              <form id="training-launch" onSubmit={create}>
                <fieldset disabled={locked || preflightBusy} className="training-fieldset">
                  <div id="training-advanced-settings">{advanced && <div className="form-grid">
                    <h3 className="full-width">Model, data and compute</h3>
            <label>Execution
              <select value={mode} onChange={(e) => { setMode(e.target.value); setRecipe('full_sft'); setSelectedPool(''); setSelectedPolicy(''); setRunner(''); }}>
                <option value="worker">Worker fine-tuning</option>
                <option value="simulation">Synthetic training fixture (demo — not a real model)</option>
              </select>
            </label>
            <label>
              Recipe type
              <select aria-label="Recipe type" value={recipe} onChange={(e) => { setRecipe(e.target.value); if (e.target.value === 'continued_pretraining') { setPreset('custom'); setSteps('3'); } }}>
                <option value="full_sft">Full parameter SFT</option>
                {mode === 'worker' && <option value="lora_adapter">LoRA · pinned CPU/GPU text or vision profile</option>}{mode === 'worker' && <option value="tts_output_head">Speech output head · pinned CPU audio profile</option>}
                {mode === 'worker' && <option value="qlora_adapter">Apple GPU QLoRA · four-bit SmolLM2 profile</option>}
                {mode === 'worker' && <option value="continued_pretraining">CPU/GPU continued pretraining · pinned text corpus</option>}
                {mode === 'simulation' && <>
                  <option value="lora_adapter">LoRA adapter fixture</option>
                  <option value="continued_pretraining">Continued pretraining fixture</option>
                  <option value="scratch_pretraining">Scratch pretraining fixture</option>
                </>}
              </select>
            </label>

            <label>
              Tokenizer version
              <div style={{ display: 'flex', gap: 'var(--space-8)' }}>
                <select
                  aria-label="Tokenizer version" required
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
                <Button
                  type="button"
                  style={{ whiteSpace: 'nowrap' }}
                  onClick={() => setOpenTokenizer(value => value + 1)}
                >
                  + New
                </Button>
              </div>
            </label>

            {recipe !== 'scratch_pretraining' && <ResourcePicker label="Base model version" loading={loading} disabled={busy || preflightBusy} required value={base} onChange={value => { setBase(value); setModelName(''); }}
              options={models.map(m => ({ value: String(m.id), id: m.model_version_id, name: m.model_name, revision: m.revision_no, state: m.state,
                href: resourceHash('model-version', m.model_version_id), description: m.capabilities?.train.reason,
                unavailable: mode === 'worker' && (!m.capabilities?.train.eligible || !m.capabilities.train.recipes.includes(recipe)) ? m.capabilities?.train.reason || 'This model does not support the selected training recipe.' : undefined }))}
              />}

            {audioProfile && <p className="muted full-width">Speech output-head training uses paired PCM16 WAV/FLAC recordings and transcripts, protected speaker/source splits and 1–10 CPU updates. Import the exact processor/vocoder profile with setup_audio_training. Independent intelligibility checks and human quality remain separate gates.</p>}
            {visionProfile && <p className="muted full-width">Vision LoRA uses one PNG/JPEG and a question/answer per sample, protected image/source splits, the pinned processor and 1–20 updates. Register paired inputs on the worker host with setup_vlm_training. Independent visual scores remain separate from production qualification.</p>}
            <p className="muted full-width"><a href="#models">Initialize a CPU base in Models</a> or select a pinned pretrained CPU or GPU base registered on your worker host. Choose its matching tokenizer.</p>
            {base && mode === 'worker' && <p className="muted full-width">{models.find(m => String(m.id) === base)?.capabilities?.train.reason || 'Inspect model compatibility in Models before launch.'}</p>}
            {base && mode === 'worker' && <ModelHardwareFit memory={selectedModel?.capabilities?.memory_requirements}
              targets={hardware.workers.filter(worker => !selectedPool || String(worker.pool) === selectedPool).map(worker => workerHardware(worker, hardware.reportedAt))}
              compatible={!trainingCapability || trainingCapability.eligible && trainingCapability.recipes.includes(recipe)}
              reason={trainingCapability?.eligible && !trainingCapability.recipes.includes(recipe) ? 'This model does not support the selected training recipe.' : trainingCapability?.reason} />}
            {base && hardware.error && <p className="muted full-width" role="status">Hardware inventory unavailable: {hardware.error}</p>}
            <ResourcePicker label="Prepared dataset revision" action={registeredRevision && <Identifier value={registeredRevision.manifest_digest} label="Dataset manifest digest" />} loading={loading} disabled={busy || preflightBusy} required={mode === 'worker'} value={selectedDataset} onChange={setSelectedDataset}
              options={datasetRevisions.map(d => ({ value: String(d.id), id: d.revision_id, name: d.dataset_name || 'Dataset', revision: d.revision_no,
                state: d.state, description: `${d.row_count ?? 'Unknown'} rows`, href: resourceHash('dataset-revision', d.revision_id) }))} />
            {mode === 'worker' && recipe === 'continued_pretraining' && <ContinuedCorpusBuilder key={refreshKey} token={token} revisions={datasetRevisions} onPublished={id => { setSelectedDataset(String(id)); setRevisionJson(''); setPreset('custom'); setSteps('3'); void loadDependencies(); }} />}
            {advanced && mode === 'worker' && registeredRevision && <div className="full-width"><PreparedDatasetPreview key={`${registeredRevision.revision_id}-${refreshKey}`} revisionId={registeredRevision.revision_id} token={token} /></div>}

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
                  <option key={p.policy_id} value={p.policy_id} disabled={p.allowance !== undefined && Number(p.allowance.remaining_amount) <= 0}>
                    {p.name} (remaining: {p.allowance?.remaining_amount ?? 'check preflight'} · limit: {p.limit_amount} {p.unit})
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
              <Field
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

            {mode === 'worker' && referenceRuntime && <><label>Learning rate<Field type="number" min="0.000001" max="0.2" step="any" value={learningRate} placeholder="Pinned runtime default" onChange={e => setLearningRate(e.target.value)} /></label><label>Validation interval<Field type="number" required min="0" max="1000" value={validationInterval} onChange={e => setValidationInterval(e.target.value)} /></label><p className="muted full-width">Validation interval 0 disables validation; otherwise the source must have separate validation groups. Schedule is constant, with a full optimizer checkpoint at every committed step. GPU profiles keep their declared optimizer and cadence.</p></>}
                  </div>}</div>
                  {(advanced || selectedDataset) && <section className="training-plan detail-box">
                    <h3>Training plan</h3>
                    <label>Training plan<select value={preset} onChange={event => { setPreset(event.target.value); if (event.target.value === 'custom') setSteps(String(steps || 50)); }}>
                      <option value="recommended" disabled={!revision}>Recommended{revision ? ` · ${plan.epochs} passes` : ' · prepare a dataset first'}</option>
                      <option value="quick">Quick setup check · 3 steps</option><option value="custom">Custom step count</option>
                    </select></label>
                    {preset === 'custom' && <label>Total steps<Field required type="number" min="1" max={audioProfile ? 10 : visionProfile ? 20 : 3000} step="1" value={manualSteps} onChange={event => setSteps(event.target.value)} /></label>}
                    <p>{preset === 'recommended' ? revision ? `${plan.epochs} complete passes through ${plan.trainingExamples} training examples (${steps} updates).` : 'Add your dataset to calculate the recommended training plan automatically.' : `${steps} training updates.`}</p>
                    {preset === 'quick' && <p>This short run checks your setup. Use more training steps to assess model quality.</p>}
                    {revision && <p>{revision.metadata.split_counts.validation ?? 0} validation and {revision.metadata.split_counts.test ?? 0} test examples remain held out.</p>}
                    {mode === 'simulation' && <><p>This demo does not train a real model. Its result cannot be recorded as an improvement.</p><label className="data-license-consent"><input type="checkbox" checked={demoAcknowledged} onChange={event => setDemoAcknowledged(event.target.checked)} /><span>I understand this is a demo and cannot be accepted.</span></label><Button className="primary" disabled={!canReview || !demoAcknowledged}>Create CPU training fixture</Button></>}
                  </section>}
                </fieldset>
              </form>
              {advanced && mode === 'worker' && <details className="detail-box"><summary>Measured pilot (optional)</summary><label>Pilot optimizer steps<Field type="number" min="1" max="10" value={pilotSteps} onChange={e => setPilotSteps(e.target.value)} disabled={locked} /></label><Button disabled={locked || !canReview} onClick={() => void previewPilot()}>Review pilot preflight</Button><p className="muted">A pilot trains real weights and reserves its actual step count. A matching completed execution can inform the duration estimate; monetary cost stays unknown without a recorded rate.</p>{pilotReport && <PreflightChecklist report={pilotReport} busy={locked} title="Pilot preflight" launchLabel="Launch real metered pilot" onLaunch={() => void launchPilot()} onRefresh={() => void previewPilot()} />}</details>}
              <details className="training-draft"><summary>Saved configuration</summary><DraftStatus draft={draft} disabled={locked || preflightBusy} /></details>
            </div>
            {(advanced || base && selectedDataset) && <aside className="training-run-preview detail-box" aria-label="Run summary">
              <span className="ml-eyebrow">RUN SUMMARY</span><h3>Your training run</h3>
              <dl className="guided-review"><div><dt>Model</dt><dd>{base ? modelLabel || `Model #${base}` : recipe === 'scratch_pretraining' ? 'Random initialization' : 'Choose a model'}</dd></div>
                <div><dt>Dataset</dt><dd>{selectedDataset ? datasetLabel || `Revision #${selectedDataset}` : 'Choose a dataset'}</dd></div>
                <div><dt>Method</dt><dd>{recipe.replaceAll('_', ' ')}</dd></div>
                <div><dt>Compute</dt><dd>{mode === 'simulation' ? 'Synthetic fixture' : pools.find(pool => String(pool.id) === selectedPool)?.name || 'Prepare or select compute'}</dd></div>
                <div><dt>Training steps</dt><dd>{steps > 0 ? steps : 'Prepare a dataset'}</dd></div>
              </dl>
              <p className="muted">{mode === 'worker' ? `Reserves ${steps > 0 ? steps : 'the selected'} training steps. Preflight checks compatibility, hardware, storage and allowance before launch.` : 'Synthetic fixtures use no worker or compute budget.'}</p>
              {mode === 'worker' && <Button type="button" className="primary" disabled={locked || preflightBusy || !canReview} onClick={() => void runPreflight()}>{preflightBusy ? 'Checking…' : 'Preview preflight'}</Button>}
              {!canReview && <p role="status">Choose compatible model, tokenizer, dataset, compute and training settings to review this run.</p>}
            </aside>}
          </div>
          {preflight && <PreflightChecklist report={preflight} busy={locked || preflightBusy} form="training-launch" compact={!advanced} onRefresh={() => void runPreflight()} />}
        </div>
        <div ref={tabPanel} tabIndex={-1} id="training-panel-current-run" role="tabpanel" aria-labelledby="training-tab-current-run" hidden={tab !== 'current-run'}>
          <div className="training-config-heading"><div><h3>Current run</h3><p>Live progress, recorded metrics and checkpoints.</p></div>
            <label>Inspect run<select aria-label="Current training run" value={focusRun?.run_id || ''} onChange={event => { setCurrentRunId(event.target.value); navigateTab('current-run', event.target.value); }}><option value="">Select a run</option>{historicalRuns.map(run => <option key={run.run_id} value={run.run_id}>{runLabel(run.run_id)} · {run.recipe_type} · {run.status}</option>)}</select></label>
          </div>
          {!loading && !focusRun && <div className="training-empty"><h3>{currentRunId ? 'This run is unavailable' : 'No training run yet'}</h3><p>{currentRunId ? 'Refresh the workspace or choose another accessible run.' : 'Prepare your model and data, then launch a training run.'}</p><Button type="button" onClick={() => navigateTab('configure')}>Configure a run</Button></div>}
          {focusRun && <>
        {(focusRun.status === 'running' || focusRun.status === 'pending') && <Button type="button" style={{ borderColor: 'var(--error)', color: 'var(--error)' }} disabled={busy} onClick={() => cancelRun(focusRun.run_id)}><XCircle size={14} /> Cancel run</Button>}
        {tab === 'current-run' && <TrainingRunProgress key={`progress-${focusRun.run_id}`} run={focusRun} refreshedAt={runsRefreshedAt} refreshError={progressError} onRefresh={() => void refreshProgress()} />}
        {focusRun.status === 'completed' && !visionRun && !audioRun && <GuidedDecision key={`${token}:${focusRun.run_id}`} token={token} runId={focusRun.run_id} />}
        {(visionRun || audioRun) && visualEvaluation && <Notice className="notice" role="status"><p>Independent {audioRun ? 'audio' : 'visual'} check: {visualEvaluation.status === 'unavailable' ? 'unavailable' : visualEvaluation.passed ? 'passed' : 'failed'}. This candidate remains a draft; customer quality and production release require separate qualification.</p>{visualEvaluation.reason && <p>{visualEvaluation.reason}</p>}<details><summary>Protected scores and exact input hashes</summary><DataInspector value={visualEvaluation.report || visualEvaluation} /></details></Notice>}
        {focusRun.status === 'completed' && focusRun.output_model_version_uuid && <Notice className="notice"><p>{audioRun ? 'Generate speech and download this draft to inspect it. Human quality and production release require separate qualification.' : 'Chat and download let you inspect this candidate. They are not evidence that it improved, and a downloaded file is not deployed.'}</p><div className="actions">{audioRun ? <a href="#audio">Inspect in Audio</a> : <a href={`#chat?model_version=${encodeURIComponent(focusRun.output_model_version_uuid)}`}>Inspect in chat</a>}{focusRun.base_model_version && !visionRun && !audioRun && <a href={`#chat?model_version=${encodeURIComponent(focusRun.output_model_version_uuid)}&compare_base=1`}>Inspect both models in chat</a>}</div></Notice>}
        {tab === 'current-run' && exportPanel}
        <div className="ml-section-heading"><div><span className="ml-eyebrow">EXPERIMENT MONITOR</span><h3>Loss & checkpoint activity</h3><p>Recorded training loss at committed steps, alongside saved checkpoint artifacts.</p></div></div>
        <div className="visualization-grid">
          <ChartPanel title="Training & validation loss" description={`${runLabel(focusRun.run_id)} · ${focusRun.execution_evidence?.level || 'unknown evidence'} · exact recorded values`}>{lossSeries.length ? <LineChart key={focusRun.run_id} series={lossSeries} xLabel="Committed step" yLabel="Loss" /> : <ChartEmpty message={focusRun.status === 'pending' ? 'This run is queued. Loss will appear after the first measured checkpoint.' : 'No loss measurements have been recorded for this run.'} />}</ChartPanel>
          <ChartPanel title="Checkpoint timeline" description="Saved artifacts from the selected run.">{focusRun ? <><div className="ml-run-progress"><span>Committed steps</span><strong>{focusRun.current_step} / {focusRun.total_steps}</strong><progress value={focusRun.current_step} max={focusRun.total_steps || 1} aria-label="Selected run committed steps" /></div>{focusRun.checkpoints.length ? <EventTimeline events={focusRun.checkpoints.slice(-5).map(c => ({ label: `Checkpoint · step ${c.step}`, detail: c.is_valid ? 'Verified checkpoint artifact' : 'Checkpoint validation failed', status: c.is_valid ? 'completed' : 'failed' }))} /> : <ChartEmpty message="No checkpoint artifacts have been recorded for this run." />}</> : <ChartEmpty message="Create a training run to inspect committed steps and checkpoints." />}</ChartPanel>
        </div>
        {focusRun?.metrics_log?.some(m => m.measured_at) && <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table"><caption>Measured optimizer steps; throughput includes the post-update loss pass. Missing metrics are not estimated.</caption><thead><tr><th>Step / timestamp</th><th>Protected validation loss</th><th>Gradient norm</th><th>{audioRun ? 'Target mel frames/sec' : 'Prediction tokens/sec'}</th><th>Allocated / peak MiB</th><th>GPU utilization</th><th>Trainable / total parameters</th></tr></thead><tbody>{focusRun.metrics_log.slice(-10).map(m => <tr key={m.step}><td>{m.step}<br />{m.measured_at || 'Not reported'}</td><td>{m.validation_loss?.toFixed(6) ?? 'Not reported'}<br />{m.validation_prediction_tokens == null ? '' : `${m.validation_prediction_tokens} prediction tokens`}</td><td>{m.gradient_norm?.toFixed(4) ?? 'Not reported'}</td><td>{(audioRun ? m.prediction_frames_per_second : m.tokens_per_second)?.toFixed(2) ?? 'Not reported'}</td><td>{m.gpu_allocated_bytes == null ? 'Not reported' : (m.gpu_allocated_bytes / 1024**2).toFixed(1)} / {m.peak_allocated_bytes == null ? 'Not reported' : (m.peak_allocated_bytes / 1024**2).toFixed(1)}</td><td>{m.gpu_utilization_percent == null ? 'Not reported' : `${m.gpu_utilization_percent}%`}</td><td>{m.trainable_parameters?.toLocaleString() ?? 'Not reported'} / {m.total_parameters?.toLocaleString() ?? 'Not reported'}</td></tr>)}</tbody></RecordTable></div>}
          </>}
        </div>
        <div id="training-panel-history" role="tabpanel" aria-labelledby="training-tab-history" hidden={tab !== 'history'}>
        <div className="ml-section-heading"><div><h3>Run history</h3><p>Inspect inputs, download candidates, and open the durable execution record.</p></div></div>
        {!loading && !error && !runs.length && <p className="muted">No training runs yet.</p>}
        <section className="detail-box"><h3>Compare recorded experiments</h3><p className="muted">Choose up to two runs using the comparison checkboxes below.</p>
          <p className="muted">Loss overlays require the same recipe, runtime build, tokenizer, architecture, dataset and validation protocol. Different optimizer settings remain visible as experimental changes. QLoRA quantized and unquantized baselines are distinct evidence; execution success does not pass a quality gate.</p>
          {compareBlocked.map(reason => <p key={reason} role="status">{reason}</p>)}
          {compared.map(run => <details key={run.run_id}><summary>{runLabel(run.run_id)} · {run.recipe_type}</summary><Identifier value={run.run_id} label="Run ID" /><DataInspector value={run.runtime} /></details>)}
          {!compareBlocked.length && <LineChart series={compared.flatMap(run => [{ name: `${runLabel(run.run_id)} training`, points: (run.metrics_log || []).map(row => ({ x: row.step, y: row.loss })) }, { name: `${runLabel(run.run_id)} validation`, points: (run.metrics_log || []).flatMap(row => typeof row.validation_loss === 'number' ? [{ x: row.step, y: row.validation_loss! }] : []) }])} yLabel="Comparable loss" />}
        </section>

        {!!runs.length && (
          <div className="table-scroll" tabIndex={0}>
            <RecordTable className="resource-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Recipe</th>
                  <th>State</th>
                  <th>Progress</th>
                  <th>Latest loss</th>
                  <th>Checkpoints</th>
                </tr>
              </thead>
              <tbody>
                {historicalRuns.map((r) => (
                  <tr key={r.run_id} className={selected?.run_id === r.run_id ? 'ml-selected-row' : undefined}>
                    <td>
                      <label><input type="checkbox" checked={comparisonIds.split(',').includes(r.run_id)} onChange={e => setComparisonIds(e.target.checked ? [...comparisonIds.split(',').filter(Boolean).slice(-1), r.run_id].join(',') : comparisonIds.split(',').filter(id => id !== r.run_id).join(','))} />Compare this run</label>
                      <a href={runHash('training', r.run_id)}>{runLabel(r.run_id)}</a> <Identifier value={r.run_id} label="Run ID" />
                      <Button className="text-button" onClick={() => { setSelected(r); navigateTab('history', r.run_id); }}>Inspect run</Button><Button className="text-button" onClick={() => { setCurrentRunId(r.run_id); navigateTab('current-run', r.run_id); }}>View monitor</Button>
                    </td>
                    <td>{r.recipe_type}</td>
                    <td>
                      <Badge className={`state state-${r.status}`}>{r.status}</Badge>
                      <EvidenceLabel evidence={r.execution_evidence} />
                    </td>
                    <td>
                      <progress
                        value={r.current_step}
                        max={r.total_steps || 1}
                        aria-label={`${runLabel(r.run_id)} progress`}
                      />{' '}
                      {r.current_step} / {r.total_steps}
                    </td>
                    <td>{r.latest_loss === null ? 'Not reported' : r.latest_loss.toFixed(6)}</td>
                    <td>{r.checkpoints.length} saved</td>
                  </tr>
                ))}
              </tbody>
            </RecordTable>
          </div>
        )}
          {tab === 'history' && runDetail}
        </div>

      </div>

    </Card>
    </>
  );
}
