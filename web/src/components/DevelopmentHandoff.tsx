import { useEffect, useState } from 'react';
import { Button, Field, MultilineField, Notice } from './ui';

export interface FailedCase { case_id: string; input_prompt: string; candidate_output: string; expected_output: string; passed: boolean }

export function DevelopmentHandoff({ cases, busy, onSubmit }: {
  cases: FailedCase[];
  busy: boolean;
  onSubmit: (corrections: { case_id: string; corrected_output: string }[], datasetName: string) => void;
}) {
  const failed = cases.filter(item => !item.passed);
  const [name, setName] = useState('Development corrections');
  const [answers, setAnswers] = useState<Record<string, string>>({});
  useEffect(() => {
    setAnswers(current => {
      const next = { ...current };
      for (const item of failed) if (next[item.case_id] === undefined) next[item.case_id] = item.expected_output;
      return next;
    });
  }, [cases]);
  if (!failed.length) return null;
  return <form className="form-grid" onSubmit={event => {
    event.preventDefault();
    onSubmit(failed.map(item => ({ case_id: item.case_id, corrected_output: answers[item.case_id] || '' })), name.trim());
  }}>
    <h4>Correct failed development cases</h4>
    <p className="muted full-width">These corrections become a new training dataset. They cannot be declared a protected final test. The current candidate stays active.</p>
    <label>Dataset name<Field required maxLength={200} value={name} onChange={event => setName(event.target.value)} disabled={busy} /></label>
    {failed.map(item => <label key={item.case_id}>Correction for {item.case_id}
      <MultilineField required value={answers[item.case_id] || ''} disabled={busy} onChange={event => setAnswers(current => ({ ...current, [item.case_id]: event.target.value }))} />
      <small>Prompt: {item.input_prompt}</small>
    </label>)}
    <Button className="primary" disabled={busy || !name.trim()}>Save corrections for the next training run</Button>
    <Notice as="p">This does not deploy a model.</Notice>
  </form>;
}
