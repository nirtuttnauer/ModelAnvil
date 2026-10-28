import { Identifier } from './Identifier';
import { Button, Card, Field, MultilineField } from './ui';
import { useResourceHandoff } from './ResourceHandoff';
import { useDraft, DraftStatus } from '../components/Draft';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources, type RegisteredModel } from '../api/resources';
import { ResourceState } from './ResourceState';

interface Evaluation { run_id: string; candidate_model_version: number; status: string; job?: string | null; execution_evidence?: { level: string } }
export function CandidateReview({ token, onCreated }: { token: string; onCreated: (id: string) => void }) {
  const draft = useDraft('release-review', { open: false as boolean, license: '', licenseSource: '', licenseNotice: '', name: '', candidate: '', evaluation: '', threshold: '0.8' });
  const [models, setModels] = useState<RegisteredModel[]>([]); const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [open, setOpen] = draft.field('open'); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const [license, setLicense] = draft.field('license'); const [licenseSource, setLicenseSource] = draft.field('licenseSource'); const [licenseNotice, setLicenseNotice] = draft.field('licenseNotice');
  const [name, setName] = draft.field('name'); const [candidate, setCandidate] = draft.field('candidate'); const [evaluation, setEvaluation] = draft.field('evaluation'); const [threshold, setThreshold] = draft.field('threshold');
  useEffect(() => {
    if (!open || !token.trim()) return;
    const controller = new AbortController(); setBusy(true); setError(null);
    Promise.all([allResources<RegisteredModel>('/api/v1/model-versions/', token, controller.signal), allResources<Evaluation>('/api/v1/evaluation-runs/', token, controller.signal)])
      .then(([m, e]) => { if (!controller.signal.aborted) { setModels(m); setEvaluations(e.filter(v => v.job && v.status === 'completed' && v.execution_evidence?.level === 'integrated_execution')); } })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [open, token]);
  async function create(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const version = await apiRequest<{ release_version_id: string }>('/api/v1/release-versions/create-candidate/', token, {
        method: 'POST', body: JSON.stringify({ name: name.trim(), candidate_model_version: candidate, evaluation_run: evaluation, min_accuracy: Number(threshold), ...(license ? { license_record: { spdx: license, source: licenseSource.trim(), notice: licenseNotice.trim() } } : {}) }) });
      onCreated(version.release_version_id); setOpen(false);
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const handoffError = useResourceHandoff(token, (kind, value) => { if (kind === 'model-version') { setCandidate(value.model_version_id || ''); setOpen(true); } });
  // Select UUIDs for the API, numeric record IDs only for matching existing evaluation foreign keys.
  const selected = models.find(m => m.model_version_id === candidate);
  const matching = evaluations.filter(e => e.candidate_model_version === selected?.id);
  return <Card className="panel"><div className="panel-title"><div><h2>Create reviewed candidate</h2><p>Freeze an actual trained candidate, its complete held-out evaluation and local export criteria.</p></div><Button className={open ? undefined : 'primary'} disabled={busy || !token.trim()} onClick={() => setOpen(v => !v)}>{open ? 'Close candidate setup' : 'New candidate release'}</Button></div>{open && <form className="form-grid" onSubmit={create}><DraftStatus draft={draft} disabled={busy} />
    <>{handoffError && <p role="alert">{handoffError}</p>}</><ResourceState loading={busy} error={error} />
    <label>Release name<Field required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label>
    <label>Reviewed candidate model<select required value={candidate} onChange={e => { setCandidate(e.target.value); setEvaluation(''); }}><option value="">Select a trained candidate</option>{models.filter(m => evaluations.some(e => e.candidate_model_version === m.id)).map(m => <option key={m.id} value={m.model_version_id}>{m.model_name} · r{m.revision_no}</option>)}</select></label>
    <label>Exact candidate evaluation<select required value={evaluation} onChange={e => setEvaluation(e.target.value)}><option value="">Select a complete evaluation</option>{matching.map((e, index) => <option key={e.run_id} value={e.run_id}>Evaluation {index + 1} · {e.status}</option>)}</select></label>
    <Identifier value={evaluation} label="Candidate evaluation ID" /><label>Minimum held-out accuracy<Field required type="number" min="0" max="1" step="0.01" value={threshold} onChange={e => setThreshold(e.target.value)} /></label>
    <label>License evidence (optional)<select value={license} onChange={e => setLicense(e.target.value)}><option value="">Use recorded model license</option><option value="mit">MIT</option><option value="apache-2.0">Apache 2.0</option><option value="bsd-3-clause">BSD 3-Clause</option><option value="open-rail">Open RAIL</option></select></label>
    {license && <><label>License source or authority<Field required maxLength={4000} value={licenseSource} onChange={e => setLicenseSource(e.target.value)} /></label><label className="full-width">License notice<MultilineField required maxLength={4000} value={licenseNotice} onChange={e => setLicenseNotice(e.target.value)} /></label></>}
    <p className="muted full-width">The review freezes measured quality, baseline regression, recorded license and training provenance. Missing or failing criteria stay visible. Download includes actual weights and a standalone CPU consumer; local review does not grant production qualification.</p>
    {!evaluations.length && !busy && <p className="muted full-width">Complete a durable evaluation of a trained CPU candidate first. <a href="#evaluation">Open Evaluation</a></p>}
    <Button className="primary" disabled={busy || !name.trim() || !candidate || !evaluation}>Freeze candidate review</Button>
  </form>}</Card>;
}
