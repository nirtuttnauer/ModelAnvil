import { useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Field, Notice } from './ui';

interface Policy { mcp_targets?: string[]; code_execution?: boolean; installed_mcp_targets?: { id: string; name: string; available: boolean; endpoint?: string; allowed_tools: string[] }[]; offline: boolean; acquisition_origins: string[]; installation_origins: string[]; measurement_retention_days: number; external_generation_targets: string[]; installed_generation_targets: { id: string; name: string; endpoint: string; model: string; credential_id: string }[] }

export function PrivacySettings({ token }: { token: string }) {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [offline, setOffline] = useState(false);
  const [origins, setOrigins] = useState<string[]>([]);
  const [days, setDays] = useState('30');
  const [targets, setTargets] = useState<string[]>([]);
  const [mcpTargets, setMcpTargets] = useState<string[]>([]);
  const [code, setCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function load() {
    setBusy(true); setError('');
    try {
      const value = await apiRequest<Policy>('/api/v1/privacy/', token);
      setPolicy(value); setMcpTargets(value.mcp_targets || []); setCode(!!value.code_execution); setOffline(value.offline); setOrigins(value.acquisition_origins); setDays(String(value.measurement_retention_days)); setTargets(value.external_generation_targets);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const value = await apiRequest<Policy>('/api/v1/privacy/', token, {method:'PUT', body:JSON.stringify({
        offline, acquisition_origins:origins, measurement_retention_days:Number(days), external_generation_targets:targets, mcp_targets:mcpTargets, code_execution:code})});
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
  return <details className="detail-box" onToggle={e => { if (e.currentTarget.open && !policy && !busy) void load(); }}>
    <summary>Privacy and data</summary>
    <p>Your examples and model responses are processed on the configured execution host. External chat sends conversation content only to a configured provider explicitly enabled below and selected in Chat. External judges, analytics and support uploads are unavailable. Diagnostic downloads contain build identity, policy and job counts only.</p>
    {error && <Notice as="p" tone="error" role="alert">{error}</Notice>}
    {notice && <Notice as="p" role="status">{notice}</Notice>}
    {busy && !policy && <p role="status">Loading project privacy settings…</p>}
    {policy && <form onSubmit={save}>
      <fieldset disabled={busy}><legend>Acquisition policy</legend>
        <label className="checkbox-label"><input type="checkbox" checked={offline} onChange={e => setOffline(e.target.checked)} />Run this project offline</label>
        <p>When acquisition is enabled, requests may send a search or source URL and configured source credentials to these destinations. They may read models and datasets; they cannot upload your examples. Review the complete list before saving.</p>
        {policy.installation_origins.map(value => <label className="checkbox-label" key={value}><input type="checkbox" checked={origins.includes(value)} onChange={e => setOrigins(current => e.target.checked ? [...current,value] : current.filter(v => v !== value))} />{value}</label>)}
        <fieldset><legend>Optional external chat destinations</legend><p>Enabling a target permits Chat to send its system prompt and selected conversation history to that endpoint. Provider retention and charges apply. Credentials remain on the API host. Offline mode disables these requests.</p>{policy.installed_generation_targets.map(value => <label className="checkbox-label" key={value.id}><input type="checkbox" checked={targets.includes(value.id)} onChange={e => setTargets(current => e.target.checked ? [...current,value.id] : current.filter(v => v !== value.id))} />{value.name} · {value.model} · {value.endpoint} · credential: {value.credential_id}</label>)}{!policy.installed_generation_targets.length && <p>No external providers are configured by the installation owner.</p>}</fieldset><fieldset><legend>Model tools</legend><p>Grant reviewed read-only MCP targets to this project. Tools sends selected arguments to the installed endpoint; host credentials stay private. Offline mode disables remote MCP. The local arithmetic server remains available offline.</p>
          {(policy.installed_mcp_targets || []).map(value => <label className="checkbox-label" key={value.id}><input type="checkbox" disabled={!value.available} checked={mcpTargets.includes(value.id)} onChange={e => setMcpTargets(current => e.target.checked ? [...current,value.id] : current.filter(v => v !== value.id))} />{value.name} · {value.allowed_tools.join(', ')}{value.endpoint ? ` · ${value.endpoint}` : ''}{!value.available ? ' · unavailable' : ''}</label>)}
          <label className="checkbox-label"><input type="checkbox" checked={code} onChange={e => setCode(e.target.checked)} />Allow disposable offline Python execution</label><p>Python has no host mounts or network access. Each run is limited to one CPU, 128 MiB and five seconds, with no persistent files. A user must also select it for each tool chat.</p></fieldset><label>Interaction measurement retention (days)<Field type="number" required min="1" max="365" value={days} onChange={e => setDays(e.target.value)} /></label>
        <p>Expired interaction measurements can be purged by an administrator. Saved product data and decisions are retained until explicitly deleted through their own authorized controls.</p>
        <Button disabled={busy || !Number.isInteger(Number(days)) || Number(days)<1 || Number(days)>365}>Save privacy settings</Button>
      </fieldset>
    </form>}
    <div className="actions"><Button disabled={busy} onClick={() => void load()}>Reload privacy settings</Button><Button disabled={busy || !policy} onClick={() => void diagnostics()}>Download safe diagnostics</Button></div>
  </details>;
}
