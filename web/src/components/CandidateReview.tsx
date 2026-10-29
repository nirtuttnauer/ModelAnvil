import { Button, Dialog, MultilineField, Notice, Select, TextControl } from './ui';
import { useResourceHandoff } from './ResourceHandoff';
import { useDraft, DraftIndicator } from '../components/Draft';
import { useEffect, useId, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources, type RegisteredModel } from '../api/resources';
import { ResourceState } from './ResourceState';

interface Evaluation { run_id: string; candidate_model_version: number; status: string; job?: string | null; execution_evidence?: { level: string } }

/** Freezes a trained candidate with its held-out evaluation into a release version, in a dialog. */
export function CandidateReview({ token, open, onOpen, onClose, onCreated }: { token: string; open: boolean; onOpen: () => void; onClose: () => void; onCreated: (id: string) => void }) {
  const formId = useId(), noticeId = useId();
  const draft = useDraft('release-review', { open: false as boolean, license: '', licenseSource: '', licenseNotice: '', name: '', candidate: '', evaluation: '', threshold: '0.8' });
  const [models, setModels] = useState<RegisteredModel[]>([]); const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
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
      onCreated(version.release_version_id); onClose();
    } catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const handoffError = useResourceHandoff(token, (kind, value) => { if (kind === 'model-version') { setCandidate(value.model_version_id || ''); onOpen(); } });
  // Select UUIDs for the API, numeric record IDs only for matching existing evaluation foreign keys.
  const selected = models.find(m => m.model_version_id === candidate);
  const matching = evaluations.filter(e => e.candidate_model_version === selected?.id);
  return <Dialog title="New candidate release" description="Freeze a trained candidate with its held-out evaluation and export criteria." open={open} onClose={onClose} size="lg"
    footer={<><Button type="button" disabled={busy} onClick={onClose}>Cancel</Button><Button form={formId} type="submit" variant="primary" disabled={busy || !name.trim() || !candidate || !evaluation}>Freeze candidate review</Button></>}>
    <form id={formId} data-ui="form" onSubmit={create}>
      <DraftIndicator draft={draft} disabled={busy} />
      {handoffError && <p role="alert" className="error-text">{handoffError}</p>}
      {error && <Notice tone="error" role="alert">{error}</Notice>}
      <ResourceState loading={busy && !models.length} />
      <div data-ui="field-grid">
        <TextControl label="Release name" required maxLength={200} value={name} onChange={e => setName(e.target.value)} />
        <TextControl label="Minimum held-out accuracy" required type="number" min="0" max="1" step="0.01" value={threshold} onChange={e => setThreshold(e.target.value)} />
        <Select label="Reviewed candidate model" required value={candidate} onChange={e => { setCandidate(e.target.value); setEvaluation(''); }}>
          <option value="">Select a trained candidate</option>{models.filter(m => evaluations.some(e => e.candidate_model_version === m.id)).map(m => <option key={m.id} value={m.model_version_id}>{m.model_name} · r{m.revision_no}</option>)}
        </Select>
        <Select label="Exact candidate evaluation" required value={evaluation} onChange={e => setEvaluation(e.target.value)}>
          <option value="">Select a complete evaluation</option>{matching.map((e, index) => <option key={e.run_id} value={e.run_id}>Evaluation {index + 1} · {e.status}</option>)}
        </Select>
        <Select label="License evidence (optional)" value={license} onChange={e => setLicense(e.target.value)}
          options={[{ value: '', label: 'Use recorded model license' }, { value: 'mit', label: 'MIT' }, { value: 'apache-2.0', label: 'Apache 2.0' }, { value: 'bsd-3-clause', label: 'BSD 3-Clause' }, { value: 'open-rail', label: 'Open RAIL' }]} />
        {license && <>
          <TextControl label="License source or authority" required maxLength={4000} value={licenseSource} onChange={e => setLicenseSource(e.target.value)} />
          <div data-ui="control" data-span="full"><label data-ui="control-label" htmlFor={noticeId}>License notice</label><MultilineField id={noticeId} required maxLength={4000} value={licenseNotice} onChange={e => setLicenseNotice(e.target.value)} /></div>
        </>}
      </div>
      <p className="muted">The review freezes measured quality, baseline regression, license and training provenance. Local review does not grant production qualification.</p>
      {!evaluations.length && !busy && <p className="muted">Complete a durable evaluation of a trained CPU candidate first. <a href="#evaluation">Open Evaluation</a></p>}
    </form>
  </Dialog>;
}
