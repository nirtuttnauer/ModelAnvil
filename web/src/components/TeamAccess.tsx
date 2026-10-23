import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Card, Field } from './ui';

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
  if (!access) return error ? <p role="alert">{error}<Button onClick={() => setRetry(v => v + 1)}>Retry team access</Button></p> : null;
  const occupied = access.members.some(m => m.role !== 'owner') || access.invitations.some(i => i.status === 'pending');
  return <Card className="panel"><div className="panel-body team-access"><h2>Team access</h2>
    <p>Invite one reviewer to this workspace. They can inspect its projects, submit labels and record accept or reject decisions. Reviewers cannot launch jobs, deploy models or manage access.</p>
    {!occupied && <form className="guided-form" onSubmit={e => { e.preventDefault(); void change('/api/v1/accounts/invitations/', 'POST', { email: email.trim() }); }}><label>Reviewer email<Field type="email" autoComplete="off" required value={email} disabled={busy} onChange={e => setEmail(e.target.value)} /></label><Button className="primary" disabled={busy || !email.trim()}>Create invitation</Button></form>}
    {error && <p role="alert">{error}</p>}
    {code && <div role="status"><p>Share this one-time code privately. It expires in 72 hours and is shown only now.</p><label>Invitation code<Field readOnly value={code} autoComplete="off" /></label><Button onClick={() => setCode('')}>Hide invitation code</Button></div>}
    <ul>{access.members.map(m => <li key={m.id}><span>{m.email} · {m.role}</span>{m.role !== 'owner' && <Button disabled={busy} aria-label={`Remove access for ${m.email}`} onClick={() => void change(`/api/v1/memberships/${m.id}/`, 'DELETE')}>Remove access</Button>}</li>)}</ul>
    {!!access.invitations.length && <><h3>Recent invitations</h3><ul>{access.invitations.map(i => <li key={i.id}><span>{i.email} · {i.status} · expires {new Date(i.expires_at).toLocaleString()}</span>{i.status === 'pending' && <Button disabled={busy} aria-label={`Revoke invitation for ${i.email}`} onClick={() => void change(`/api/v1/accounts/invitations/${i.id}/`, 'DELETE')}>Revoke invitation</Button>}</li>)}</ul></>}
  </div></Card>;
}
