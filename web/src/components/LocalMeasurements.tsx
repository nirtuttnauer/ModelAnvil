import { useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Notice } from './ui';

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
  return <details className="detail-box" onToggle={e => { if (e.currentTarget.open && !report && !busy) void load(); }}>
    <summary>Local workflow measurements</summary>
    <p>Interaction timing and recorded decisions stay in this installation. Measurement records contain no prompts, uploaded content or credentials. External analytics are disabled.</p>
    {busy && <p role="status">Loading local measurements…</p>}
    {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
    {report && <dl>
      <dt>Week beginning (UTC)</dt><dd>{report.week_start.slice(0, 10)}</dd>
      <dt>Completed improvement decisions</dt><dd>{report.weekly_improvement_cycles}</dd>
      <dt>Accepted candidates with higher measured accuracy</dt><dd>{report.weekly_accepted_improvements}</dd>
      <dt>Rejected candidates</dt><dd>{report.weekly_rejected_candidates}</dd>
      <dt>Reported interaction time this week</dt><dd>{report.reported_active_seconds.toFixed(1)} seconds</dd>
      <dt>First workspace visit to first decision</dt><dd>{report.time_to_first_decision_seconds === null ? 'Not yet measured' : `${report.time_to_first_decision_seconds.toFixed(1)} seconds`}</dd>
    </dl>}
    <p className="muted">Only complete, verified candidate and baseline comparisons count. Interaction timing is approximate and excludes idle or hidden windows. Queue and workload times are recorded separately.</p>
    <Button disabled={busy} onClick={() => void load()}>{error ? 'Retry local measurements' : 'Refresh local measurements'}</Button>
  </details>;
}
