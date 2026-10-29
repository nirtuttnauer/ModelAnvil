import { Badge, Button, Dialog, Disclosure, KeyValueList, Notice, RecordTable, Section, Select, StatusBadge, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { Identifier } from '../components/Identifier';
import { runHash } from '../api/runs';
import { ReleaseGateChecklist } from '../components/ReleaseGateChecklist';
import { InspectorPanel } from '../components/InspectorPanel';
import { DataInspector } from '../components/DataInspector';
import React from 'react';
import { apiPage, apiRequest, errorMessage, apiDownload } from '../api/client';
import { CandidateReview } from '../components/CandidateReview';
import { ResourceState } from '../components/ResourceState';
import { statusLabel } from '../api/status';
import { ChartPanel, ChartEmpty, SegmentBar } from '../components/Charts';
import './operations.css';

interface ReleaseVersion {
  release_version_id: string; revision_no: number; release: number; status: string; recorded_status?: string;
  candidate_type?: string; candidate_ref?: string; model_version?: number | null; manifest_digest?: string; created_at?: string;
  local_review?: { state: string; criteria: { key: string; required: unknown; actual: unknown; passed: boolean }[]; evaluation_run: string; production_qualified: boolean }; execution_evidence?: unknown; gate_results?: unknown; model_card?: unknown;
}
interface ServingEndpoint {
  endpoint_id: string; endpoint_key: string; name: string; created_at?: string; updated_at?: string;
  deployments?: unknown[]; active_deployment: { deployment_id: string; release_version: number; release_version_id: string; revision_no: number; readiness_state: string; recorded_readiness_state?: string; execution_evidence?: unknown } | null;
}

interface ReleasesPageProps {
  token?: string;
  refreshKey?: number;
}

export function ReleasesPage({ token, refreshKey = 0 }: ReleasesPageProps) {
  const endpointFormId = React.useId();
  const [endpoints, setEndpoints] = React.useState<ServingEndpoint[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [showModal, setShowModal] = React.useState(false);
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [newKey, setNewKey] = React.useState('');
  const [newName, setNewName] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [releaseVersions, setReleaseVersions] = React.useState<ReleaseVersion[]>([]);
  const [releaseVersion, setReleaseVersion] = React.useState(() => new URLSearchParams(window.location.hash.split('?')[1]).get('release_version') || '');
  const [sbomBusy, setSbomBusy] = React.useState(false);
  const [sbomJson, setSbomJson] = React.useState<string | null>(null);
  const [sbomEvidence, setSbomEvidence] = React.useState<{ verified?: boolean; warnings?: string[] } | null>(null);

  const fetchEndpoints = React.useCallback(async () => {
    if (!token?.trim()) {
      setLoading(false);
      setEndpoints([]); setReleaseVersions([]); setReleaseVersion(''); setSbomJson(null);
      return;
    }
    setLoading(true); setError(null);
    try {
      const [page, versions] = await Promise.all([apiPage<ServingEndpoint>('/api/v1/serving-endpoints/', token), apiPage<ReleaseVersion>('/api/v1/release-versions/', token)]);
      setEndpoints(page.results); setReleaseVersions(versions.results);
    } catch (err) { setEndpoints([]); setReleaseVersions([]); setError(errorMessage(err)); }
    finally { setLoading(false); }

  }, [token, refreshKey]);

  React.useEffect(() => { setSbomJson(null); setNotice(null); }, [token]);

  React.useEffect(() => {
    fetchEndpoints();
  }, [fetchEndpoints, refreshKey]);

  async function handleCreateEndpoint(e: React.FormEvent) {
    e.preventDefault();
    if (!token?.trim() || !newKey.trim()) return;
    setSubmitting(true); setError(null);
    try {
      await apiRequest('/api/v1/serving-endpoints/', token, { method: 'POST',
        body: JSON.stringify({ endpoint_key: newKey.trim(), name: newName.trim() || newKey.trim() }) });
      setShowModal(false); setNewKey(''); setNewName('');
      setNotice(`Serving endpoint "${newKey}" created. Deploy a reviewed candidate to check readiness.`);
      await fetchEndpoints();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGenerateSbom(saveArtifact = false) {
    if (!releaseVersion) return;
    setSbomBusy(true); setError(null);
    try {
      const report = await apiRequest<{spdx_document: unknown; verified?: boolean; warnings?: string[]; sbom_artifact?: {artifact_id: string}}>(`/api/v1/release-versions/${releaseVersion}/sbom/`, token || '', saveArtifact ? {method: 'POST', body: '{}'} : {});
      setSbomJson(JSON.stringify(report.spdx_document, null, 2));
      setSbomEvidence(report);
      if (report.sbom_artifact) setNotice(`SPDX document saved as committed artifact ${report.sbom_artifact.artifact_id}.`);
    } catch (err) { setError(errorMessage(err)); } finally { setSbomBusy(false); }
  }
  function downloadSbom() {
    if (!sbomJson) return;
    const url = URL.createObjectURL(new Blob([sbomJson], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = `release-${releaseVersion}.spdx.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function downloadReleaseBundle() {
    if (!releaseVersion) return;
    setSbomBusy(true); setError(null);
    try {
      if (selected?.local_review) {
        const archive = await apiDownload(`/api/v1/release-versions/${releaseVersion}/download/`, token || '');
        const url = URL.createObjectURL(archive); const link = document.createElement('a');
        link.href = url; link.download = `candidate-${releaseVersion}.zip`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        setNotice('Downloaded reviewed weights, tokenizer, configuration, hashes, notices and standalone CPU consumer.'); return;
      }
      const bundle = await apiRequest<{model_bundle?: unknown}>(`/api/v1/release-versions/${releaseVersion}/export-bundle/`, token || '');
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = `release-${releaseVersion}.bundle.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(bundle.model_bundle ? 'Downloaded release bundle with committed model bytes and local loading verification.' : 'Downloaded release metadata. This candidate has no committed model weights.');
    } catch (err) { setError(errorMessage(err)); } finally { setSbomBusy(false); }
  }

  async function servingAction(endpoint: ServingEndpoint, action: 'deploy-local' | 'rollback' | 'local-health' | 'completions') {
    setSubmitting(true); setError(null);
    try {
      const result = await apiRequest<{ state?: string; readiness_state?: string; text?: string; production_qualified?: boolean }>(`/api/v1/serving-endpoints/${endpoint.endpoint_id}/${action}/`, token || '',
        action === 'local-health' ? {} : { method: 'POST', body: JSON.stringify(action === 'deploy-local' ? { release_version_id: releaseVersion } : action === 'completions' ? { prompt: 'x', max_tokens: 2 } : {}) });
      setNotice(`${endpoint.name}: ${action} ${result.state || result.readiness_state || 'completed'}${result.text !== undefined ? ` · output ${result.text}` : ''}. Local CPU scope only.`);
      await fetchEndpoints();
    } catch(e) { await fetchEndpoints(); setError(errorMessage(e)); } finally { setSubmitting(false); }
  }
  const selected = releaseVersions.find(v => v.release_version_id === releaseVersion);
  const states = [...new Set(releaseVersions.map(v => v.status))].map(label => ({ label: statusLabel(label), value: releaseVersions.filter(v => v.status === label).length }));
  const linkedEndpoints = selected ? endpoints.filter(ep => ep.active_deployment?.release_version_id === selected.release_version_id) : [];
  const ready = !!token?.trim();
  const sbomDisabled = !releaseVersion || sbomBusy || !ready;
  function choose(id: string) { setReleaseVersion(id); setSbomJson(null); }

  return <div className="ops-page">
    <Section title="Release versions" description="Candidate records and their reported states." actions={<>
      <Select aria-label="Release version for SBOM" value={releaseVersion} onChange={e => choose(e.target.value)}>
        <option value="">Select a release version</option>{releaseVersions.map(v => <option key={v.release_version_id} value={v.release_version_id}>Release · r{v.revision_no} · {statusLabel(v.status)}</option>)}
      </Select>
      <Button type="button" variant="primary" disabled={!ready || submitting} onClick={() => setReviewOpen(true)}>New candidate release</Button>
      <Button type="button" disabled={!ready || submitting} onClick={() => setShowModal(true)}>New endpoint</Button>
    </>}>
      {notice && <Notice tone="success" role="status">{notice}</Notice>}
      <ResourceState loading={loading && !releaseVersions.length} error={error} onRetry={() => void fetchEndpoints()} />
      <div data-ui="split" data-open={selected ? '' : undefined}>
        <div className="ops-main">
          {!loading && !error && !releaseVersions.length && <EmptyState title="No release versions" description={ready ? 'Review a completed CPU candidate and its evaluation to create one.' : 'Connect with an API key to load the release registry.'} />}
          {!!releaseVersions.length && <div className="table-scroll" tabIndex={0}><RecordTable>
            <thead><tr><th>Version</th><th>Candidate</th><th>State</th><th>Created</th></tr></thead>
            <tbody>{releaseVersions.map(v => <tr key={v.release_version_id} aria-selected={selected === v || undefined}>
              <td><Button type="button" variant="quiet" size="sm" onClick={() => choose(v.release_version_id)}>Release · r{v.revision_no}</Button></td>
              <td>{v.candidate_type || 'Not reported'}</td>
              <td><StatusBadge status={v.status} />{v.recorded_status && v.recorded_status !== v.status && <small>Recorded state: {statusLabel(v.recorded_status)}</small>}</td>
              <td>{v.created_at ? new Date(v.created_at).toLocaleString() : 'Not reported'}</td>
            </tr>)}</tbody>
          </RecordTable></div>}
        </div>
        {selected && <InspectorPanel key={selected.release_version_id} eyebrow="Release" title={`Release · r${selected.revision_no}`} closeLabel="Close release details" onClose={() => choose('')}>
          <div data-ui="actions"><StatusBadge status={selected.status} /></div>
          <KeyValueList items={[
            { label: 'Reported state', value: statusLabel(selected.status) },
            { label: 'Recorded state', value: statusLabel(selected.recorded_status || selected.status) },
            { label: 'Candidate type', value: selected.candidate_type || 'Not reported' },
            { label: 'Candidate reference', value: selected.candidate_ref ? <Identifier value={selected.candidate_ref} label="Candidate reference" display="code" /> : 'Not reported' },
            { label: 'Model version', value: selected.model_version ? <Identifier value={selected.model_version} label="Model version record ID" display="code" /> : 'Not linked' },
            { label: 'Linked endpoint records', value: `${linkedEndpoints.length} in loaded page` },
            { label: 'Manifest digest', value: selected.manifest_digest ? <Identifier value={selected.manifest_digest} label="Manifest SHA-256" display="code" /> : 'Not reported' },
            { label: 'Release version ID', value: <Identifier value={selected.release_version_id} label="Release version ID" display="code" /> },
          ]} />
          {selected.local_review && <ReleaseGateChecklist criteria={selected.local_review.criteria} state={selected.local_review.state} evidenceHref={runHash('evaluation', selected.local_review.evaluation_run)} />}
          <div data-ui="actions">
            <Button type="button" size="sm" disabled={sbomDisabled} onClick={() => void handleGenerateSbom()}>{sbomBusy ? 'Loading…' : 'View SPDX SBOM'}</Button>
            <Button type="button" size="sm" disabled={sbomDisabled} onClick={() => void handleGenerateSbom(true)}>Save SPDX artifact</Button>
            <Button type="button" size="sm" disabled={sbomDisabled} onClick={downloadReleaseBundle}>Download release bundle</Button>
          </div>
          <Disclosure summary="Recorded execution evidence" variant="quiet" open>{selected.execution_evidence ? <DataInspector value={selected.execution_evidence} /> : <p className="muted">No execution evidence was returned.</p>}</Disclosure>
          <Disclosure summary="Recorded gate results" variant="quiet"><DataInspector value={selected.gate_results ?? []} /></Disclosure>
          <Disclosure summary="Model card" variant="quiet"><DataInspector value={selected.model_card ?? {}} /></Disclosure>
          <p className="ops-footnote">Recorded gates and endpoint pointers do not establish live serving or production qualification.</p>
        </InspectorPanel>}
      </div>
    </Section>
    {sbomJson && <Section title="Software bill of materials" description="SPDX 2.3 document for the selected release version." actions={<><Button type="button" onClick={downloadSbom}>Download JSON</Button><Button type="button" variant="quiet" onClick={() => setSbomJson(null)}>Close</Button></>}>
      <p className="muted">{sbomEvidence?.verified ? 'Model byte checksums verified against the committed bundle.' : 'Metadata inventory; model bytes are unverified.'}</p>
      {sbomEvidence?.warnings?.map(warning => <p className="muted" key={warning}>{warning}</p>)}
      <DataInspector value={JSON.parse(sbomJson)} title="Software inventory" />
    </Section>}
    <Section title="Serving endpoints" description="Local CPU serving records. Check live health after interruptions.">
      {endpoints.length ? <div className="ops-endpoints">{endpoints.map(ep => <article key={ep.endpoint_id} className="ops-endpoint">
        <div data-ui="actions"><h3>{ep.name || ep.endpoint_key}</h3><Badge tone={ep.active_deployment ? 'success' : 'neutral'}>{ep.active_deployment ? 'Pointer recorded' : 'No pointer'}</Badge></div>
        <KeyValueList items={[
          { label: 'Deployment revision', value: ep.active_deployment ? `Rev ${ep.active_deployment.revision_no}` : 'None' },
          { label: 'Last startup readiness', value: ep.active_deployment?.readiness_state ? statusLabel(ep.active_deployment.readiness_state) : 'Not reported' },
          ...(ep.active_deployment?.recorded_readiness_state && ep.active_deployment.recorded_readiness_state !== ep.active_deployment.readiness_state ? [{ label: 'Recorded readiness', value: statusLabel(ep.active_deployment.recorded_readiness_state) }] : []),
          { label: 'Updated', value: ep.updated_at ? new Date(ep.updated_at).toLocaleString() : 'Not reported' },
          { label: 'Endpoint ID', value: <Identifier value={ep.endpoint_id} label="Endpoint ID" display="code" /> },
        ]} />
        <div data-ui="actions">
          <Button type="button" size="sm" disabled={submitting || !selected?.local_review || selected.local_review.state !== 'approved'} onClick={() => void servingAction(ep, 'deploy-local')}>Deploy selected locally</Button>
          <Button type="button" size="sm" disabled={submitting || !ep.active_deployment} onClick={() => void servingAction(ep, 'local-health')}>Check live health</Button>
          <Button type="button" size="sm" disabled={submitting || !ep.active_deployment} onClick={() => void servingAction(ep, 'completions')}>Test inference</Button>
          <Button type="button" size="sm" disabled={submitting || !ep.active_deployment} onClick={() => void servingAction(ep, 'rollback')}>Roll back locally</Button>
        </div>
        {ep.deployments && <Disclosure summary="Deployment history" variant="quiet"><DataInspector value={ep.deployments} /></Disclosure>}
        {ep.active_deployment && <Disclosure summary="Linked version and evidence" variant="quiet"><DataInspector value={ep.active_deployment} /></Disclosure>}
      </article>)}</div> : !loading && !error && <EmptyState title="No serving endpoints" description="Create an endpoint record to track release deployment metadata." />}
    </Section>
    <Disclosure summary="Insights" variant="card"><div className="ops-charts">
      <ChartPanel title="Reported release states" description={`${releaseVersions.length} versions in the loaded page. Backend state does not certify production readiness.`}>{releaseVersions.length ? <SegmentBar data={states} unit="versions" /> : <ChartEmpty message="Create a candidate review to see its reported state." />}</ChartPanel>
      <ChartPanel title="Recorded release references" description={selected ? `Release revision ${selected.revision_no}` : 'Select a release version to inspect its recorded references.'}>
        {selected ? <KeyValueList items={[
          { label: selected.candidate_type || 'Candidate', value: selected.candidate_ref ? <Identifier value={selected.candidate_ref} label="Candidate reference" display="code" /> : 'Reference not reported' },
          { label: 'Release', value: <Identifier value={selected.release_version_id} label="Release version ID" display="code" /> },
          { label: 'Revision', value: `${selected.revision_no} · ${statusLabel(selected.status)}` },
        ]} /> : <ChartEmpty message="Choose a version from the list above." />}
      </ChartPanel>
    </div></Disclosure>
    <CandidateReview token={token || ''} open={reviewOpen} onOpen={() => setReviewOpen(true)} onClose={() => setReviewOpen(false)} onCreated={id => { choose(id); setNotice('Candidate review frozen. Inspect each criterion before downloading.'); void fetchEndpoints(); }} />
    <Dialog title="New serving endpoint" description="Creates an endpoint record. Deploy a reviewed candidate to it, then check its health." open={showModal} onClose={() => setShowModal(false)}
      footer={<><Button type="button" disabled={submitting} onClick={() => setShowModal(false)}>Cancel</Button><Button form={endpointFormId} type="submit" variant="primary" disabled={submitting || !ready || !newKey.trim()}>{submitting ? 'Creating…' : 'Create endpoint'}</Button></>}>
      <form id={endpointFormId} data-ui="form" onSubmit={handleCreateEndpoint}>
        <div data-ui="field-grid">
          <TextControl label="Endpoint key" placeholder="svg-generation-primary" value={newKey} onChange={e => setNewKey(e.target.value)} required />
          <TextControl label="Display name" placeholder="SVG generation primary" value={newName} onChange={e => setNewName(e.target.value)} />
        </div>
      </form>
    </Dialog>
  </div>;
}
