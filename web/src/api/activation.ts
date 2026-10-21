import { apiPath, authHeaders } from './client.ts';

/** Interaction timing is a local, best-effort lower bound, never execution evidence. */
export class ActiveTime {
  private sampledAt: number;
  private lastInteraction: number;
  private focused: boolean;
  constructor(now: number, focused: boolean) {
    this.sampledAt = now; this.lastInteraction = -Infinity; this.focused = focused;
  }
  interact(now: number): void { this.lastInteraction = now; }
  sample(now: number, focused: boolean): number {
    const milliseconds = this.focused ? Math.max(0, Math.min(now, this.lastInteraction + 15000) - this.sampledAt) : 0;
    this.sampledAt = now; this.focused = focused;
    return Math.min(60000, Math.floor(milliseconds));
  }
}

export function startActivation(token: string, project: string): () => void {
  const key = `modelanvil_activation_${project}`;
  let session: string;
  try {
    session = sessionStorage.getItem(key) || crypto.randomUUID();
    sessionStorage.setItem(key, session);
  } catch { session = crypto.randomUUID(); }
  const focused = () => document.visibilityState === 'visible' && document.hasFocus();
  const clock = new ActiveTime(performance.now(), focused());
  let active = 0;
  let stopped = false;
  const sample = () => { active += clock.sample(performance.now(), focused()); };
  const interact = () => { sample(); clock.interact(performance.now()); };
  const send = (kind: 'workspace_opened' | 'activity', milliseconds = 0) => {
    const headers = authHeaders(token);
    headers.set('Content-Type', 'application/json');
    // Capture the project: cleanup can run after the global API scope has changed.
    headers.set('X-Project-ID', project);
    const event = { event_id: kind === 'workspace_opened' ? session : crypto.randomUUID(),
      session_id: session, kind, active_milliseconds: Math.min(60000, milliseconds) };
    const request = () => fetch(apiPath('/api/v1/activation/events/'), { method: 'POST', headers,
      body: JSON.stringify(event), keepalive: true, redirect: 'error' });
    // An uncertain retry reuses the same event ID; failed measurements never block work.
    void request().catch(() => stopped ? undefined : request()).catch(() => undefined);
  };
  const flush = () => { sample(); if (active) { send('activity', active); active = 0; } };
  send('workspace_opened');
  const timer = window.setInterval(flush, 30000);
  for (const name of ['pointerdown', 'keydown', 'scroll']) window.addEventListener(name, interact, { passive: true });
  document.addEventListener('visibilitychange', sample);
  window.addEventListener('blur', sample);
  window.addEventListener('focus', sample);
  window.addEventListener('pagehide', flush);
  return () => {
    flush(); stopped = true; window.clearInterval(timer);
    for (const name of ['pointerdown', 'keydown', 'scroll']) window.removeEventListener(name, interact);
    document.removeEventListener('visibilitychange', sample);
    window.removeEventListener('blur', sample); window.removeEventListener('focus', sample);
    window.removeEventListener('pagehide', flush);
  };
}
