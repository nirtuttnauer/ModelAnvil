import { Identifier } from '../components/Identifier';
import { ImprovementDecision, type Decision } from '../components/ImprovementDecision';
import { GuidedEvaluation, type GuidedEvaluationPreparation, type GuidedEvaluationRun } from '../components/GuidedEvaluation';
import { ImprovementReport, ReviewedModelExport, type DecisionReport } from '../components/ImprovementReport';
import { evaluationSelection } from '../api/improvement';
import { Button, Checkbox, Dialog, Disclosure, KeyValueList, LinkButton, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { MetricComparison } from '../components/MetricComparison';
import { ResourcePicker } from '../components/ResourcePicker';
import { resourceHash } from '../api/resource-routes';
import { RecordListEditor } from '../components/FormEditors';
import { evaluationFields, recordsInput } from '../components/form-data';
import { useResourceHandoff } from '../components/ResourceHandoff';
import { useDraft, DraftIndicator } from '../components/Draft';
import { EvaluationCase } from '../components/DataInspector';
import { useEffect, useId, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { allResources, type RegisteredModel } from '../api/resources';
import { ResourceState } from '../components/ResourceState';
import { runHash } from '../api/runs';
import { statusLabel } from '../api/status';
import { BarChart, ChartPanel, ChartEmpty, MetricsChart, SegmentBar } from '../components/Charts';
import './ml-pages.css';
import './improvement.css';

interface Suite { id: number; suite?: number; suite_version_id: string; suite_name: string; revision_no: number; cases_count: number; source_group_count?: number | null; scorer_type: string; protected_role: string }
interface Metric { key: string; slice_name: string; value: number; sample_count: number; uncertainty_interval: unknown }
interface Coverage { completed: number; missing: number | null; failed: number; total: number | null }
interface Comparison { compatible: boolean; reason: string }
interface Pins { scorer_version?: string; decoding?: string; prompt_format?: string; device?: string; runtime?: string; training_overlap?: string; environment?: { runtime?: string; device?: string; prompt_format?: string; decoding?: string } }
interface Pool { id: number; name: string; status: string }
interface Budget { policy_id: string; name: string; unit: string; enabled: boolean; allowance?: { remaining_amount: string } }
interface Run { candidate_name?: string; baseline_name?: string; decision_report?: DecisionReport; improvement_decision?: Decision | null; job?: string | null; protocol_ref?: { completed_cases?: number; total_cases?: number; decoding?: string; pins?: Pins }; case_coverage?: Coverage; comparison?: Comparison; execution_evidence?: { level: string; source: string }; run_id: string; suite_version: number; candidate_model_version: number; baseline_model_version: number | null; status: string; metrics: Metric[]; baseline_metrics?: Metric[]; created_at: string }
interface Case { result_id: string; case_id: string; input_prompt: string; candidate_output: string; expected_output: string; score: number | null; passed: boolean; failure_reason: string; slice_name: string; baseline_output?: string | null; baseline_score?: number | null }

export function EvaluationPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const setupFormId = useId(), suiteFormId = useId();
  const draft = useDraft('evaluation', { pool: '', budget: '', showSuiteForm: false as boolean, suiteName: '', suiteTarget: '', suiteScorer: 'exact_match', suiteCases: '[{\n  "case_id": "case-1",\n  "input_prompt": "Hello",\n  "expected_output": "hello",\n  "slice": "general",\n  "source_group_id": "held-out"\n}]', maxTokens: '8', setup: false as boolean, suite: '', candidate: '', baseline: '' });
  const [runs, setRuns] = useState<Run[]>([]); const [models, setModels] = useState<RegisteredModel[]>([]); const [suites, setSuites] = useState<Suite[]>([]);
  const [pools, setPools] = useState<Pool[]>([]); const [budgets, setBudgets] = useState<Budget[]>([]); const [pool, setPool] = draft.field('pool'); const [budget, setBudget] = draft.field('budget');
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [retry, setRetry] = useState(0); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState('');
  const [showSuiteForm, setShowSuiteForm] = draft.field('showSuiteForm'); const [suiteName, setSuiteName] = draft.field('suiteName'); const [suiteTarget, setSuiteTarget] = draft.field('suiteTarget'); const [suiteScorer, setSuiteScorer] = draft.field('suiteScorer'); const [suiteCases, setSuiteCases] = draft.field('suiteCases'); const [maxTokens, setMaxTokens] = draft.field('maxTokens');
  const [setup, setSetup] = draft.field('setup'); const [suite, setSuite] = draft.field('suite'); const [candidate, setCandidate] = draft.field('candidate'); const [baseline, setBaseline] = draft.field('baseline');
  const [route, setRoute] = useState(() => evaluationSelection(window.location.hash));
  const [selectedId, setSelectedId] = useState(() => route.evaluationRun); const [cases, setCases] = useState<Case[]>([]); const [casesLoading, setCasesLoading] = useState(false); const [next, setNext] = useState<string | null>(null); const [failuresOnly, setFailuresOnly] = useState(false);
  const selected = runs.find(r => r.run_id === selectedId);
  const runLabel = (id: string) => `Evaluation run ${runs.findIndex(item => item.run_id === id) + 1}`;
  const modelName = (id: number | null) => models.find(m => m.id === id) ? `${models.find(m => m.id === id)!.model_name} · r${models.find(m => m.id === id)!.revision_no}` : id === null ? 'None' : 'Model unavailable';
  useEffect(() => { const changed = () => { const value = evaluationSelection(window.location.hash); setRoute(value); if (value.evaluationRun) setSelectedId(value.evaluationRun); }; window.addEventListener('hashchange', changed); return () => window.removeEventListener('hashchange', changed); }, []);
  function selectRun(id: string) { setSelectedId(id); window.location.hash = id ? `evaluation?run=${encodeURIComponent(id)}` : 'evaluation'; }
  function prepared(value: GuidedEvaluationPreparation) {
    setRuns(current => [value.evaluation as Run, ...current.filter(item => item.run_id !== value.evaluation.run_id)]);
    setSuites(current => [value.suite, ...current.filter(item => item.id !== value.suite.id)]);
    setSelectedId(value.evaluation.run_id); setPool(String(value.launch.pool)); setBudget(value.launch.budget_policy_id); setMaxTokens(String(value.launch.max_tokens)); setSetup(false);
  }
  function queued(value: GuidedEvaluationRun) { setRuns(current => current.map(item => item.run_id === value.run_id ? value as Run : item)); setSelectedId(value.run_id); setRetry(value => value + 1); }
  useEffect(() => { const c = new AbortController(); setLoading(true); setError(null);
    Promise.all([allResources<Run>('/api/v1/evaluation-runs/', token, c.signal), allResources<RegisteredModel>('/api/v1/model-versions/', token, c.signal), allResources<Suite>('/api/v1/evaluation-suite-versions/', token, c.signal), allResources<Pool>('/api/v1/worker-pools/', token, c.signal), allResources<Budget>('/api/v1/budget-policies/', token, c.signal)])
      .then(([r, m, s, p, b]) => { if (!c.signal.aborted) { setRuns(r); setModels(m); setSuites(s); setPools(p.filter(v => v.status === 'active')); setBudgets(b.filter(v => v.enabled && v.unit === 'evaluation_cases')); const requested = evaluationSelection(window.location.hash).evaluationRun; setSelectedId(current => requested ? r.some(run => run.run_id === requested) ? requested : '' : r.some(run => run.run_id === current) ? current : r[0]?.run_id || ''); if (requested && !r.some(run => run.run_id === requested)) setError('This comparison is unavailable in the current project. Choose another evaluation or switch to its project.'); } }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, refreshKey, retry]);
  useEffect(() => { const c = new AbortController(); setCases([]); setNext(null); setCasesLoading(false); if (!selectedId) return () => c.abort(); setCasesLoading(true);
    apiPage<Case>(`/api/v1/evaluation-runs/${selectedId}/cases/`, token, c.signal).then(p => { if (!c.signal.aborted) { setCases(p.results); setNext(p.next || null); } }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setCasesLoading(false); }); return () => c.abort();
  }, [selectedId, token, refreshKey, retry]);
  useEffect(() => {
    if (!runs.some(r => r.job && ['pending', 'running'].includes(r.status))) return;
    const timer = window.setInterval(() => setRetry(v => v + 1), 3000);
    return () => window.clearInterval(timer);
  }, [runs]);
  async function create(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { const r = await apiRequest<Run>('/api/v1/evaluation-runs/', token, { method: 'POST', body: JSON.stringify({ suite_version: Number(suite), candidate_model_version: Number(candidate), baseline_model_version: baseline ? Number(baseline) : null }) }); setRuns(current => [r, ...current]); setSelectedId(r.run_id); setSetup(false); setNotice(`Evaluation configuration created: ${r.status}.`); }
    catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function registerSuite(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const parsed = recordsInput(suiteCases, evaluationFields, 64, 'case_id');
      const version = await apiRequest<Suite>('/api/v1/evaluation-suites/register-cpu/', token, { method: 'POST', body: JSON.stringify({ name: suiteName.trim(), protected_role: 'protected_eval', scorer_type: suiteScorer, cases: parsed, ...(suiteTarget ? { suite: Number(suiteTarget) } : {}) }) });
      setSuites(current => [version, ...current.filter(item => item.id !== version.id)]); setSuite(String(version.id)); setShowSuiteForm(false); if (!route.trainingRun) setSetup(true); const groupCount = version.source_group_count;
      const groupLabel = groupCount == null ? 'unreported source groups' : `${groupCount} source ${groupCount === 1 ? 'group' : 'groups'}`;
      setNotice(`Suite r${version.revision_no} pinned as protected evaluation with ${groupLabel}.`);
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function executeSelected() {
    if (!selected) return; setBusy(true); setError(null);
    try {
      const updated = await apiRequest<Run>(`/api/v1/evaluation-runs/${selected.run_id}/execute/`, token, { method: 'POST', body: JSON.stringify({ max_tokens: Number(maxTokens), pool: Number(pool), budget_policy_id: budget }) });
      setRuns(current => current.map(r => r.run_id === updated.run_id ? updated : r)); setRetry(v => v + 1); setNotice(updated.execution_evidence?.level === 'fixture' ? 'Demo evaluation completed with fictional Storybook results.' : `CPU evaluation queued. Open the run for worker progress and cancellation.`);
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function loadMore() { if (!next) return; setBusy(true); setError(null); try { const p = await apiPage<Case>(nextPagePath(next, `/api/v1/evaluation-runs/${selectedId}/cases/`), token); setCases(current => [...current, ...p.results]); setNext(p.next || null); } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  const suiteFamilies = [...suites.reduce((map, item) => { if (item.suite == null) return map; const current = map.get(item.suite); if (!current || item.revision_no > current.revision_no) map.set(item.suite, item); return map; }, new Map<number, Suite>()).values()];
  const selectedSuite = suites.find(s => s.id === selected?.suite_version);
  const pins = selected?.protocol_ref?.pins;
  const environment = pins?.environment;
  const overlap = pins?.training_overlap === 'known_lineage_checked' ? 'Known training lineage checked' : pins?.training_overlap === 'external_training_history_unknown' ? 'External training history unknown' : 'Not reported';
  const coverage = selected?.case_coverage;
  const recordedCases = coverage?.completed ?? selected?.protocol_ref?.completed_cases;
  const totalCases = coverage?.total ?? selected?.protocol_ref?.total_cases ?? selectedSuite?.cases_count;
  const missingCases = coverage?.missing ?? (typeof recordedCases === 'number' && typeof totalCases === 'number' ? Math.max(0, totalCases - recordedCases) : null);
  const loadedPassing = cases.filter(c => c.passed).length;
  const sliceCases = [...new Set(cases.map(c => c.slice_name || 'All samples'))].map(slice => ({ label: slice, value: cases.filter(c => (c.slice_name || 'All samples') === slice).length, color: 0 }));
  const canQueue = !!selected && selected.status === 'pending' && !selected.job && !route.trainingRun && !selected.decision_report?.training_run_id;
  const modelOptions = models.map(m => ({ value: String(m.id), id: m.model_version_id, name: m.model_name, revision: m.revision_no, state: m.state, href: resourceHash('model-version', m.model_version_id), description: m.capabilities?.evaluate.reason, unavailable: m.capabilities?.evaluate.eligible === false ? m.capabilities.evaluate.reason || 'Evaluation unavailable.' : undefined }));

  const handoffError = useResourceHandoff(token, (kind, value) => { if (kind === 'model-version') { setCandidate(String(value.id)); setSetup(true); } });
  return <div className="ml-page">
    <Section title="Comparison" description="Review the same held-out cases for your candidate and its starting model." actions={<>
      <Select aria-label="Evaluation run to visualize" disabled={busy} value={selectedId} onChange={e => selectRun(e.target.value)}>
        <option value="">Select an evaluation</option>{runs.map(r => <option key={r.run_id} value={r.run_id}>{runLabel(r.run_id)} · {modelName(r.candidate_model_version)} · {statusLabel(r.status)}</option>)}
      </Select>
      <Button type="button" variant="primary" disabled={loading || busy} onClick={() => setSetup(true)}>New evaluation</Button>
      <Button type="button" disabled={loading || busy || !token.trim()} onClick={() => setShowSuiteForm(true)}>Register evaluation suite</Button>
    </>}>
      {route.trainingRun && <GuidedEvaluation key={`${token}-${route.trainingRun}-${route.suiteVersion}`} token={token} trainingRun={route.trainingRun} currentRun={selected} suites={suites} suiteVersion={route.suiteVersion} suitesLoading={loading} onPrepared={prepared} onQueued={queued} />}
      {!route.trainingRun && selected?.status === 'pending' && !selected.job && selected.decision_report?.training_run_id && <p><LinkButton variant="primary" href={`#evaluation?training_run=${encodeURIComponent(selected.decision_report.training_run_id)}${selectedSuite ? `&suite_version=${encodeURIComponent(selectedSuite.suite_version_id)}` : ''}`}>Review and run this comparison</LinkButton></p>}
      {selected?.decision_report && <ImprovementReport report={selected.decision_report} runId={selected.run_id} candidateName={selected.candidate_name || modelName(selected.candidate_model_version)} baselineName={selected.baseline_name || modelName(selected.baseline_model_version)} />}
      {selected && <ImprovementDecision key={selected.run_id} token={token} run={selected.run_id} decision={selected.improvement_decision} eligible={selected.status === 'completed' && !!selected.job && !!selected.baseline_model_version && selected.baseline_model_version !== selected.candidate_model_version && selected.execution_evidence?.level === 'integrated_execution'} onRecorded={decision => setRuns(current => current.map(item => item.run_id === selected.run_id ? { ...item, improvement_decision: decision } : item))} />}
      {selected?.decision_report?.export_available && selected.decision_report.training_run_id && <ReviewedModelExport key={selected.run_id} token={token} trainingRun={selected.decision_report.training_run_id} candidate={selected.candidate_model_version} decision={selected.improvement_decision} evaluationRun={selected.run_id} />}
      {handoffError && <p role="alert" className="error-text">{handoffError}</p>}
      <ResourceState loading={loading && !runs.length} error={error} onRetry={() => setRetry(v => v + 1)} />
      {notice && <Notice tone="success" role="status">{notice}</Notice>}
      {!loading && !error && !runs.length && <EmptyState title="No evaluation runs yet" description="Create an evaluation to compare a candidate on held-out cases." />}
      {selected && <div className="ml-run">
        <div className="ml-run-head"><h3>{runLabel(selected.run_id)}</h3><StatusBadge status={selected.status} /><LinkButton size="sm" href={runHash('evaluation', selected.run_id)}>Open run</LinkButton><Button type="button" variant="quiet" size="sm" disabled={busy} onClick={() => selectRun('')}>Close details</Button></div>
        <KeyValueList columns={2} items={[
          { label: 'Candidate model', value: modelName(selected.candidate_model_version) },
          { label: 'Baseline model', value: modelName(selected.baseline_model_version) },
          { label: 'Evaluation suite', value: selectedSuite ? `${selectedSuite.suite_name} · r${selectedSuite.revision_no}` : 'Suite unavailable' },
          { label: 'Scorer', value: selectedSuite?.scorer_type || 'Not reported' },
          { label: 'Evidence', value: `${selected.execution_evidence?.level || 'Unknown'} · ${selected.execution_evidence?.source || 'No execution source reported'}` },
          { label: 'Cases', value: `${recordedCases ?? 'Not reported'} recorded${typeof totalCases === 'number' ? ` of ${totalCases}` : ''} · missing ${missingCases ?? 'not reported'} · failed ${coverage?.failed ?? 'not reported'}` },
          { label: 'Created', value: new Date(selected.created_at).toLocaleString() },
        ]} />
        {canQueue && <form data-ui="form" onSubmit={e => { e.preventDefault(); void executeSelected(); }}>
          <div data-ui="field-grid">
            <TextControl label="Maximum generated tokens" required type="number" min="1" max="32" value={maxTokens} onChange={e => setMaxTokens(e.target.value)} />
            <Select label="Evaluation worker pool" required value={pool} onChange={e => setPool(e.target.value)}><option value="">Select an active pool</option>{pools.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
            <Select label="Evaluation case budget" required value={budget} onChange={e => setBudget(e.target.value)}><option value="">Select an enabled case policy</option>{budgets.map(b => <option key={b.policy_id} value={b.policy_id}>{b.name} · {b.allowance?.remaining_amount ?? 'Unknown'} cases remaining</option>)}</Select>
          </div>
          <div data-ui="actions"><Button variant="primary" disabled={busy || !pool || !budget || !token.trim() || !Number.isInteger(Number(maxTokens)) || Number(maxTokens) < 1 || Number(maxTokens) > 32}>{busy ? 'Queueing…' : 'Queue CPU evaluation'}</Button><span className="muted">Reserves one unit per suite case and settles recorded cases only.</span></div>
        </form>}
        {selected.comparison && !selected.comparison.compatible && <p className="muted">{selected.comparison.reason}</p>}
        <h4>Metrics by slice</h4>
        <MetricComparison metrics={selected.metrics} baseline={selected.comparison?.compatible ? selected.baseline_metrics : []} candidateName={modelName(selected.candidate_model_version)} baselineName={modelName(selected.baseline_model_version)} />
        <h4>Case results</h4>
        <Checkbox label="Show failures only in loaded cases" checked={failuresOnly} onChange={e => setFailuresOnly(e.target.checked)} />
        <ResourceState loading={casesLoading} />
        <div className="ml-cases">{cases.filter(c => !failuresOnly || !c.passed).map(c => <EvaluationCase key={c.result_id} result={c} />)}</div>
        {!casesLoading && !cases.length && <p className="muted">No case results recorded.</p>}
        {next && <div data-ui="actions"><Button type="button" disabled={busy} onClick={() => void loadMore()}>Load more case results</Button></div>}
        <Disclosure summary="Evidence" variant="quiet"><KeyValueList columns={2} items={[
          { label: 'Scorer version', value: pins?.scorer_version || 'Not reported' },
          { label: 'Protected role', value: selectedSuite?.protected_role === 'protected_eval' ? 'Protected evaluation' : (selectedSuite?.protected_role || 'Not reported') },
          { label: 'Source groups', value: selectedSuite?.source_group_count == null ? 'Not reported' : selectedSuite.source_group_count },
          { label: 'Run environment', value: environment ? `${environment.device || 'device not reported'} · ${environment.prompt_format || 'template not reported'} · ${environment.decoding || 'decoding not reported'}` : 'Not reported' },
          { label: 'Training overlap', value: overlap },
          { label: 'Qualification', value: 'Production qualification unavailable' },
          { label: 'Suite version ID', value: <Identifier value={selectedSuite?.suite_version_id || selected.suite_version} label="Evaluation suite version ID" display="code" /> },
          { label: 'Run ID', value: <Identifier value={selected.run_id} label="Run ID" display="code" /> },
        ]} /></Disclosure>
        <Disclosure summary="Insights" variant="quiet"><div className="ml-charts">
          <MetricsChart key={selected.run_id} metrics={selected.metrics} />
          <ChartPanel title="Loaded case outcomes" description={`${cases.length} loaded case results. More pages may change these totals.`}>{cases.length > 0 ? <SegmentBar data={[{ label: 'Passed', value: loadedPassing, color: 1 }, { label: 'Failed', value: cases.length - loadedPassing, color: 3 }]} unit="cases" /> : <ChartEmpty message="The selected run has no loaded case results." />}</ChartPanel>
          <ChartPanel title="Loaded case coverage" description="Case count by slice in the loaded results, not the full suite."><BarChart data={sliceCases} unit="Loaded cases" emptyMessage="Load case results to inspect slice coverage." /></ChartPanel>
        </div></Disclosure>
      </div>}
    </Section>
    <Section title="History" description="Each run keeps its own suite, candidate and evidence.">
      {!!runs.length && <div className="table-scroll" tabIndex={0}><RecordTable>
        <thead><tr><th>Run</th><th>Candidate</th><th>Baseline</th><th>Suite</th><th>State</th></tr></thead>
        <tbody>{runs.map(r => <tr key={r.run_id} aria-selected={r.run_id === selectedId || undefined}>
          <td><a href={runHash('evaluation', r.run_id)}>{runLabel(r.run_id)}</a><div className="ops-row-actions"><Button type="button" variant="quiet" size="sm" disabled={busy} onClick={() => selectRun(r.run_id)}>Inline details</Button></div></td>
          <td>{modelName(r.candidate_model_version)}</td><td>{modelName(r.baseline_model_version)}</td>
          <td>{suites.find(s => s.id === r.suite_version)?.suite_name || 'Suite unavailable'}</td>
          <td><StatusBadge status={r.status} /><small title={r.execution_evidence?.source}>{r.execution_evidence?.level || 'unknown evidence'}</small></td>
        </tr>)}</tbody>
      </RecordTable></div>}
      {!loading && !error && !runs.length && <p className="muted">No evaluation runs yet.</p>}
    </Section>
    <Dialog title="New evaluation" description="Compare a candidate on a pinned held-out suite, with an optional baseline." open={setup} onClose={() => setSetup(false)} size="lg"
      footer={<><Button type="button" disabled={busy} onClick={() => setSetup(false)}>Cancel</Button><Button form={setupFormId} type="submit" variant="primary" disabled={busy || !suite || !candidate}>Create evaluation configuration</Button></>}>
      <form id={setupFormId} data-ui="form" onSubmit={create}>
        <DraftIndicator draft={draft} disabled={busy} />
        <Select label="Evaluation suite version" required value={suite} onChange={e => setSuite(e.target.value)}>
          <option value="">Select a suite</option>{suites.map(s => <option key={s.id} value={s.id}>{s.suite_name} · r{s.revision_no} · {s.cases_count} cases · {s.protected_role === 'protected_eval' ? 'protected evaluation' : (s.protected_role || 'role not declared')} · {s.source_group_count == null ? 'source groups not declared' : `${s.source_group_count} source groups`}</option>)}
        </Select>
        <ResourcePicker label="Candidate model" loading={loading} required disabled={busy} value={candidate} onChange={setCandidate} options={modelOptions} />
        <ResourcePicker label="Baseline model (optional)" loading={loading} disabled={busy} value={baseline} onChange={setBaseline} placeholder="No baseline" options={modelOptions} />
        <p className="muted">Creates a pending evaluation. Queue it on a CPU worker from verified candidate and baseline bytes.</p>
        {!suites.length && <p className="muted">Register an evaluation suite first to pin the cases.</p>}
      </form>
    </Dialog>
    <Dialog title="Register evaluation suite" description="Pin held-out cases as a protected suite version." open={showSuiteForm} onClose={() => setShowSuiteForm(false)} size="lg"
      footer={<><Button type="button" disabled={busy} onClick={() => setShowSuiteForm(false)}>Cancel</Button><Button form={suiteFormId} type="submit" variant="primary" disabled={busy || !suiteName.trim()}>{busy ? 'Registering…' : suiteTarget ? 'Pin next suite version' : 'Pin evaluation suite'}</Button></>}>
      <form id={suiteFormId} data-ui="form" onSubmit={registerSuite}>
        <DraftIndicator draft={draft} disabled={busy} />
        <div data-ui="field-grid">
          <Select label="Suite version" value={suiteTarget} onChange={e => { const value = e.target.value; setSuiteTarget(value); const chosen = suiteFamilies.find(item => String(item.suite) === value); if (chosen) setSuiteName(chosen.suite_name); }}>
            <option value="">New suite</option>{suiteFamilies.map(item => <option key={item.suite} value={item.suite}>{item.suite_name} · current r{item.revision_no}</option>)}
          </Select>
          <TextControl label="Suite name" required maxLength={200} readOnly={Boolean(suiteTarget)} value={suiteName} onChange={e => setSuiteName(e.target.value)} />
          <Select label="Protected evaluation role" required value="protected_eval" onChange={() => undefined} options={[{ value: 'protected_eval', label: 'Protected evaluation — held out from training' }]} />
          <Select label="Scoring method" value={suiteScorer} onChange={e => setSuiteScorer(e.target.value)} options={[{ value: 'exact_match', label: 'Exact match' }, { value: 'substring', label: 'Expected text appears in output' }, { value: 'numeric_tolerance', label: 'Numeric tolerance (0.0001)' }]} />
        </div>
        <RecordListEditor title="Evaluation cases" itemName="Case" fields={evaluationFields} maximum={64} uniqueKey="case_id" value={suiteCases} onChange={setSuiteCases} disabled={busy} description="Write the prompt, expected response and source group for each case. IDs must be unique; slices group related cases." />
        <p className="muted">Pin 1–64 held-out cases. A new version keeps the protected role and does not rewrite earlier revisions.</p>
      </form>
    </Dialog>
  </div>;
}
