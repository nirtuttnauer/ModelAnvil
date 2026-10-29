import { useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Notice } from './ui';

export interface Decision { outcome: 'accept' | 'reject'; decision_id: string }

export function ImprovementDecision({ token, run, decision, eligible, onRecorded }: {
  token: string; run: string; decision?: Decision | null; eligible: boolean; onRecorded?: (decision: Decision) => void;
}) {
  const [saved, setSaved] = useState<Decision | null>(decision || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const recorded = saved || decision;
  async function record(outcome: Decision['outcome']) {
    setBusy(true); setError('');
    try {
      const value = await apiRequest<Decision>(`/api/v1/evaluation-runs/${run}/record-decision/`, token,
        { method: 'POST', body: JSON.stringify({ outcome }) });
      setSaved(value); onRecorded?.(value);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <section aria-label="Improvement decision">
    <h3>Record your decision</h3>
    <p className="muted">After reviewing the comparison, record whether you accept or reject this candidate. This saves your choice locally and does not deploy the model. A new comparison is required to change a recorded decision.</p>
    {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
    {recorded ? <Notice as="p" role="status">Decision recorded: {recorded.outcome === 'accept' ? 'candidate accepted' : 'candidate rejected'}.</Notice>
      : <><div data-ui="actions"><Button disabled={busy || !eligible} onClick={() => void record('accept')}>{busy ? 'Recording…' : 'Record accept decision'}</Button><Button disabled={busy || !eligible} onClick={() => void record('reject')}>Record reject decision</Button></div>
        {!eligible && <p className="muted">Complete a durable comparison of a trained candidate and a distinct baseline to record a decision.</p>}</>}
  </section>;
}
