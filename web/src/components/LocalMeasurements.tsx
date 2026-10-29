import { useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Disclosure, KeyValueList, Notice } from './ui';

interface Report {
  week_start: string; weekly_improvement_cycles: number; weekly_accepted_improvements: number;
  weekly_rejected_candidates: number; reported_active_seconds: number;
  time_to_first_decision_seconds: number | null;
}

export function LocalMeasurements({ token }: { token: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load() {
    setBusy(true); setError('');
    try { setReport(await apiRequest<Report>('/api/v1/activation/report/', token)); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <Disclosure summary="Local workflow measurements" onToggle={e => { if (e.currentTarget.open && !report && !busy) void load(); }}>
    <p className="muted">Timing and decisions stay in this installation; no prompts, content or credentials are recorded.</p>
    {busy && <p role="status">Loading local measurements…</p>}
    {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
    {report && <KeyValueList items={[
      { label: 'Week beginning (UTC)', value: report.week_start.slice(0, 10) },
      { label: 'Completed improvement decisions', value: report.weekly_improvement_cycles },
      { label: 'Accepted candidates with higher measured accuracy', value: report.weekly_accepted_improvements },
      { label: 'Rejected candidates', value: report.weekly_rejected_candidates },
      { label: 'Reported interaction time this week', value: `${report.reported_active_seconds.toFixed(1)} seconds` },
      { label: 'First workspace visit to first decision', value: report.time_to_first_decision_seconds === null ? 'Not yet measured' : `${report.time_to_first_decision_seconds.toFixed(1)} seconds` },
    ]} />}
    <p className="muted">Only complete comparisons count; timing excludes idle windows.</p>
    <Button disabled={busy} onClick={() => void load()}>{error ? 'Retry local measurements' : 'Refresh local measurements'}</Button>
  </Disclosure>;
}
