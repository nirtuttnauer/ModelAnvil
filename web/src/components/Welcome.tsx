import { Button, Field, Notice } from './ui';
import { useEffect, useState, type FormEvent } from 'react';
import { authHeaders, apiRequest, errorMessage, setActiveProjectId } from '../api/client';
import './guided-training.css';

export function Welcome({ onConnected }: { onConnected: (token: string) => void }) {
  const [mode, setMode] = useState<'signup' | 'signin' | 'reset' | 'invite'>('signup');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [delivery, setDelivery] = useState('');
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
      setSignup(result.signup_enabled); setMode(current => current === 'reset' || current === 'invite' ? current : result.signup_enabled ? 'signup' : 'signin'); setReady(true);
      if (result.authenticated) onConnected('session');
    }).catch(e => { if (!controller.signal.aborted) { setError(errorMessage(e)); setReady(true); } });
    return () => controller.abort();
  }, [retry]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const headers = authHeaders('session'); headers.set('Content-Type', 'application/json');
      const path = mode === 'reset' ? (code ? 'password-reset/confirm' : 'password-reset') : mode === 'invite' ? 'invitations/accept' : mode;
      const response = await fetch(`/api/v1/accounts/${path}/`, { method: 'POST', headers,
        body: JSON.stringify(mode === 'reset' && !code ? { email: email.trim() } : mode === 'reset' ? { email: email.trim(), password, code: code.trim() }
          : mode === 'invite' ? { email: email.trim(), name: name.trim(), password, code: code.trim() }
          : { ...(mode === 'signup' ? { name: name.trim() } : {}), email: email.trim(), password }), redirect: 'error' });
      const result = await response.json();
      if (!response.ok) {
        const detail = result.error?.details;
        throw new Error(result.error?.message ? result.error.message + (Array.isArray(detail) ? ' ' + detail.map((d: { message: string }) => d.message).join(' ') : '')
          : typeof result.detail === 'string' ? result.detail : 'Could not sign in. Check your email and password.');
      }
      if (mode === 'reset' && !code) {
        setDelivery(typeof result.delivery === 'string' ? result.delivery : 'If this email has an account, reset instructions are ready.');
        if (typeof result.reset_code === 'string') setCode(result.reset_code);
        return;
      }
      setPassword(''); setCode(''); onConnected(result.token);
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
    <h2 id="welcome-title">{mode === 'signup' ? 'Create your workspace' : mode === 'reset' ? 'Reset your password' : mode === 'invite' ? 'Join this workspace' : 'Welcome back'}</h2>
    <p>{mode === 'signup' ? 'Your account includes a project for your first fine-tune.' : mode === 'reset' ? 'Email accounts created here can set a new password.' : mode === 'invite' ? 'Use the one-time code from the workspace owner. You can review results and record the decision.' : 'Sign in to continue your training and saved models.'}</p>
    {error && <Notice tone="error" role="alert" className="notice error">{error}{signup === null && <Button onClick={() => { setReady(false); setError(''); setRetry(v => v + 1); }}>Retry connection</Button>}</Notice>}
    <form onSubmit={submit} className="guided-form">
      {(mode === 'signup' || mode === 'invite') && <label>Your name<Field autoComplete="name" value={name} onChange={e => setName(e.target.value)} maxLength={100} required disabled={busy} /></label>}
      <label>Email<Field type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} maxLength={254} required disabled={busy} /></label>
      {(mode !== 'reset' || code) && <label>Password<Field type="password" autoComplete={mode === 'signin' ? 'current-password' : 'new-password'} value={password} onChange={e => setPassword(e.target.value)} minLength={mode === 'signin' ? 1 : 10} maxLength={256} required disabled={busy} />{mode !== 'signin' && <small>Use at least 10 characters.</small>}</label>}
      {(mode === 'invite' || (mode === 'reset' && code)) && <label>One-time code<Field autoComplete="one-time-code" value={code} onChange={e => setCode(e.target.value)} minLength={8} maxLength={128} required disabled={busy} /></label>}
      {mode === 'reset' && delivery && <p role="status">{delivery}</p>}
      <Button className="primary" disabled={busy || !ready || (mode === 'signup' && signup !== true)}>{busy ? 'Connecting…' : mode === 'signup' ? 'Create account' : mode === 'reset' ? (code ? 'Set new password' : 'Request reset code') : mode === 'invite' ? 'Join workspace' : 'Sign in'}</Button>
    </form>
    {(signup || mode === 'signup') && mode !== 'reset' && mode !== 'invite' && <Button className="welcome-switch" disabled={busy} onClick={() => { setMode(mode === 'signup' ? 'signin' : 'signup'); setError(''); }}>{mode === 'signup' ? 'Already have an account? Sign in' : 'Create a new account'}</Button>}
    {mode === 'signin' && <Button className="welcome-switch" disabled={busy} onClick={() => { setMode('reset'); setCode(''); setDelivery(''); setError(''); }}>Forgot your password?</Button>}
    {mode !== 'invite' && <Button className="welcome-switch" disabled={busy} onClick={() => { setMode('invite'); setCode(''); setError(''); }}>Have an invitation code?</Button>}
    {(mode === 'reset' || mode === 'invite') && <Button className="welcome-switch" disabled={busy} onClick={() => { setMode(signup ? 'signup' : 'signin'); setCode(''); setDelivery(''); setError(''); }}>Back to sign in</Button>}
    {signup === false && ready && <p>Account creation is disabled here. Ask the installation owner for an account.</p>}
    <details><summary>Connect an existing workspace with an API key</summary><form onSubmit={connectKey} className="guided-form"><label>Organization API key<Field type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} required disabled={busy} /></label><Button disabled={busy || !key.trim()}>Connect workspace</Button></form></details>
  </section></main>;
}
