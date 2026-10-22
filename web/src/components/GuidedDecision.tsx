import { useEffect, useState } from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ImprovementDecision, type Decision } from './ImprovementDecision';
import { Button, Field, Notice } from './ui';

interface ComparisonPreview {
  eligible: boolean;
  reason: string;
  setup_check: boolean;
  synthetic: boolean;
  held_out_count: number;
  held_out_preview: { case_id: string; input_prompt: string; expected_output: string }[];
  metric: string;
  existing_run_id: string | null;
  existing_status: string | null;
}

interface GuidedEvaluation {
  run_id: string;
  status: string;
  execution_evidence?: { level: string };
  improvement_decision?: Decision | null;
  metrics?: { key: string; value: number; sample_count: number; slice_name: string }[];
}

interface ComparisonCase {
  case_id: string;
  input_prompt: string;
  expected_output: string;
  candidate_output: string;
  baseline_output?: string | null;
  passed: boolean;
  failure_reason: string;
}

interface Question { input_prompt: string; expected_output: string }

export function GuidedDecision({ token, runId }: { token: string; runId: string }) {
  const [preview, setPreview] = useState<ComparisonPreview | null>(null);
  const [evaluation, setEvaluation] = useState<GuidedEvaluation | null>(null);
  const [cases, setCases] = useState<ComparisonCase[]>([]);
  const [questions, setQuestions] = useState<Question[]>([{ input_prompt: '', expected_output: '' }]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setPreview(null); setError('');
    apiRequest<ComparisonPreview>(`/api/v1/training-runs/${runId}/comparison/`, token, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setPreview(value); })
      .catch(reason => { if (!controller.signal.aborted) setError(errorMessage(reason)); });
    return () => controller.abort();
  }, [runId, token]);

  const activeStatuses = ['pending', 'running', 'completed'];
  const evaluationId = evaluation && activeStatuses.includes(evaluation.status) ? evaluation.run_id
    : preview?.existing_run_id && preview.existing_status && activeStatuses.includes(preview.existing_status) ? preview.existing_run_id : '';
  useEffect(() => {
    if (!evaluationId) return;
    const controller = new AbortController();
    let timer = 0;
    async function poll() {
      try {
        const current = await apiRequest<GuidedEvaluation>(`/api/v1/evaluation-runs/${evaluationId}/`, token, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setEvaluation(current);
        if (current.status === 'completed') {
          const page = await apiPage<ComparisonCase>(`/api/v1/evaluation-runs/${evaluationId}/cases/`, token, controller.signal);
          if (!controller.signal.aborted) setCases(page.results);
          return;
        }
        if (current.status === 'failed' || current.status === 'cancelled') return;
        timer = window.setTimeout(() => void poll(), 2000);
      } catch (reason) {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      }
    }
    void poll();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [evaluationId, token]);

  async function compare() {
    if (!confirmed || busy) return;
    const supplied = preview && preview.held_out_count === 0 ? questions.map(question => ({
      input_prompt: question.input_prompt.trim(), expected_output: question.expected_output.trim(),
    })).filter(question => question.input_prompt || question.expected_output) : undefined;
    if (supplied && (supplied.length < 1 || supplied.length > 8 || supplied.some(question => !question.input_prompt || !question.expected_output))) {
      setError('Enter 1–8 questions, each with the answer you expect.');
      return;
    }
    setBusy(true); setError('');
    try {
      const created = await apiRequest<GuidedEvaluation>(`/api/v1/training-runs/${runId}/comparison/`, token, {
        method: 'POST', body: JSON.stringify({ confirm: true, max_tokens: 32, ...(supplied ? { questions: supplied } : {}) }),
      });
      setEvaluation(created); setCases([]);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setBusy(false); }
  }

  const failures = cases.filter(row => !row.passed);
  const waiting = evaluation && ['pending', 'running'].includes(evaluation.status);
  const eligibleDecision = evaluation?.status === 'completed' && evaluation.execution_evidence?.level === 'integrated_execution';
  return <section className="detail-box" aria-label="Compare and decide">
    <h3>Compare this candidate with the base model</h3>
    <p>{preview?.metric || 'Accuracy is the share of cases whose answer matches the expected answer. Recording a choice does not deploy the model.'}</p>
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    {!preview && !error && <p role="status">Checking whether this candidate can be compared…</p>}
    {preview && !preview.eligible && <Notice role="status">{preview.reason}</Notice>}
    {preview?.eligible && !evaluationId && <div className="guided-form">
      {preview.held_out_count > 0 ? <>
        <p>{preview.held_out_count} held-out {preview.held_out_count === 1 ? 'question' : 'questions'} from this dataset will be scored. These examples were not used for training.</p>
        <ul>{preview.held_out_preview.map(row => <li key={row.case_id}><strong>{row.input_prompt}</strong><br />Expected: {row.expected_output}</li>)}</ul>
      </> : <>
        <p>This dataset has no held-out questions. Confirm a short list and the answers you expect.</p>
        {questions.map((question, index) => <div key={index}>
          <label>Question {index + 1}<Field value={question.input_prompt} maxLength={1024} disabled={busy} onChange={event => setQuestions(current => current.map((item, itemIndex) => itemIndex === index ? { ...item, input_prompt: event.target.value } : item))} /></label>
          <label>Expected answer<Field value={question.expected_output} maxLength={4096} disabled={busy} onChange={event => setQuestions(current => current.map((item, itemIndex) => itemIndex === index ? { ...item, expected_output: event.target.value } : item))} /></label>
        </div>)}
        <Button type="button" disabled={busy || questions.length >= 8} onClick={() => setQuestions(current => [...current, { input_prompt: '', expected_output: '' }])}>Add a question</Button>
      </>}
      <label className="data-license-consent"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} /><span>I confirm these questions are the comparison to record.</span></label>
      <Button type="button" className="primary" disabled={busy || !confirmed} onClick={() => void compare()}>{busy ? 'Starting comparison…' : 'Compare with the base model'}</Button>
    </div>}
    {waiting && <p role="status">Comparison is {evaluation?.status}. This page updates until both models have answered.</p>}
    {evaluation?.status === 'failed' && <Notice tone="error" role="alert">The comparison did not finish. Confirm the questions and compare again.</Notice>}
    {!!cases.length && <>
      <h4>Paired answers</h4>
      {!!failures.length && <p role="status">{failures.length} of {cases.length} cases did not match the expected answer.</p>}
      <div className="table-scroll" tabIndex={0}><table className="resource-table"><caption>Candidate and base answers for the confirmed questions.</caption><thead><tr><th>Question</th><th>Expected</th><th>Candidate</th><th>Base model</th><th>Result</th></tr></thead><tbody>
        {cases.map(row => <tr key={row.case_id}><td>{row.input_prompt}</td><td>{row.expected_output}</td><td>{row.candidate_output}</td><td>{row.baseline_output || 'Not recorded'}</td><td>{row.passed ? 'Match' : row.failure_reason || 'Miss'}</td></tr>)}
      </tbody></table></div>
    </>}
    {evaluation && <ImprovementDecision token={token} run={evaluation.run_id} decision={evaluation.improvement_decision} eligible={!!eligibleDecision} />}
  </section>;
}
