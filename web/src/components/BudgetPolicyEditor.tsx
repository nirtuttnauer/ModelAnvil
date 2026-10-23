import { Button, Card, Field, RecordTable } from './ui';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources } from '../api/resources';

interface Policy {
  policy_id: string; name: string; period: string; unit: string; currency: string; limit_amount: string; enabled: boolean;
  allowance?: { scope: string; period_start: string; reserved_amount: string; settled_amount: string; remaining_amount: string };
}

export function BudgetPolicyEditor({ token, refreshKey, onChanged }: { token: string; refreshKey: number; onChanged: () => void }) {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [allowed, setAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Policy | null>(null);
  const [name, setName] = useState('');
  const [unit, setUnit] = useState('training_steps');
  const [period, setPeriod] = useState('lifetime');
  const [limit, setLimit] = useState('100');
  const [enabled, setEnabled] = useState(true);
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError('');
    Promise.all([allResources<Policy>('/api/v1/budget-policies/', token, c.signal),
      apiRequest<{ can_administer: boolean }>('/api/v1/budget-policies/permissions/', token, { signal: c.signal })])
      .then(([rows, access]) => { if (!c.signal.aborted) { setPolicies(rows); setAllowed(access.can_administer); } })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, refreshKey]);
  useEffect(() => { setOpen(false); setEditing(null); setNotice(''); }, [token]);
  function edit(policy: Policy | null) {
    setEditing(policy); setName(policy?.name || ''); setUnit(policy?.unit || 'training_steps');
    setPeriod(policy?.period || 'lifetime'); setLimit(policy?.limit_amount || '100'); setEnabled(policy?.enabled ?? true); setOpen(true); setError('');
  }
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const saved = await apiRequest<Policy>(editing ? `/api/v1/budget-policies/${editing.policy_id}/` : '/api/v1/budget-policies/', token,
        { method: editing ? 'PATCH' : 'POST', body: JSON.stringify({ name: name.trim(), period, unit, currency: editing?.currency || '', limit_amount: limit, enabled }) });
      setPolicies(rows => editing ? rows.map(p => p.policy_id === saved.policy_id ? saved : p) : [saved, ...rows]);
      setOpen(false); setNotice(`Budget policy “${saved.name}” saved.`); onChanged();
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <Card className="panel" aria-label="Budget policy management">
    <div className="panel-title"><div><h2>Budget policies</h2><p>Organization-wide limits shared across projects. Reservations and usage use the policy’s resource unit.</p></div>
      {allowed && <Button className="primary" disabled={loading || busy} onClick={() => edit(null)}>New budget policy</Button>}</div>
    <div className="panel-body">
      {error && <p className="error-text" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!allowed && !loading && <p className="muted">An organization administrator manages these policies.</p>}
      {open && <form className="form-grid" onSubmit={save}>
        <label>Policy name<Field required maxLength={200} value={name} disabled={busy} onChange={e => setName(e.target.value)} /></label>
        <label>Resource unit<select value={unit} disabled={busy || !!editing} onChange={e => setUnit(e.target.value)}><option value="training_steps">Training steps</option><option value="bank_acquisition_records">Dataset Bank records</option><option value="evaluation_cases">Evaluation cases</option><option value="embedding_attempts">Embedding build attempts</option>{editing && !['training_steps','bank_acquisition_records','evaluation_cases','embedding_attempts'].includes(editing.unit) && <option value={editing.unit}>{editing.unit}</option>}</select></label>
        <label>Budget period<select value={period} disabled={busy || !!editing} onChange={e => setPeriod(e.target.value)}><option value="lifetime">Lifetime</option><option value="monthly">Monthly</option><option value="daily">Daily</option></select></label>
        <label>Policy limit<Field required type="number" min="0.000001" step="0.000001" value={limit} disabled={busy} onChange={e => setLimit(e.target.value)} /></label>
        <label className="checkbox-label"><input type="checkbox" checked={enabled} disabled={busy} onChange={e => setEnabled(e.target.checked)} />Enabled</label>
        <p className="muted full-width">{editing?.currency ? `Existing policy currency: ${editing.currency}.` : 'This is a quantity allowance, not a monetary price. Costs remain unpriced unless measured rates are available.'} Existing reservations retain their units and periods.</p>
        <div className="actions full-width"><Button className="primary" disabled={busy || !name.trim() || !limit}>{busy ? 'Saving…' : 'Save budget policy'}</Button><Button type="button" disabled={busy} onClick={() => setOpen(false)}>Cancel budget edit</Button></div>
      </form>}
      {loading ? <p role="status">Loading budget policies…</p> : !policies.length ? <p className="muted">No policies yet. Create a training-step policy to enable budgeted training.</p> : <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table">
        <thead><tr><th>Policy</th><th>Unit and period</th><th>Limit</th><th>Settled usage</th><th>Reserved</th><th>Remaining</th><th>State</th>{allowed && <th>Edit</th>}</tr></thead>
        <tbody>{policies.map(p => <tr key={p.policy_id}><td>{p.name}<small className="id-text">Organization-wide</small></td><td>{p.unit}{p.currency ? ` · ${p.currency}` : ''}<small className="id-text">{p.period} · {p.allowance?.period_start || 'Period not reported'}</small></td><td>{p.limit_amount}</td><td>{p.allowance?.settled_amount ?? 'Not reported'}</td><td>{p.allowance?.reserved_amount ?? 'Not reported'}</td><td>{p.allowance?.remaining_amount ?? 'Not reported'}</td><td>{p.enabled ? 'Enabled' : 'Disabled'}</td>{allowed && <td><Button disabled={busy} onClick={() => edit(p)}>Edit {p.name}</Button></td>}</tr>)}</tbody>
      </RecordTable></div>}
    </div>
  </Card>;
}
