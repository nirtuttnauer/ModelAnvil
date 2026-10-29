import { Button, Checkbox, Dialog, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from './ui';
import { useEffect, useId, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources } from '../api/resources';

interface Policy {
  policy_id: string; name: string; period: string; unit: string; currency: string; limit_amount: string; enabled: boolean;
  allowance?: { scope: string; period_start: string; reserved_amount: string; settled_amount: string; remaining_amount: string };
}
const UNITS = [{ value: 'training_steps', label: 'Training steps' }, { value: 'bank_acquisition_records', label: 'Dataset Bank records' }, { value: 'evaluation_cases', label: 'Evaluation cases' }];

/** Organization-wide budget policies, edited in a dialog by administrators. */
export function BudgetPolicyEditor({ token, refreshKey, onChanged }: { token: string; refreshKey: number; onChanged: () => void }) {
  const formId = useId();
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
  const unitOptions = editing && !UNITS.some(u => u.value === editing.unit) ? [...UNITS, { value: editing.unit, label: editing.unit }] : UNITS;
  return <Section title="Budget policies" description="Organization-wide limits shared across projects." actions={allowed && <Button type="button" variant="primary" disabled={loading || busy} onClick={() => edit(null)}>New policy</Button>}>
    {error && !open && <p className="error-text" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!allowed && !loading && <p className="muted">An organization administrator manages these policies.</p>}
    {loading ? <p role="status">Loading budget policies…</p> : !policies.length ? <p className="muted">No policies yet. Create a training-step policy to enable budgeted training.</p> : <div className="table-scroll" tabIndex={0}><RecordTable>
      <thead><tr><th>Policy</th><th>Unit and period</th><th>Limit</th><th>Settled</th><th>Reserved</th><th>Remaining</th><th>State</th>{allowed && <th>Actions</th>}</tr></thead>
      <tbody>{policies.map(p => <tr key={p.policy_id}>
        <td>{p.name}</td>
        <td>{p.unit}{p.currency ? ` · ${p.currency}` : ''}<small>{p.period} · {p.allowance?.period_start || 'Period not reported'}</small></td>
        <td>{p.limit_amount}</td><td>{p.allowance?.settled_amount ?? 'Not reported'}</td><td>{p.allowance?.reserved_amount ?? 'Not reported'}</td><td>{p.allowance?.remaining_amount ?? 'Not reported'}</td>
        <td><StatusBadge status={p.enabled ? 'enabled' : 'disabled'} label={p.enabled ? 'Enabled' : 'Disabled'} /></td>
        {allowed && <td><Button type="button" size="sm" disabled={busy} aria-label={`Edit ${p.name}`} onClick={() => edit(p)}>Edit</Button></td>}
      </tr>)}</tbody>
    </RecordTable></div>}
    <Dialog title={editing ? 'Edit budget policy' : 'New budget policy'} description="A quantity allowance per period, not a monetary price." open={open} onClose={() => setOpen(false)}
      footer={<><Button type="button" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || !name.trim() || !limit}>{busy ? 'Saving…' : 'Save budget policy'}</Button></>}>
      <form id={formId} data-ui="form" onSubmit={save}>
        {error && <Notice tone="error" role="alert">{error}</Notice>}
        <div data-ui="field-grid">
          <TextControl label="Policy name" required maxLength={200} value={name} disabled={busy} onChange={e => setName(e.target.value)} />
          <TextControl label="Policy limit" required type="number" min="0.000001" step="0.000001" value={limit} disabled={busy} onChange={e => setLimit(e.target.value)} />
          <Select label="Resource unit" value={unit} disabled={busy || !!editing} onChange={e => setUnit(e.target.value)} options={unitOptions} />
          <Select label="Budget period" value={period} disabled={busy || !!editing} onChange={e => setPeriod(e.target.value)} options={[{ value: 'lifetime', label: 'Lifetime' }, { value: 'monthly', label: 'Monthly' }, { value: 'daily', label: 'Daily' }]} />
          <div data-span="full"><Checkbox label="Enabled" checked={enabled} disabled={busy} onChange={e => setEnabled(e.target.checked)} /></div>
        </div>
        <p className="muted">{editing?.currency ? `Existing policy currency: ${editing.currency}. ` : ''}Existing reservations keep their units and periods.</p>
      </form>
    </Dialog>
  </Section>;
}
