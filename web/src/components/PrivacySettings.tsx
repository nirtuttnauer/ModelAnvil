import { useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Checkbox, Disclosure, Field, Notice } from './ui';

interface Policy { offline: boolean; acquisition_origins: string[]; installation_origins: string[]; measurement_retention_days: number }

export function PrivacySettings({ token }: { token: string }) {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [offline, setOffline] = useState(false);
  const [origins, setOrigins] = useState<string[]>([]);
  const [days, setDays] = useState('30');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function load() {
    setBusy(true); setError('');
    try {
      const value = await apiRequest<Policy>('/api/v1/privacy/', token);
      setPolicy(value); setOffline(value.offline); setOrigins(value.acquisition_origins); setDays(String(value.measurement_retention_days));
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const value = await apiRequest<Policy>('/api/v1/privacy/', token, {method:'PUT', body:JSON.stringify({
        offline, acquisition_origins:origins, measurement_retention_days:Number(days)})});
      setPolicy(value); setOffline(value.offline); setNotice('Project privacy settings saved. Installation restrictions still apply.');
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function diagnostics() {
    setBusy(true); setError('');
    try {
      const value = await apiRequest<unknown>('/api/v1/privacy/diagnostics/', token);
      const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)], {type:'application/json'}));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'modelanvil-diagnostics.json'; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <Disclosure summary="Privacy and data" onToggle={e => { if (e.currentTarget.open && !policy && !busy) void load(); }}>
    <p className="muted">Examples and responses stay on this computer. Diagnostics contain build identity, policy and job counts only.</p>
    {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
    {notice && <Notice as="p" role="status">{notice}</Notice>}
    {busy && !policy && <p role="status">Loading project privacy settings…</p>}
    {policy && <form onSubmit={save}>
      <fieldset disabled={busy}><legend>Acquisition policy</legend>
        <Checkbox label="Run this project offline" checked={offline} onChange={e => setOffline(e.target.checked)} />
        <p className="muted">Allowed destinations may read models and datasets. They never receive your examples.</p>
        {policy.installation_origins.map(value => <Checkbox key={value} label={value} checked={origins.includes(value)} onChange={e => setOrigins(current => e.target.checked ? [...current,value] : current.filter(v => v !== value))} />)}
        <label>Interaction measurement retention (days)<Field type="number" required min="1" max="365" value={days} onChange={e => setDays(e.target.value)} /></label>
        <p className="muted">Expired measurements can be purged by an administrator.</p>
        <Button disabled={busy || !Number.isInteger(Number(days)) || Number(days)<1 || Number(days)>365}>Save privacy settings</Button>
      </fieldset>
    </form>}
    <div data-ui="actions"><Button disabled={busy} onClick={() => void load()}>Reload privacy settings</Button><Button disabled={busy || !policy} onClick={() => void diagnostics()}>Download safe diagnostics</Button></div>
  </Disclosure>;
}
