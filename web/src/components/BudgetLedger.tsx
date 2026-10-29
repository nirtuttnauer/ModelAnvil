import { Identifier } from './Identifier';
import { Button, Disclosure, RecordTable, StatusBadge } from './ui';
import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources } from '../api/resources';
import { runHash } from '../api/runs';
import { DataInspector } from './DataInspector';
interface Source { scope: string; kind?: string; run_id?: string; project_id?: string; actor_id?: string | null }
interface Usage { usage_id: string; quantity: string; unit: string; currency: string; amount: string | null; net_amount: string | null; occurred_at: string; source: Source; adjustments: unknown[]; reservation_id: string | null }
interface Reservation { reservation_id: string; job_id: string; policy_name: string; unit: string; currency: string; state: string; estimated_amount: string; settled_amount: string | null; period_start: string; source: Source }
interface Policy { policy_id: string; name: string; unit: string; currency: string; limit_amount: string; allowance?: { period_start: string; remaining_amount: string; reserved_amount: string; settled_amount: string } }
function sourceLink(source: Source) {
  return source.run_id ? source.kind === 'alignment' ? `#alignment?run=${source.run_id}` : runHash(source.kind === 'training' || source.kind === 'evaluation' ? source.kind : 'job', source.run_id) : null;
}

/** Committed usage, reservations and policy allowances for the selected scope, folded away by default. */
export function BudgetLedger({ token, query, refreshKey }: { token: string; query: string; refreshKey: number }) {
  const [usage, setUsage] = useState<Usage[]>([]), [reservations, setReservations] = useState<Reservation[]>([]), [policies, setPolicies] = useState<Policy[]>([]);
  const [error, setError] = useState(''), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [notice, setNotice] = useState('');
  const exportRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const c = new AbortController(); setError(''); setLoading(true);
    Promise.all([allResources<Usage>('/api/v1/usage-events/'+query, token, c.signal), allResources<Reservation>('/api/v1/budget-reservations/'+query, token, c.signal), allResources<Policy>('/api/v1/budget-policies/', token, c.signal)])
      .then(([u, r, p]) => { if (!c.signal.aborted) { setUsage(u); setReservations(r); setPolicies(p); } })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => { c.abort(); exportRequest.current?.abort(); };
  }, [token, query, refreshKey]);
  async function exportLedger() {
    const c = new AbortController(); exportRequest.current = c; setBusy(true); setNotice('');
    try {
      const report = await apiRequest<{ complete: boolean; event_count: number; reservation_count: number }>('/api/v1/usage-events/export/'+query, token, { signal: c.signal });
      if (c.signal.aborted) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = `modelanvil-ledger-${report.complete ? 'complete' : 'PARTIAL'}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(`${report.complete ? 'Complete' : 'Partial'} scoped export: ${report.event_count} events and ${report.reservation_count} reservations. Metadata declares filters, UTC dates and completeness.`);
    } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); } finally { if (!c.signal.aborted) setBusy(false); }
  }
  return <Disclosure summary="Reservations ledger" variant="card">
    <div data-ui="form">
      <div data-ui="actions"><Button type="button" disabled={busy || loading || !!error} onClick={() => void exportLedger()}>Export ledger</Button>{loading && <span role="status" className="muted">Loading all scoped ledger pages…</span>}</div>
      {error && <p role="alert" className="error-text">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!error && <>
        <h3>Policy allowances</h3>
        <p className="muted">Current-period allowances for the whole policy ledger, independent of the usage filters.</p>
        {policies.length > 0 && <ul className="ops-allowances">{policies.map(policy => <li key={policy.policy_id}><strong>{policy.name}</strong> · {policy.allowance?.remaining_amount ?? 'unknown'} {policy.unit} {policy.currency} remaining · period {policy.allowance?.period_start ?? 'unknown'}{policy.allowance && Number(policy.allowance.remaining_amount) <= Number(policy.limit_amount)*0.2 && <p role="alert">Policy {policy.name} has {Number(policy.allowance.remaining_amount) <= 0 ? 'no' : '20% or less'} allowance remaining. Refresh to check new reservations and settlements.</p>}</li>)}</ul>}
        <h3>Committed usage ({usage.length})</h3>
        <div className="table-scroll" tabIndex={0}><RecordTable><thead><tr><th>Time and execution</th><th>Quantity</th><th>Cost and corrections</th><th>Attribution</th></tr></thead><tbody>{usage.map(row => <tr key={row.usage_id}><td>{new Date(row.occurred_at).toLocaleString()}{sourceLink(row.source) ? <a href={sourceLink(row.source)!}>Open execution</a> : <small>Execution attribution unavailable</small>}</td><td>{row.quantity} {row.unit}</td><td>{row.net_amount ?? 'Unpriced'} {row.currency}<Disclosure summary="Original cost and adjustments" variant="quiet"><DataInspector value={{ amount: row.amount, adjustments: row.adjustments, reservation: row.reservation_id }} /></Disclosure></td><td>{row.source.scope}<small>{row.source.project_id ? <>Project <Identifier value={row.source.project_id} label="Project ID" /></> : 'No project attribution'}</small><small>Actor: {row.source.actor_id ? <Identifier value={row.source.actor_id} label="Actor ID" /> : 'Not recorded'}</small></td></tr>)}</tbody></RecordTable></div>
        <h3>Reservations ({reservations.length})</h3>
        <div className="table-scroll" tabIndex={0}><RecordTable><thead><tr><th>Policy and period</th><th>Estimated reservation</th><th>Committed usage</th><th>State and source</th></tr></thead><tbody>{reservations.map(row => <tr key={row.reservation_id}><td>{row.policy_name}<small>Period starts {row.period_start}</small></td><td>{row.estimated_amount} {row.unit} {row.currency}</td><td>{row.settled_amount ?? 'Not settled'}</td><td><StatusBadge status={row.state} />{sourceLink(row.source) && <small><a href={sourceLink(row.source)!}>Open execution</a></small>}<Disclosure summary="Reservation record" variant="quiet"><DataInspector value={row} /></Disclosure></td></tr>)}</tbody></RecordTable></div>
      </>}
    </div>
  </Disclosure>;
}
