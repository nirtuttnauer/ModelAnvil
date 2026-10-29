import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { runHash } from '../api/runs';
import { Button, Notice } from './ui';

export interface GuidedEvaluationRun {
  run_id: string; status: string; candidate_model_version: number; baseline_model_version: number | null;
  candidate_name?: string; baseline_name?: string; suite_version: number; job?: string | null;
}
export interface GuidedEvaluationPreparation {
  evaluation: GuidedEvaluationRun;
  suite: { id: number; suite_version_id: string; suite_name: string; revision_no: number; cases_count: number; scorer_type: string; protected_role: string };
  launch: { pool: number; budget_policy_id: string; max_tokens: number; profile: string };
  warnings: string[]; labels: string[];
  cases: { case_id: string; input_prompt: string; expected_output: string; source_group_id: string }[];
}

export function GuidedEvaluation({ token, trainingRun, currentRun, suites = [], suiteVersion = '', suitesLoading = false, onPrepared, onQueued }: {
  token: string; trainingRun: string;
  suites?: GuidedEvaluationPreparation['suite'][]; suiteVersion?: string; suitesLoading?: boolean;
  currentRun?: GuidedEvaluationRun | null;
  onPrepared: (value: GuidedEvaluationPreparation) => void;
  onQueued: (value: GuidedEvaluationRun) => void;
}) {
  const [prepared, setPrepared] = useState<GuidedEvaluationPreparation | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const evaluation = currentRun?.run_id === prepared?.evaluation.run_id ? currentRun : prepared?.evaluation;
  const protectedSuites = suites.filter(suite => suite.protected_role === 'protected_eval' && suite.scorer_type === 'exact_match' && suite.cases_count > 0 && suite.cases_count <= 64);
  const missingSuite = !!suiteVersion && !protectedSuites.some(suite => suite.suite_version_id === suiteVersion);
  function chooseSuite(value: string) {
    const query = new URLSearchParams(window.location.hash.split('?')[1]);
    if (value) query.set('suite_version', value); else query.delete('suite_version');
    window.location.hash = `evaluation?${query}`;
  }
  useEffect(() => () => request.current?.abort(), []);
  async function prepare() {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError('');
    try {
      const value = await apiRequest<GuidedEvaluationPreparation>(`/api/v1/training-runs/${trainingRun}/prepare-evaluation/`, token,
        { method: 'POST', body: JSON.stringify(suiteVersion ? { suite_version: suiteVersion } : {}), signal: controller.signal });
      if (controller.signal.aborted) return;
      setPrepared(value); onPrepared(value);
    } catch (failure) { if (!controller.signal.aborted) setError(errorMessage(failure)); }
    finally { if (!controller.signal.aborted) { setBusy(false); request.current = null; } }
  }
  async function queue() {
    if (!prepared || request.current) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError('');
    try {
      const value = await apiRequest<GuidedEvaluationRun>(`/api/v1/evaluation-runs/${prepared.evaluation.run_id}/execute/`, token,
        { method: 'POST', body: JSON.stringify(prepared.launch), signal: controller.signal });
      if (controller.signal.aborted) return;
      setPrepared({ ...prepared, evaluation: value }); onQueued(value);
    } catch (failure) { if (!controller.signal.aborted) setError(errorMessage(failure)); }
    finally { if (!controller.signal.aborted) { setBusy(false); request.current = null; } }
  }
  return <section className="guided-evaluation" aria-labelledby="guided-evaluation-title" aria-busy={busy}>
    <div><h3 id="guided-evaluation-title">Evaluate against the starting model</h3>
      <p>Use the exact selected checkpoint, its base model and protected classification examples. Both models use the same native chat template and decoding settings.</p></div>
    {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
    {!prepared ? <><p className="muted">Prepare the comparison to inspect its cases and local execution settings before any evaluation starts.</p>
      <label>Protected comparison examples<select value={suiteVersion} disabled={busy || suitesLoading} onChange={event => chooseSuite(event.target.value)}>
        <option value="">Test split from this training dataset</option>
        {missingSuite && <option value={suiteVersion} disabled>Saved suite unavailable</option>}
        {protectedSuites.map(suite => <option key={suite.suite_version_id} value={suite.suite_version_id}>{suite.suite_name} · r{suite.revision_no} · {suite.cases_count} cases</option>)}
      </select></label>
      <p className="muted">Use the dataset’s held-out test split, or select a protected exact-label suite with 1–64 cases. Register a suite above if your dataset has no usable test split.</p>
      {missingSuite && !suitesLoading && <Notice as="p" tone="error" role="alert">The saved suite is unavailable or incompatible. Choose a protected exact-label suite.</Notice>}
      <Button variant="primary" type="button" disabled={busy || suitesLoading || missingSuite} onClick={() => void prepare()}>{busy ? 'Preparing comparison…' : error ? 'Retry preparation' : 'Prepare comparison'}</Button></> : <>
      <dl className="guided-review"><div><dt>Candidate</dt><dd>{prepared.evaluation.candidate_name || 'Selected trained checkpoint'}</dd></div>
        <div><dt>Baseline</dt><dd>{prepared.evaluation.baseline_name || 'Pinned starting model'}</dd></div>
        <div><dt>Protected cases</dt><dd>{prepared.suite.cases_count} · {prepared.suite.suite_name} · r{prepared.suite.revision_no}</dd></div>
        <div><dt>Scoring</dt><dd>Exact classification label · up to {prepared.launch.max_tokens} output tokens</dd></div></dl>
      {prepared.warnings.map(warning => <Notice as="p" key={warning}>{warning}</Notice>)}
      <details><summary>Inspect held-out cases and labels</summary><p>Allowed labels: {prepared.labels.join(', ') || 'Not reported'}. Keep these source groups out of training.</p>
        {prepared.cases.map(item => <div className="evaluation-preview-case" key={item.case_id}><strong>{item.case_id}</strong><p>{item.input_prompt}</p><p>Expected label: <strong>{item.expected_output}</strong></p></div>)}</details>
      {!evaluation?.job && evaluation?.status === 'pending' ? <div data-ui="actions"><Button variant="primary" type="button" disabled={busy} onClick={() => void queue()}>{busy ? 'Queueing comparison…' : 'Run comparison'}</Button><p className="muted">Uses managed local compute and an evaluation case allowance. No manual worker setup is needed.</p></div>
        : <p role="status">Comparison {evaluation?.status}. <a href={runHash('evaluation', prepared.evaluation.run_id)}>Open evaluation progress</a></p>}
    </>}
  </section>;
}
