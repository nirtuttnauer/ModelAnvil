import { Identifier } from './Identifier';
import { Button, Notice, StatusBadge } from './ui';
import { useEffect, useId, useRef, useState } from 'react';
import { Activity, ArrowUpRight, RefreshCw } from 'lucide-react';
import { activeJobDisplayName, loadActiveJobs, type ActiveJob } from '../api/active-jobs';
import { errorMessage } from '../api/client';
import { runHash } from '../api/runs';
import { InspectorPanel } from './InspectorPanel';
import './active-jobs.css';

export function ActiveJobs({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [open, setOpen] = useState(false), id = useId();
  const drawer = useRef<HTMLDialogElement>(null);
  const [jobs, setJobs] = useState<ActiveJob[]>([]);
  const [loading, setLoading] = useState(true), [fetching, setFetching] = useState(false);
  const [error, setError] = useState(''), [updated, setUpdated] = useState<Date | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open || !drawer.current) return;
    const element = drawer.current, compact = window.matchMedia('(max-width: 1199px)');
    function show() {
      element.close();
      if (compact.matches) element.showModal(); else element.show();
    }
    show(); compact.addEventListener('change', show);
    return () => { compact.removeEventListener('change', show); element.close(); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape' && !event.defaultPrevented && !document.querySelector('dialog[open]:not(.active-jobs-drawer)')) { event.preventDefault(); setOpen(false); }
    }
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); let pending = false;
    async function refresh() {
      if (pending) return; pending = true; setFetching(true);
      try {
        const values = await loadActiveJobs(token, controller.signal);
        if (!controller.signal.aborted) { setJobs(values); setError(''); setUpdated(new Date()); }
      } catch (e) { if (!controller.signal.aborted) setError(errorMessage(e)); }
      finally { pending = false; if (!controller.signal.aborted) { setLoading(false); setFetching(false); } }
    }
    void refresh();
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void refresh(); }, 5000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [open, token, refreshKey, retry]);
  return <><Button type="button" variant="quiet" icon className="active-jobs-trigger" aria-label="Active jobs" title="Active jobs" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}><Activity size={18} aria-hidden="true" />{open && !loading && !error && <span className="active-jobs-count" aria-hidden="true">{jobs.length}</span>}</Button>
    {open && <dialog ref={drawer} className="active-jobs-drawer" id={id} aria-label="Active jobs" onCancel={() => setOpen(false)} onClick={event => { if (event.target === event.currentTarget) setOpen(false); }}><InspectorPanel title="Active jobs" eyebrow="This project" closeLabel="Close active jobs" onClose={() => setOpen(false)}>
      <div className="active-jobs-summary"><p role="status">{loading ? 'Loading active jobs…' : error ? 'Live updates unavailable' : `${jobs.length} active ${jobs.length === 1 ? 'job' : 'jobs'}`}</p><Button type="button" variant="quiet" icon disabled={fetching} aria-label="Refresh active jobs" onClick={() => setRetry(value => value + 1)}><RefreshCw size={16} aria-hidden="true" /></Button></div>
      <p className="active-jobs-muted">Refreshes every 5 seconds while open.</p>
      {error && <Notice tone="error" role="alert">Could not refresh jobs. {error}<Button disabled={fetching} onClick={() => setRetry(value => value + 1)}>Try again</Button></Notice>}
      {!loading && !error && !jobs.length && <div className="active-jobs-empty"><Activity size={28} aria-hidden="true" /><h3>No active jobs</h3><p>Training, evaluations and other queued work will appear here when started.</p></div>}
      <ul className="active-job-list">{jobs.map(job => <li key={job.job_id}><div className="active-job-heading"><strong>{activeJobDisplayName(job.name)}</strong><Identifier value={job.job_id} label="Job ID" /><StatusBadge status={job.desired_action === 'cancel' ? 'cancellation_requested' : job.status} label={job.desired_action === 'cancel' ? 'Cancelling' : job.status === 'running' ? 'Running' : 'Queued'} /></div>
        {job.payload?.type && <p className="active-jobs-muted">{job.payload.type === 'qualified_training' ? 'Language model training' : job.payload.type.replaceAll('_', ' ')}</p>}
        {job.status === 'running' ? job.progress == null ? <p className="active-jobs-muted">Progress not reported yet.</p> : <><div className="active-job-progress"><span>Reported progress</span><strong>{job.progress}%</strong></div><progress aria-label={`${job.name} progress`} value={job.progress} max={100} /></> : <p className="active-jobs-muted">Waiting to start.</p>}
        <a href={runHash('job', job.job_id)} onClick={() => setOpen(false)}>Open run <ArrowUpRight size={14} aria-hidden="true" /></a>
      </li>)}</ul>
      {updated && <p className="active-jobs-muted">Last updated {updated.toLocaleTimeString()}{error ? ' · data may be out of date' : ''}</p>}
    </InspectorPanel></dialog>}
  </>;
}
