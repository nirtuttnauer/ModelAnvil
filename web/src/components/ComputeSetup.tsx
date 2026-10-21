import { Identifier } from './Identifier';
import { Button, Card, Field, Notice } from './ui';
import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { computeReadiness, type ComputeWorker } from '../api/compute';

interface Profile { id: string; name: string; memory_bytes: number; limitations: string[]; available: boolean }
interface Registration { worker_id: number; worker_token: string; worker_token_expires_at: string; startup_command: string }

export function ComputeSetup({ token, onRegistered, onPermission }: {
  token: string; onRegistered: () => void; onPermission: (allowed: boolean) => void;
}) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [allowed, setAllowed] = useState(false);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [pool, setPool] = useState('');
  const [profile, setProfile] = useState('cpu-character');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [registration, setRegistration] = useState<Registration | null>(null);
  const [worker, setWorker] = useState<ComputeWorker | null>(null);
  const [revealed, setRevealed] = useState(false);
  const inventoryChanged = useRef(onRegistered);
  inventoryChanged.current = onRegistered;
  useEffect(() => {
    const c = new AbortController(); setRegistration(null); setWorker(null); setRevealed(false);
    apiRequest<{ can_administer: boolean; profiles: Profile[] }>('/api/v1/workers/setup/', token, { signal: c.signal })
      .then(data => { if (!c.signal.aborted) { setAllowed(data.can_administer); onPermission(data.can_administer); setProfiles(data.profiles); setError(''); } })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => c.abort();
  }, [token, retry, onPermission]);
  useEffect(() => {
    if (!registration) return;
    const c = new AbortController(); let pending = false; let connection = 'not_connected';
    async function poll() {
      if (pending || c.signal.aborted || document.visibilityState !== 'visible') return;
      pending = true;
      try { const data = await apiRequest<ComputeWorker>(`/api/v1/worker-inventory/${registration!.worker_id}/`, token, { signal: c.signal }); if (!c.signal.aborted) { setWorker(data); if (data.connection_state !== connection) { connection = data.connection_state || ''; inventoryChanged.current(); } } }
      catch(e) { if (!c.signal.aborted) setError(errorMessage(e)); }
      finally { pending = false; }
    }
    void poll(); const timer = window.setInterval(poll, 3000);
    return () => { c.abort(); window.clearInterval(timer); };
  }, [registration, token]);
  async function register(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const data = await apiRequest<Registration>('/api/v1/workers/setup/', token,
        { method: 'POST', body: JSON.stringify({ worker_name: name.trim(), pool: pool.trim(), profile }) });
      setRegistration(data); setWorker(null); setRevealed(false); setOpen(false); onRegistered();
    } catch(e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  const selected = profiles.find(p => p.id === profile);
  return <Card className="panel" aria-label="Compute setup">
    <div className="panel-title"><div><h2>Set up local compute</h2><p>Register an installed runtime, then connect its worker.</p></div>
      {allowed && <Button className="primary" disabled={busy || !!registration} onClick={() => setOpen(v => !v)}>{open ? 'Close compute setup' : 'Register local worker'}</Button>}</div>
    <div className="panel-body">
      {error && <Notice tone="error" className="notice error" role="alert">{error}<Button disabled={busy} onClick={() => setRetry(v => v + 1)}>Retry setup access</Button></Notice>}
      {!allowed && !error && <p className="muted">An organization administrator can register compute here.</p>}
      {open && <form className="form-grid" onSubmit={register}>
        <label>Worker name<Field required maxLength={200} disabled={busy} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Pool name<Field required maxLength={100} disabled={busy} value={pool} onChange={e => setPool(e.target.value)} /><small>Use an active pool name or create a new pool.</small></label>
        <label>Installed runtime<select disabled={busy} value={profile} onChange={e => setProfile(e.target.value)}>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}{p.available ? '' : ' · packages required'}</option>)}</select></label>
        {selected && <div className="full-width"><p>One CPU slot · minimum {selected.memory_bytes / 1048576} MiB host memory.</p><ul>{selected.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul></div>}
        <p className="muted full-width">Registration does not start work. Run the worker in the same trusted service environment as the API, with the same database and artifact storage. Remote HTTP training is not supported by this local profile.</p>
        <Button className="primary" disabled={busy || !name.trim() || !pool.trim() || !selected?.available}>{busy ? 'Registering…' : 'Register compute'}</Button>
      </form>}
      {registration && <div className="detail-box" aria-label="Worker connection instructions">
        <h3>Connect worker <Identifier value={registration.worker_id} label="Worker record ID" /></h3>
        <p>Save this credential securely. It is shown once and cleared when you dismiss these instructions or leave the page.</p>
        <label>One-time worker credential<Field type={revealed ? 'text' : 'password'} readOnly autoComplete="off" value={registration.worker_token} /></label>
        <Button onClick={() => setRevealed(v => !v)}>{revealed ? 'Hide credential' : 'Reveal credential'}</Button>
        <p>Expires {new Date(registration.worker_token_expires_at).toLocaleString()}.</p>
        <p>From the installed application directory, run this command. Paste the credential at its hidden prompt; keep it out of command history.</p>
        <pre tabIndex={0} style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{registration.startup_command}</pre>
        <p role="status">{worker ? computeReadiness(worker) : 'Waiting for a worker heartbeat'}</p>
        <p className="muted">A connected worker still needs compatible inputs and a quota for its workload before launch.</p>
        <div className="actions"><Button onClick={onRegistered}>Refresh inventory</Button><Button onClick={() => { setRegistration(null); setWorker(null); setRevealed(false); }}>Dismiss connection instructions</Button></div>
      </div>}
    </div>
  </Card>;
}
