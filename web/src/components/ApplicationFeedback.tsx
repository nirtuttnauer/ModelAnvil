import { useEffect, useState } from 'react';
import { allResources } from '../api/resources';
import { apiRequest, errorMessage } from '../api/client';
import { Button, Checkbox, Disclosure, KeyValueList, MultilineControl, Notice, Section, Select, StatusBadge, TextControl } from './ui';
import { EmptyState, Feedback } from './Feedback';
import { Identifier } from './Identifier';
interface Policy { enabled: boolean; collect_content: boolean; retention_days: number; privacy_maximum_days: number; can_administer: boolean }
interface Receipt { feedback_id: string; model_version_id: string; application: string; application_version: string; source_id: string; source_group_id: string; verdict: string; rubric: string; evaluation_role: string; content_collected: boolean; campaign_id?: string; review_state: string; cleanup_pending: boolean; expires_at: string }
interface Model { model_version_id: string; model_name: string; revision_no: number }
export function ApplicationFeedback({ token, refreshKey, reviewOnly, onReview, onDeleted }: { token: string; refreshKey: number; reviewOnly: boolean; onReview: (id: string) => void; onDeleted: (campaignId?: string) => void }) {
  const [policy, setPolicy] = useState<Policy | null>(null), [receipts, setReceipts] = useState<Receipt[]>([]), [models, setModels] = useState<Model[]>([]);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [retry, setRetry] = useState(0);
  const [enabled, setEnabled] = useState(false), [allowContent, setAllowContent] = useState(false), [days, setDays] = useState('30');
  const [application, setApplication] = useState(''), [version, setVersion] = useState(''), [eventId, setEventId] = useState(''), [model, setModel] = useState('');
  const [source, setSource] = useState(''), [group, setGroup] = useState(''), [rubric, setRubric] = useState(''), [verdict, setVerdict] = useState('failure'), [role, setRole] = useState('development');
  const [authorized, setAuthorized] = useState(false), [consent, setConsent] = useState(false), [prompt, setPrompt] = useState(''), [prediction, setPrediction] = useState('');
  useEffect(() => { setPrompt(''); setPrediction(''); setConsent(false); setAuthorized(false); setNotice(''); }, [token, refreshKey]);
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(''); setReceipts([]); setPolicy(null);
    Promise.all([apiRequest<Policy>('/api/v1/application-feedback/policy/', token, { signal: c.signal }), allResources<Receipt>('/api/v1/application-feedback/', token, c.signal), allResources<Model>('/api/v1/model-versions/', token, c.signal)])
      .then(([p, r, m]) => { if (!c.signal.aborted) { setPolicy(p); setEnabled(p.enabled); setAllowContent(p.collect_content); setDays(String(p.retention_days)); setReceipts(r); setModels(m); } })
      .catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, refreshKey, retry]);
  async function savePolicy(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const p = await apiRequest<Policy>('/api/v1/application-feedback/policy/', token, { method: 'POST', body: JSON.stringify({ enabled, collect_content: allowContent, retention_days: Number(days) }) }); setPolicy(p); setRetry(v => v + 1); setNotice('Feedback collection settings saved. Shorter retention also applies to existing receipts.'); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function ingest(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try { const receipt = await apiRequest<Receipt>('/api/v1/application-feedback/', token, { method: 'POST', body: JSON.stringify({ application, application_version: version, event_id: eventId, model_version: model, source_id: source, source_group_id: group, rubric, verdict, evaluation_role: role, authorized, content_consent: consent, ...(consent ? { content: { prompt, prediction } } : {}) }) }); setPrompt(''); setPrediction(''); setConsent(false); setAuthorized(false); setEventId(''); setRetry(v => v + 1); setNotice(receipt.campaign_id ? 'Failure opened as an unreviewed correction candidate. The original prediction is preserved.' : 'Minimal feedback receipt recorded. No prompt or prediction was collected.'); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function erase(receipt: Receipt) {
    if (!window.confirm('Delete this feedback, its owned review content and published source artifacts? Existing copies already exported outside this installation cannot be recalled.')) return;
    setBusy(true); setError('');
    try { const result = await apiRequest<{cleanup_pending:boolean}>(`/api/v1/application-feedback/${receipt.feedback_id}/`, token, { method: 'DELETE' }); onDeleted(receipt.campaign_id); setRetry(v => v + 1); setNotice(result.cleanup_pending ? 'Feedback is unavailable. Storage cleanup is pending; erase expired feedback retries it.' : 'Feedback content erased. Its published source artifacts are unavailable for further training.'); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function purge() {
    setBusy(true); setError('');
    try { const result = await apiRequest<{ deleted_feedback: number }>('/api/v1/application-feedback/purge/', token, { method: 'POST', body: JSON.stringify({ confirm: 'delete_expired_feedback' }) }); onDeleted(); setRetry(v => v + 1); setNotice(`${result.deleted_feedback} expired feedback receipts erased with their owned review and source artifacts.`); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <Section title="Private application feedback" description="Turn authorized development failures into reviewed corrections." actions={<Button type="button" disabled={loading || busy} onClick={() => setRetry(v => v + 1)}>Refresh feedback</Button>}>
    {error && <Notice tone="error" role="alert">{error}</Notice>}{notice && <Notice tone="success" role="status">{notice}</Notice>}{loading && <Feedback state="loading" title="Loading feedback collection…" />}
    {policy && <><p>Collection is {policy.enabled ? 'enabled' : 'disabled'}. Default collection stores application/model versions, pseudonymous source IDs and rubric feedback. Prompts and predictions require project opt-in and consent for each event. Raw feedback and its owned review/source artifacts expire after {policy.retention_days} days; protected final-test groups cannot enter training.</p>
      {policy.can_administer && <Disclosure summary="Feedback collection and retention" variant="quiet"><form data-ui="form" onSubmit={savePolicy}>
        <Checkbox label="Enable application feedback collection" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
        <Checkbox label="Allow explicitly consented prompts and predictions" checked={allowContent} onChange={e => setAllowContent(e.target.checked)} />
        <div data-ui="field-grid"><TextControl label="Feedback retention days" required type="number" min="1" max={policy.privacy_maximum_days} value={days} onChange={e => setDays(e.target.value)} hint={`The project Privacy limit is ${policy.privacy_maximum_days} days. Reducing retention shortens existing receipts; increasing it does not extend them.`} /></div>
        <div data-ui="actions"><Button variant="primary" disabled={busy}>Save feedback settings</Button><Button type="button" disabled={busy} onClick={() => void purge()}>Erase expired feedback content</Button></div>
      </form></Disclosure>}
      {!reviewOnly && <Disclosure summary="Import authorized feedback" variant="quiet"><form data-ui="form" onSubmit={ingest}>
        <div data-ui="field-grid">
          <TextControl label="Application name" required maxLength={128} value={application} onChange={e => setApplication(e.target.value)} />
          <TextControl label="Application version" required maxLength={128} value={version} onChange={e => setVersion(e.target.value)} />
          <TextControl label="Application event ID" required maxLength={128} value={eventId} onChange={e => setEventId(e.target.value)} hint="Reuse the same ID when retrying the same event." />
          <Select label="Original model version" required value={model} onChange={e => setModel(e.target.value)}><option value="">Choose the actual application model</option>{models.map(m => <option key={m.model_version_id} value={m.model_version_id}>{m.model_name} · r{m.revision_no}</option>)}</Select>
          <TextControl label="Pseudonymous source ID" required maxLength={128} value={source} onChange={e => setSource(e.target.value)} />
          <TextControl label="Related source group" required maxLength={128} value={group} onChange={e => setGroup(e.target.value)} />
          <div data-span="full"><MultilineControl label="Rubric or feedback rule" required rows={3} maxLength={2000} value={rubric} onChange={e => setRubric(e.target.value)} /></div>
          <Select label="Observed result" value={verdict} onChange={e => { setVerdict(e.target.value); setConsent(false); setPrompt(''); setPrediction(''); }} options={[{ value: 'failure', label: 'Development failure' }, { value: 'success', label: 'Success · metadata only' }]} />
          <Select label="Original evaluation role" value={role} onChange={e => { setRole(e.target.value); setConsent(false); setPrompt(''); setPrediction(''); }} options={[{ value: 'development', label: 'Development' }, { value: 'final_test', label: 'Final test · protected, metadata only' }]} />
          {policy.collect_content && verdict === 'failure' && role === 'development' && <div data-span="full"><Checkbox label="I have explicit consent to store this event’s prompt and original prediction for correction review." checked={consent} onChange={e => { setConsent(e.target.checked); if (!e.target.checked) { setPrompt(''); setPrediction(''); } }} /></div>}
          {consent && <><div data-span="full"><MultilineControl label="Original application prompt" required rows={4} maxLength={16000} value={prompt} onChange={e => setPrompt(e.target.value)} /></div><div data-span="full"><MultilineControl label="Original application prediction (empty output allowed)" rows={4} maxLength={16000} value={prediction} onChange={e => setPrediction(e.target.value)} /></div></>}
          <div data-span="full"><Checkbox label="I am authorized to import this feedback into the selected project." checked={authorized} onChange={e => setAuthorized(e.target.checked)} /></div>
        </div>
        <p className="muted">Content is held only in this form’s memory until submission. Failure content opens an unreviewed Annotation candidate. Only a human correction can enter a new training snapshot; inspected groups cannot become clean protected tests.</p>
        <div data-ui="actions"><Button variant="primary" disabled={busy || !policy.enabled || !authorized}>Import application feedback</Button></div>
      </form></Disclosure>}
    </>}
    {!loading && !receipts.length && <EmptyState title="No application feedback in this project" description="Imported receipts and their review state appear here." />}
    {receipts.map(receipt => <Disclosure key={receipt.feedback_id} variant="plain" aria-label={`Feedback receipt ${receipt.feedback_id}`}
      summary={<span data-ui="actions"><span>{receipt.application || 'Erased feedback'}{receipt.application_version ? ` · ${receipt.application_version}` : ''}</span><StatusBadge status={receipt.review_state} /></span>}>
      <KeyValueList items={[
        { label: 'Feedback receipt', value: <Identifier value={receipt.feedback_id} label="Feedback receipt ID" display="code" /> },
        { label: 'Original model version', value: <Identifier value={receipt.model_version_id} label="Original model version ID" display="code" /> },
        { label: 'Result', value: `${receipt.verdict} · ${receipt.evaluation_role.replaceAll('_', ' ')} · ${receipt.content_collected ? 'content consent recorded' : 'metadata only'}` },
        ...(receipt.source_group_id ? [{ label: 'Source group', value: receipt.source_group_id }] : []),
        ...(receipt.rubric ? [{ label: 'Rubric', value: receipt.rubric }] : []),
        { label: 'Content expires', value: new Date(receipt.expires_at).toLocaleString() },
      ]} />
      {receipt.cleanup_pending && <Notice tone="caution" role="status">Storage erasure pending. Run expired feedback cleanup to retry.</Notice>}
      <div data-ui="actions">{receipt.campaign_id && <Button type="button" onClick={() => onReview(receipt.campaign_id!)}>Review application correction</Button>}{policy?.can_administer && receipt.review_state !== 'deleted' && <Button type="button" disabled={busy} onClick={() => void erase(receipt)}>Delete feedback content</Button>}</div>
    </Disclosure>)}
  </Section>;
}
