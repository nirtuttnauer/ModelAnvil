import { Identifier } from './Identifier';
import { Button, Notice } from './ui';
import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import type { SpecialistJob, SpecialistResult } from '../api/specialists';

export function SpecialistJobs({ token, selected, onSelect, onResult }: {
  token: string; selected: string; onSelect: (id: string) => void;
  onResult: (result: SpecialistResult, kind: string) => void;
}) {
  const [recent, setRecent] = useState<SpecialistJob[]>([]);
  const [job, setJob] = useState<SpecialistJob | null>(null);
  const [error, setError] = useState('');
  const [mutating, setMutating] = useState(false);
  const delivered = useRef('');
  const callback = useRef(onResult); callback.current = onResult;
  useEffect(() => {
    if (!token.trim()) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    setJob(null); delivered.current = ''; setError('');
    async function poll() {
      try {
        const list = await apiRequest<SpecialistJob[]>('/api/v1/specialists/jobs/', token, { signal: controller.signal });
        const status = selected ? await apiRequest<SpecialistJob>(`/api/v1/specialists/jobs/${selected}/`, token, { signal: controller.signal }) : null;
        if (controller.signal.aborted) return;
        setRecent(list); setJob(status); setError('');
        if (status?.result && delivered.current !== status.request_id) {
          delivered.current = status.request_id;
          callback.current(status.result, status.kind || 'ocr');
        }
      } catch (e) { if (!controller.signal.aborted) setError(errorMessage(e)); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2500);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [token, selected]);

  async function action(name: 'cancel' | 'retry') {
    if (mutating || !selected) return;
    setMutating(true); setError('');
    try { await apiRequest(`/api/v1/specialists/jobs/${selected}/${name}/`, token, { method:'POST' }); }
    catch (e) { setError(errorMessage(e)); }
    finally { setMutating(false); }
  }

  return <section className="detail-box specialist-jobs"><h3>Durable specialist jobs</h3>
    <p className="muted">Jobs continue after you leave this page. Completed requests restore their results; failed requests can retry within the admitted attempt quota.</p>
    {error && <Notice tone="error" role="alert">{error}</Notice>}
    <label>Recent requests<select value={selected} onChange={e => onSelect(e.target.value)}>
      <option value="">Select a request</option>
      {recent.map((r, index) => <option key={r.request_id} value={r.request_id}>{r.kind?.toUpperCase()} · request {index + 1} · {r.status}</option>)}
    </select></label>
    {job && <div><p role="status">{job.status} · attempt {job.attempt_count} of {job.max_attempts}{job.desired_action === 'cancel' ? ' · cancellation requested' : ''}</p>
      <span>Request <Identifier value={job.request_id} label="Specialist request ID" /> Job <Identifier value={job.job_id} label="Job ID" /></span>
      {job.page_count && <p>{job.completed_pages?.length || 0} of {job.page_count} pages saved for resume.</p>}
      {job.error && <p role="alert">{job.error}</p>}
      <div className="specialist-actions">
        <Button disabled={mutating || !['queued','running','interrupted'].includes(job.status) || job.desired_action === 'cancel'} onClick={() => void action('cancel')}>Cancel request</Button>
        <Button disabled={mutating || !['failed','interrupted'].includes(job.status) || job.desired_action === 'cancel' || job.attempt_count >= job.max_attempts} onClick={() => void action('retry')}>Retry request</Button>
      </div>
    </div>}
  </section>;
}

export function LayoutRegions({ result }: { result: SpecialistResult }) {
  return <>{result.pages?.filter(p => p.regions?.length).map(page => <section key={page.page} className="layout-regions">
    <h4>Page {page.page} · detected reading order</h4>
    <svg role="img" aria-label={`Page ${page.page} region map in normalized page pixels`} viewBox={`0 0 ${page.image_dimensions.join(' ')}`}>
      {page.regions?.map(region => <g key={region.region_id}>
        <title>{region.order}. {region.label} · {(region.confidence * 100).toFixed(1)}% · {region.text || 'Visual region'}</title>
        <rect x={region.box[0]} y={region.box[1]} width={region.box[2]-region.box[0]} height={region.box[3]-region.box[1]} />
        <text x={region.box[0]+5} y={region.box[1]+22}>{region.order}</text>
      </g>)}
    </svg>
    <ol>{page.regions?.map(region => <li key={region.region_id}><strong>{region.order}. {region.label}</strong> · {(region.confidence*100).toFixed(1)}%<br />{region.text || 'Visual region; no OCR text'}<br /><small>Box [{region.box.join(', ')}] in normalized RGB page pixels</small></li>)}</ol>
  </section>)}</>;
}
