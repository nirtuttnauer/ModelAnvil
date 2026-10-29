import { Button, Disclosure, Notice, Select, Tab, TabList } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { GuidedFineTune } from '../components/GuidedFineTune';
import { PreflightChecklist, type PreflightReport } from '../components/PreflightChecklist';
import { PageActions } from '../components/PageActions';
import { JourneySteps } from '../components/primitives/Journey';
import { AdvancedTrainingForm } from '../components/training/AdvancedTrainingForm';
import { TrainingPlanPicker } from '../components/training/TrainingPlanPicker';
import { RunSummary } from '../components/training/RunSummary';
import { CurrentRun } from '../components/training/CurrentRun';
import { RunDetailsPanel } from '../components/training/RunDetailsPanel';
import { RunHistory } from '../components/training/RunHistory';
import { ModelExport } from '../components/ModelExport';
import { useHardwareInventory } from '../components/useHardwareInventory';
import { guidedPlan, readGuidedValue, type GuidedInputs, type GuidedRevision } from '../api/guided-training';
import { trainingDefaults, legacyGuidedDefaults, preparedTrainingFields, migrateGuidedTraining, trainingStepCount, trainingLaunchPayload, trainingTab, latestTrainingRun, type TrainingTab } from '../api/training-workspace';
import { comparisonBlockers } from '../api/run-comparison';
import { allResources } from '../api/resources';
import { useResourceHandoff } from '../components/ResourceHandoff';
import { useDraft, DraftIndicator } from '../components/Draft';
import { useEffect, useState, useCallback, useRef } from 'react';
import { ApiRequestError, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { runHash } from '../api/runs';
import { PREPARE_STEPS } from '../api/journey';
import { trainingMethodLabel, trainingRunLabel, type BudgetPolicy, type DatasetRevision, type ModelVersion, type Runner, type Tokenizer, type TrainingRun, type WorkerPool } from '../api/training';
import './training-workspace.css';

export function TrainingPage({ token = '', refreshKey = 0 }: { token?: string; refreshKey?: number }) {
  const hardware = useHardwareInventory(token, refreshKey);
  const [runs, setRuns] = useState<TrainingRun[]>([]);
  const [runsRefreshedAt, setRunsRefreshedAt] = useState(0);
  const [progressError, setProgressError] = useState<string | null>(null);
  const [tokenizers, setTokenizers] = useState<Tokenizer[]>([]);
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [datasetRevisions, setDatasetRevisions] = useState<DatasetRevision[]>([]);
  const [pools, setPools] = useState<WorkerPool[]>([]);
  const [policies, setPolicies] = useState<BudgetPolicy[]>([]);
  const [runners, setRunners] = useState<Runner[]>([]);
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
  const [guidedStage, setGuidedStage] = draft.field('guidedStage');
  const [setupBusy, setSetupBusy] = useState(false);
  const [routeHash, setRouteHash] = useState(window.location.hash);
  const tab = trainingTab(routeHash);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const tabPanel = useRef<HTMLDivElement>(null);
  function navigateTab(next: TrainingTab, runId?: string) {
    const query = new URLSearchParams(window.location.hash.split('?')[1]);
    query.set('tab', next);
    query.delete('run'); query.delete('model_version'); query.delete('dataset_revision');
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

  const [learningRate] = draft.field('learningRate'), [validationInterval] = draft.field('validationInterval');
  const [pilotSteps, setPilotSteps] = draft.field('pilotSteps'), [comparisonIds, setComparisonIds] = draft.field('comparisonIds');
  const [pilotReport, setPilotReport] = useState<PreflightReport | null>(null);
  const [pilotBusy, setPilotBusy] = useState(false);
  const [mode] = draft.field('mode'), [recipe] = draft.field('recipe'), [runner] = draft.field('runner');
  const [tokenizer, setTokenizer] = draft.field('tokenizer'), [base, setBase] = draft.field('base');
  const [selectedDataset, setSelectedDataset] = draft.field('selectedDataset');
  const [selectedPool] = draft.field('selectedPool'), [selectedPolicy] = draft.field('selectedPolicy');
  const [seed] = draft.field('seed'), [manualSteps, setSteps] = draft.field('steps');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<TrainingRun | null>(null);
  const uploadedRevision = readGuidedValue<GuidedRevision>(revisionJson);
  const registeredRevision = datasetRevisions.find(revision => String(revision.id) === selectedDataset);
  const revision = uploadedRevision && String(uploadedRevision.id) === selectedDataset ? uploadedRevision :
    registeredRevision?.metadata && registeredRevision.row_count != null ? registeredRevision as GuidedRevision : null;
  const configuration = { ...trainingDefaults, mode, recipe, base, tokenizer, runner, selectedDataset, selectedPool, selectedPolicy,
    seed, steps: manualSteps, learningRate, validationInterval, preset, project };
  const steps = trainingStepCount(configuration, revision);
  const plan = guidedPlan(revision, recipe === 'lora_adapter');
  const selectedModel = models.find(model => String(model.id) === base);
  const modelLabel = modelName || selectedModel?.model_name || '';
  const datasetLabel = registeredRevision?.dataset_name || (revision?.dataset_name ?? '');
  const canReview = !!tokenizer && (recipe === 'scratch_pretraining' || !!base) && Number.isInteger(steps) && steps > 0 && steps <= 3000 &&
    (mode === 'simulation' || !!selectedDataset && !!selectedPool && !!selectedPolicy && !!runner);
  const focusRun = latestTrainingRun(runs, currentRunId);
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
  /** Start the next fine-tune at the examples step; the base model stays selected. */
  function startNewRun() {
    setSelectedDataset(''); setRevisionJson(''); draft.field('name')[1](''); draft.field('resumeJson')[1](''); draft.field('columnMappingJson')[1]('{"mode":"auto"}');
    setPreset('recommended'); setAdvanced(false); setPreflight(null); setGuidedStage(base ? 1 : 0);
    navigateTab('configure');
  }
  const [preflight, setPreflight] = useState<PreflightReport | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const preflightGeneration = useRef(0);
  useEffect(() => {
    preflightGeneration.current += 1;
    setPreflight(null); setPreflightBusy(false); setPilotReport(null); setPilotBusy(false);
  }, [mode, recipe, tokenizer, base, selectedDataset, selectedPool, selectedPolicy, runner, steps, seed, learningRate, validationInterval, pilotSteps, token, refreshKey]);

  const loadDependencies = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [r, t, m, dRes, pRes, bRes, manifests] = await Promise.all([
        allResources<TrainingRun>('/api/v1/training-runs/', token, signal),
        allResources<Tokenizer>('/api/v1/tokenizers/', token, signal),
        allResources<ModelVersion>('/api/v1/model-versions/', token, signal),
        allResources<DatasetRevision>('/api/v1/dataset-revisions/', token, signal).catch(() => [] as DatasetRevision[]),
        allResources<WorkerPool>('/api/v1/worker-pools/', token, signal).catch(() => [] as WorkerPool[]),
        allResources<BudgetPolicy>('/api/v1/budget-policies/', token, signal),
        allResources<Runner>('/api/v1/runner-manifests/', token, signal),
      ]);
      if (!signal?.aborted) {
        setRuns(r); setRunsRefreshedAt(Date.now()); setProgressError(null);
        setSelected(current => current ? r.find(run => run.run_id === current.run_id) || null : null);
        setTokenizers(t); setModels(m);
        setDatasetRevisions(dRes.filter(d => d.state === 'published'));
        setPools(pRes.filter(p => p.status === 'active'));
        setPolicies(bRes.filter(p => p.enabled && p.unit === 'training_steps' && !p.currency));
        setRunners(manifests.filter(item => item.enabled && item.compatibility.contract_digest));
      }
    } catch (e) {
      if (!signal?.aborted) { setRuns([]); setTokenizers([]); setModels([]); setError(errorMessage(e)); }
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
      const values = await allResources<TrainingRun>('/api/v1/training-runs/', token, signal);
      if (!signal?.aborted) {
        setRuns(values); setRunsRefreshedAt(Date.now()); setProgressError(null);
        setSelected(current => current ? values.find(run => run.run_id === current.run_id) || null : null);
      }
    } catch (e) { if (!signal?.aborted) setProgressError(errorMessage(e)); }
    finally { progressRequest.current = false; }
  }, [token]);
  const hasActiveRuns = runs.some(run => ['pending', 'running'].includes(run.status));
  useEffect(() => {
    if (!hasActiveRuns) return;
    const controller = new AbortController();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void refreshProgress(controller.signal); }, 3000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [hasActiveRuns, refreshProgress]);

  const referenceRuntime = ['modelanvil.cpu-character-sft.v1', 'modelanvil.general-transformer-sft.v1'].includes(selectedModel?.architecture_ref || '');
  function launchPayload() { return trainingLaunchPayload(configuration, steps, referenceRuntime); }
  function requestKey(inputs: Record<string, unknown>) {
    const fingerprint = JSON.stringify(inputs);
    if (launchKey && launchInputs === fingerprint) return launchKey;
    const key = crypto.randomUUID(); setLaunchKey(key); setLaunchInputs(fingerprint); return key;
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!canReview || setupBusy || pilotBusy || (mode === 'worker' && (preflight?.status !== 'approved' || !preflight.preflight_token))) return;
    setBusy(true); setError(null); setNotice('');
    try {
      const inputs = launchPayload();
      const key = requestKey(inputs);
      const body = JSON.stringify({ ...inputs, ...(mode === 'worker' ? { preflight_token: preflight?.preflight_token } : {}) });
      const run = await apiRequest<TrainingRun>('/api/v1/training-runs/', token, { method: 'POST', headers: { 'Idempotency-Key': key }, body });
      setLaunchKey(''); setLaunchInputs('');
      setCurrentRunId(run.run_id);
      setNotice('Training started. Follow its progress below.');
      setPreflight(null); navigateTab('current-run', run.run_id); requestAnimationFrame(() => tabPanel.current?.focus());
      setRuns(current => [run, ...current]);
      setSelected(run);
    } catch (e) {
      setError(errorMessage(e));
      if (e instanceof ApiRequestError && e.status === 400) setPreflight(null);
    } finally {
      setBusy(false);
    }
  }

  async function cancelRun(runId: string) {
    setBusy(true); setError(null);
    try {
      const updated = await apiRequest<TrainingRun>(`/api/v1/training-runs/${runId}/cancel/`, token, { method: 'POST' });
      setNotice(updated.status === 'cancelled' ? 'Run cancelled.' : 'Cancellation requested; waiting for the worker to acknowledge it.');
      setRuns(current => current.map(r => (r.run_id === runId ? updated : r)));
      setSelected(updated);
      if (tab === 'current-run') setCurrentRunId(runId);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }

  async function runPreflight() {
    if (!canReview || setupBusy) return;
    const generation = ++preflightGeneration.current;
    setPreflightBusy(true); setError(null); setPreflight(null);
    try {
      const report = await apiRequest<PreflightReport>('/api/v1/training-runs/preflight/', token, { method: 'POST', body: JSON.stringify(launchPayload()) });
      if (generation === preflightGeneration.current) setPreflight(report);
    } catch (e) { if (generation === preflightGeneration.current) setError(errorMessage(e)); }
    finally { if (generation === preflightGeneration.current) setPreflightBusy(false); }
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
      const run = await apiRequest<TrainingRun>('/api/v1/training-runs/', token, { method: 'POST', headers: { 'Idempotency-Key': key }, body });
      setLaunchKey(''); setLaunchInputs(''); setPilotReport(null); setRuns(current => [run, ...current]); setSelected(run); setCurrentRunId(run.run_id); navigateTab('current-run', run.run_id);
      setNotice(`Pilot run queued: ${pilotSteps} optimizer steps. Cost stays unknown unless priced usage is recorded.`);
    } catch (e) { setError(errorMessage(e)); } finally { setPilotBusy(false); }
  }
  const compared = comparisonIds.split(',').filter(Boolean).map(id => runs.find(run => run.run_id === id)).filter((run): run is TrainingRun => !!run);
  const compareBlocked = comparisonBlockers(compared);
  // Arriving from Datasets or Models preselects the resource and stays in the wizard.
  const handoffError = useResourceHandoff(token, (kind, value) => {
    if (kind === 'model-version') { setBase(String(value.id)); setTokenizer(String(value.tokenizer || '')); setGuidedStage(selectedDataset ? 2 : 1); }
    else { setSelectedDataset(String(value.id)); setGuidedStage(base ? 2 : 0); }
    setModelName(''); setPreset('recommended'); setAdvanced(false); setPreflight(null);
  });
  const tabs: Array<{ value: TrainingTab; label: string }> = [{ value: 'configure', label: 'Configure' }, { value: 'current-run', label: 'Current run' }, { value: 'history', label: 'History' }];
  const locked = busy || setupBusy || pilotBusy;
  const historicalRuns = [...runs].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const runLabel = (id: string) => trainingRunLabel(runs, id);
  const runHref = (r: TrainingRun) => runHash('training', r.run_id);
  const showSummary = advanced || !!(base && selectedDataset);

  return <div className="training-page">
    <PageActions><Button type="button" variant="primary" hidden={tab === 'configure'} disabled={!token.trim() || loading} onClick={startNewRun}>New training run</Button></PageActions>
    <TabList label="Training workspace">
      {tabs.map((item, index) => <Tab key={item.value} ref={element => { tabRefs.current[index] = element; }}
        type="button" id={`training-tab-${item.value}`} aria-controls={`training-panel-${item.value}`}
        aria-selected={tab === item.value} tabIndex={tab === item.value ? 0 : -1}
        onClick={() => navigateTab(item.value)} onKeyDown={event => {
          const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
          if (next !== null) { event.preventDefault(); navigateTab(tabs[next].value); tabRefs.current[next]?.focus(); }
        }}>{item.label}{item.value === 'current-run' && hasActiveRuns && <span className="training-live-dot" aria-label="Training active" />}</Tab>)}
    </TabList>
    {handoffError && <p role="alert">{handoffError}</p>}
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
    {notice && <Notice tone="success" role="status">{notice}</Notice>}

    <div id="training-panel-configure" role="tabpanel" aria-labelledby="training-tab-configure" hidden={tab !== 'configure'}>
      <div className="training-config-toolbar" data-ui="toolbar">
        <div data-ui="toolbar-filters">{!advanced && mode === 'worker' && <JourneySteps steps={PREPARE_STEPS} current={guidedStage} compact label="Prepare steps" />}</div>
        <div data-ui="toolbar-actions"><Button type="button" aria-expanded={advanced} aria-controls="training-advanced-settings" disabled={locked || preflightBusy}
          onClick={() => { setAdvanced(value => !value); if (advanced) setGuidedStage(base && selectedDataset ? 2 : base ? 1 : 0); }}>{advanced ? 'Hide advanced settings' : 'Advanced settings'}</Button></div>
      </div>
      <div className={`training-config-layout${showSummary ? '' : ' training-config-guided'}`}>
        <div className="training-config-fields">
          <div hidden={advanced || mode !== 'worker'}><GuidedFineTune token={token} draft={draft} modelLabel={modelLabel} datasetLabel={datasetLabel} datasetRevisionId={registeredRevision?.revision_id || revision?.revision_id}
            onModelPrepared={prepareModel} onDatasetPrepared={prepareDataset} onBusyChange={setSetupBusy} /></div>
          <form id="training-launch" onSubmit={create}>
            <fieldset disabled={locked || preflightBusy} className="training-fieldset">
              <div id="training-advanced-settings">{advanced && <AdvancedTrainingForm draft={draft} tokenizers={tokenizers} models={models} datasetRevisions={datasetRevisions} pools={pools} policies={policies} runners={runners}
                loading={loading} busy={busy || preflightBusy} hardware={hardware} referenceRuntime={referenceRuntime} token={token} refreshKey={refreshKey} />}</div>
              {(advanced || selectedDataset) && <TrainingPlanPicker preset={preset} onPreset={setPreset} manualSteps={manualSteps} onSteps={setSteps} steps={steps} revision={revision} plan={plan} synthetic={mode === 'simulation'} canReview={canReview} />}
            </fieldset>
          </form>
          {advanced && mode === 'worker' && <Disclosure summary="Measured pilot (optional)">
            <Select label="Pilot optimizer steps" hint="A pilot trains real weights and reserves its own steps." value={pilotSteps} onChange={e => setPilotSteps(e.target.value)} disabled={locked} options={['1', '2', '3', '5', '10'].map(value => ({ value, label: value }))} />
            <div data-ui="actions"><Button type="button" disabled={locked || !canReview} onClick={() => void previewPilot()}>Run pilot preflight</Button></div>
            {pilotReport && <PreflightChecklist report={pilotReport} busy={locked} title="Pilot preflight" launchLabel="Start pilot run" onLaunch={() => void launchPilot()} onRefresh={() => void previewPilot()} />}
          </Disclosure>}
          <Disclosure summary="Saved configuration" variant="quiet"><DraftIndicator draft={draft} disabled={locked || preflightBusy} /></Disclosure>
        </div>
        {showSummary && <RunSummary model={base ? modelLabel || `Model #${base}` : recipe === 'scratch_pretraining' ? 'Random initialization' : 'Choose a model'}
          dataset={selectedDataset ? datasetLabel || `Version #${selectedDataset}` : 'Choose a dataset'} recipe={recipe}
          compute={mode === 'simulation' ? 'Synthetic run' : pools.find(pool => String(pool.id) === selectedPool)?.name || 'Set up when training starts'}
          steps={steps} synthetic={mode === 'simulation'} canReview={canReview} busy={locked} checking={preflightBusy} onPreflight={() => void runPreflight()} />}
      </div>
      {preflight && <PreflightChecklist report={preflight} busy={locked || preflightBusy} form="training-launch" compact={!advanced} onRefresh={() => void runPreflight()} />}
    </div>

    <div ref={tabPanel} tabIndex={-1} id="training-panel-current-run" role="tabpanel" aria-labelledby="training-tab-current-run" hidden={tab !== 'current-run'}>
      <div data-ui="toolbar" className="training-run-toolbar"><div data-ui="toolbar-filters">
        <Select aria-label="Current training run" value={focusRun?.run_id || ''} onChange={event => { setCurrentRunId(event.target.value); navigateTab('current-run', event.target.value); }}>
          <option value="">Select a run</option>{historicalRuns.map(run => <option key={run.run_id} value={run.run_id}>{runLabel(run.run_id)} · {trainingMethodLabel(run.recipe_type)} · {run.status}</option>)}
        </Select>
      </div></div>
      {!loading && !focusRun && <EmptyState layout="centered" title={currentRunId ? 'This run is unavailable' : 'No training run yet'} description={currentRunId ? 'Refresh the workspace or choose another run.' : 'Choose a model and add your examples, then start training.'} action={<Button type="button" onClick={() => navigateTab('configure')}>New training run</Button>} />}
      {focusRun && tab === 'current-run' && <CurrentRun run={focusRun} label={runLabel(focusRun.run_id)} refreshedAt={runsRefreshedAt} progressError={progressError} onRefresh={() => void refreshProgress()} onCancel={cancelRun} busy={busy} token={token} tokenizers={tokenizers} models={models} />}
    </div>

    <div id="training-panel-history" role="tabpanel" aria-labelledby="training-tab-history" hidden={tab !== 'history'}>
      <RunHistory runs={historicalRuns} selectedId={selected?.run_id} comparisonIds={comparisonIds} onComparisonChange={setComparisonIds} compared={compared} compareBlocked={compareBlocked}
        runLabel={runLabel} runHref={runHref} onInspect={run => { setSelected(run); navigateTab('history', run.run_id); }} onMonitor={run => { setCurrentRunId(run.run_id); navigateTab('current-run', run.run_id); }} />
      {selected && tab === 'history' && <RunDetailsPanel run={selected} label={runLabel(selected.run_id)} tokenizers={tokenizers} models={models} token={token} variant="history" busy={busy} onCancel={cancelRun} onClose={() => { setSelected(null); navigateTab('history'); }}>
        {selected.status === 'completed' && <ModelExport key={`export-${selected.run_id}`} runId={selected.run_id} options={selected.export_options || []} token={token} checkpointStep={selected.quality_summary?.selected_step ?? selected.total_steps} synthetic={selected.runtime?.execution_mode === 'simulation'} />}
      </RunDetailsPanel>}
    </div>
  </div>;
}
