import { Button, Dialog, Notice, Select, TextControl } from './ui';
import { useEffect, useId, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { computeReadiness, type ComputeWorker } from '../api/compute';

interface Profile { id: string; name: string; memory_bytes: number; limitations: string[]; available: boolean }
interface Registration { worker_id: number; worker_token: string; worker_token_expires_at: string; startup_command: string }

/** Registers a local worker in a dialog and shows its one-time connection credential until dismissed. */
export function ComputeSetup({ token, open, onClose, onRegistered, onPermission }: {
  token: string; open: boolean; onClose: () => void; onRegistered: () => void; onPermission: (allowed: boolean) => void;
}) {
  const formId = useId();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [allowed, setAllowed] = useState(false);
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
      setRegistration(data); setWorker(null); setRevealed(false); onRegistered();
    } catch(e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  function dismiss() { setRegistration(null); setWorker(null); setRevealed(false); }
  const selected = profiles.find(p => p.id === profile);
  return <Dialog title="Register local worker" description="Register an installed runtime, then connect its worker." open={open} onClose={onClose}
    footer={registration
      ? <><Button type="button" onClick={onRegistered}>Refresh inventory</Button><Button type="button" variant="primary" onClick={() => { dismiss(); onClose(); }}>Done</Button></>
      : <><Button type="button" disabled={busy} onClick={onClose}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || !allowed || !name.trim() || !pool.trim() || !selected?.available}>{busy ? 'Registering…' : 'Register compute'}</Button></>}>
    {error && <Notice tone="error" role="alert">{error} <Button type="button" size="sm" disabled={busy} onClick={() => setRetry(v => v + 1)}>Retry setup access</Button></Notice>}
    {!allowed && !error && <p className="muted">An organization administrator can register compute here.</p>}
    {allowed && !registration && <form id={formId} data-ui="form" onSubmit={register}>
      <div data-ui="field-grid">
        <TextControl label="Worker name" required maxLength={200} disabled={busy} value={name} onChange={e => setName(e.target.value)} />
        <TextControl label="Pool name" hint="Use an active pool name or create a new pool." required maxLength={100} disabled={busy} value={pool} onChange={e => setPool(e.target.value)} />
        <div data-span="full"><Select label="Installed runtime" disabled={busy} value={profile} onChange={e => setProfile(e.target.value)}>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}{p.available ? '' : ' · packages required'}</option>)}</Select></div>
      </div>
      {selected && <p className="muted">One CPU slot · minimum {selected.memory_bytes / 1048576} MiB host memory.{selected.limitations.length ? ` ${selected.limitations.join(' ')}` : ''}</p>}
      <p className="muted">Registration does not start work. Run the worker next to the API with the same database and artifact storage.</p>
    </form>}
    {registration && <div data-ui="form" aria-label="Worker connection instructions">
      <p>Save this credential securely. It is shown once and cleared when you dismiss these instructions.</p>
      <TextControl label="One-time worker credential" type={revealed ? 'text' : 'password'} readOnly autoComplete="off" value={registration.worker_token} />
      <div data-ui="actions"><Button type="button" size="sm" onClick={() => setRevealed(v => !v)}>{revealed ? 'Hide credential' : 'Reveal credential'}</Button><span className="muted">Expires {new Date(registration.worker_token_expires_at).toLocaleString()}.</span></div>
      <p>From the installed application directory, run this command and paste the credential at its hidden prompt.</p>
      <pre tabIndex={0} className="ops-command">{registration.startup_command}</pre>
      <p role="status">{worker ? computeReadiness(worker) : 'Waiting for a worker heartbeat'}</p>
    </div>}
  </Dialog>;
}
