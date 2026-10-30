import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { statusLabel } from '../api/status';
import { Button, Card, Notice, RecordTable, Section, StatusBadge, TextControl } from './ui';

type Access = { invitations: { id: string; email: string; role: string; expires_at: string; status: string }[]; members: { id: string; email: string; role: string }[] };
export function TeamAccess({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [access, setAccess] = useState<Access | null>(null);
  const [email, setEmail] = useState(''); const [code, setCode] = useState('');
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [retry, setRetry] = useState(0);
  useEffect(() => { const c = new AbortController();
    apiRequest<{ can_invite?: boolean }>('/api/v1/accounts/status/', token, { signal: c.signal }).then(async status => {
      if (!status.can_invite) { if (!c.signal.aborted) setAccess(null); return; }
      const result = await apiRequest<Access>('/api/v1/accounts/invitations/', token, { signal: c.signal });
      if (!c.signal.aborted) { setAccess(result); setError(''); }
    }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }); return () => c.abort();
  }, [token, refreshKey, retry]);
  async function change(path: string, method: string, body?: object) {
    setBusy(true); setError(''); setCode('');
    try { const result = await apiRequest<{ invite_code?: string }>(path, token, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
      if (result?.invite_code) { setCode(result.invite_code); setEmail(''); } setRetry(v => v + 1);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  if (!access) return error ? <Notice tone="error" role="alert"><span>{error}</span><Button type="button" onClick={() => setRetry(v => v + 1)}>Retry team access</Button></Notice> : null;
  const occupied = access.members.some(m => m.role !== 'owner') || access.invitations.some(i => i.status === 'pending');
  return <Section title="Team access" description="Invite one reviewer to this workspace. They can inspect its projects, submit labels and record accept or reject decisions. Reviewers cannot launch jobs, deploy models or manage access.">
    {!occupied && <form data-ui="form" onSubmit={e => { e.preventDefault(); void change('/api/v1/accounts/invitations/', 'POST', { email: email.trim() }); }}>
      <div data-ui="field-grid"><TextControl label="Reviewer email" type="email" autoComplete="off" required value={email} disabled={busy} onChange={e => setEmail(e.target.value)} /></div>
      <div data-ui="actions"><Button variant="primary" disabled={busy || !email.trim()}>Create invitation</Button></div>
    </form>}
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    {code && <Card tone="accent" padded role="status"><div data-ui="form">
      <p>Share this one-time code privately. It expires in 72 hours and is shown only now.</p>
      <div data-ui="field-grid"><TextControl label="Invitation code" readOnly value={code} autoComplete="off" /></div>
      <div data-ui="actions"><Button type="button" onClick={() => setCode('')}>Hide invitation code</Button></div>
    </div></Card>}
    <div className="table-scroll" tabIndex={0}><RecordTable><caption>Members</caption>
      <thead><tr><th>Member</th><th>Role</th><th>Actions</th></tr></thead>
      <tbody>{access.members.map(m => <tr key={m.id}><td>{m.email}</td><td>{statusLabel(m.role)}</td><td>{m.role !== 'owner' && <Button type="button" size="sm" disabled={busy} aria-label={`Remove access for ${m.email}`} onClick={() => void change(`/api/v1/memberships/${m.id}/`, 'DELETE')}>Remove access</Button>}</td></tr>)}</tbody>
    </RecordTable></div>
    {!!access.invitations.length && <Section level={3} title="Recent invitations">
      <div className="table-scroll" tabIndex={0}><RecordTable>
        <thead><tr><th>Email</th><th>Status</th><th>Expires</th><th>Actions</th></tr></thead>
        <tbody>{access.invitations.map(i => <tr key={i.id}><td>{i.email}</td><td><StatusBadge status={i.status} /></td><td>{new Date(i.expires_at).toLocaleString()}</td><td>{i.status === 'pending' && <Button type="button" size="sm" disabled={busy} aria-label={`Revoke invitation for ${i.email}`} onClick={() => void change(`/api/v1/accounts/invitations/${i.id}/`, 'DELETE')}>Revoke invitation</Button>}</td></tr>)}</tbody>
      </RecordTable></div>
    </Section>}
  </Section>;
}
