import { Button, Field, Notice } from './ui';
import { useEffect, useState, type FormEvent } from 'react';
import { authHeaders, apiRequest, errorMessage, setActiveProjectId } from '../api/client';
import './guided-training.css';

export function Welcome({ onConnected }: { onConnected: (token: string) => void }) {
  const [mode, setMode] = useState<'signup' | 'signin'>('signup');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [signup, setSignup] = useState<boolean | null>(null);
  const [retry, setRetry] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/v1/accounts/status/', { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Could not connect to ModelAnvil. Try again when the app is running.');
      const result = await response.json();
      if (controller.signal.aborted) return;
      setSignup(result.signup_enabled); setMode(result.signup_enabled ? 'signup' : 'signin'); setReady(true);
      if (result.authenticated) onConnected('session');
    }).catch(e => { if (!controller.signal.aborted) { setError(errorMessage(e)); setReady(true); } });
    return () => controller.abort();
  }, [retry]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const headers = authHeaders('session'); headers.set('Content-Type', 'application/json');
      const response = await fetch(`/api/v1/accounts/${mode}/`, { method: 'POST', headers,
        body: JSON.stringify({ ...(mode === 'signup' ? { name: name.trim() } : {}), email: email.trim(), password }), redirect: 'error' });
      const result = await response.json();
      if (!response.ok) {
        const detail = result.error?.details;
        throw new Error(result.error?.message ? result.error.message + (Array.isArray(detail) ? ' ' + detail.map((d: { message: string }) => d.message).join(' ') : '')
          : typeof result.detail === 'string' ? result.detail : 'Could not sign in. Check your email and password.');
      }
      setPassword(''); onConnected(result.token);
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  async function connectKey(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { setActiveProjectId(null); await apiRequest('/api/v1/tenants/', key); onConnected(key); }
    catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  return <main className="welcome-screen"><div className="welcome-intro">
    <img className="welcome-logo-light" src={`${import.meta.env.BASE_URL}brand/modelanvil-logo.svg`} alt="ModelAnvil" width="220" /><img className="welcome-logo-dark" src={`${import.meta.env.BASE_URL}brand/modelanvil-logo-reversed.svg`} alt="ModelAnvil" width="220" />
    <h1>Fine-tune an LLM with your own data.</h1>
    <p>Choose a pretrained model, upload your examples, and train on this computer. ModelAnvil handles the setup.</p>
    <ol className="welcome-journey"><li>Choose your model</li><li>Add your dataset</li><li>Review and train</li></ol>
  </div><section className="welcome-card" aria-labelledby="welcome-title">
    <h2 id="welcome-title">{mode === 'signup' ? 'Create your workspace' : 'Welcome back'}</h2>
    <p>{mode === 'signup' ? 'Your account includes a project for your first fine-tune.' : 'Sign in to continue your training and saved models.'}</p>
    {error && <Notice tone="error" role="alert" className="notice error">{error}{signup === null && <Button onClick={() => { setReady(false); setError(''); setRetry(v => v + 1); }}>Retry connection</Button>}</Notice>}
    <form onSubmit={submit} className="guided-form">
      {mode === 'signup' && <label>Your name<Field autoComplete="name" value={name} onChange={e => setName(e.target.value)} maxLength={100} required disabled={busy} /></label>}
      <label>Email<Field type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} maxLength={254} required disabled={busy} /></label>
      <label>Password<Field type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} minLength={mode === 'signup' ? 10 : 1} maxLength={256} required disabled={busy} />{mode === 'signup' && <small>Use at least 10 characters.</small>}</label>
      <Button className="primary" disabled={busy || !ready || (mode === 'signup' && signup !== true)}>{busy ? 'Connecting…' : mode === 'signup' ? 'Create account' : 'Sign in'}</Button>
    </form>
    {(signup || mode === 'signup') && <Button className="welcome-switch" disabled={busy} onClick={() => { setMode(mode === 'signup' ? 'signin' : 'signup'); setError(''); }}>{mode === 'signup' ? 'Already have an account? Sign in' : 'Create a new account'}</Button>}
    {signup === false && ready && <p>Account creation is disabled here. Ask the installation owner for an account.</p>}
    <details><summary>Connect an existing workspace with an API key</summary><form onSubmit={connectKey} className="guided-form"><label>Organization API key<Field type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} required disabled={busy} /></label><Button disabled={busy || !key.trim()}>Connect workspace</Button></form></details>
  </section></main>;
}
