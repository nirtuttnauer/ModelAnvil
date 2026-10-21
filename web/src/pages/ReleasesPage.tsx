import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field, Notice, RecordTable } from '../components/ui';
import { runHash } from '../api/runs';
import { ReleaseGateChecklist } from '../components/ReleaseGateChecklist';
import { InspectorPanel } from '../components/InspectorPanel';
import { DataInspector } from '../components/DataInspector';
import React from 'react';
import { apiPage, apiRequest, errorMessage, apiDownload } from '../api/client';
import { CandidateReview } from '../components/CandidateReview';
import { ResourceState } from '../components/ResourceState';
import { Rocket, Plus, FileText, CheckCircle2, ArrowRight, Box, X } from 'lucide-react';
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
  const [endpoints, setEndpoints] = React.useState<ServingEndpoint[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [showModal, setShowModal] = React.useState(false);
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
  const states = [...new Set(releaseVersions.map(v => v.status))].map(label => ({ label, value: releaseVersions.filter(v => v.status === label).length }));
  const linkedEndpoints = selected ? endpoints.filter(ep => ep.active_deployment?.release_version_id === selected.release_version_id) : [];
  return <div className="resource-view releases-view operations-page">
    <div className="ops-heading"><div><span className="eyebrow">Release registry</span><h2>Candidate review</h2><p>Inspect candidate versions, endpoint records and recorded release evidence.</p></div><Button disabled={!token?.trim() || submitting} aria-expanded={showModal} onClick={() => setShowModal(v => !v)}><Plus size={16} aria-hidden="true" />New Endpoint</Button></div>
    <Notice as="p" className="notice">Reviewed CPU candidates export actual verified model bytes. Other exports may contain metadata only. Local CPU serving is available after a passing frozen review and actual readiness probe. Production qualification remains unavailable.</Notice>
    <ResourceState loading={loading} error={error} onRetry={() => void fetchEndpoints()} />
    {notice && <Notice tone="success" className="notice success" role="status"><CheckCircle2 size={16} aria-hidden="true" />{notice}</Notice>}
    {showModal && <Card className="panel"><div className="panel-title"><div><h2>Create serving endpoint</h2><p>Creates an endpoint record. Select a reviewed candidate, deploy locally and check actual service health.</p></div><Button className="icon-button" aria-label="Close endpoint form" disabled={submitting} onClick={() => setShowModal(false)}><X size={17} aria-hidden="true" /></Button></div><form onSubmit={handleCreateEndpoint} className="form-grid"><label htmlFor="endpoint-key">Endpoint Key<Field type="text" id="endpoint-key" placeholder="e.g. svg-generation-primary" value={newKey} onChange={e => setNewKey(e.target.value)} required /></label><label htmlFor="endpoint-name">Display Name<Field type="text" id="endpoint-name" placeholder="e.g. SVG Generation Primary Cluster" value={newName} onChange={e => setNewName(e.target.value)} /></label><div className="full-width actions"><Button className="primary" type="submit" disabled={submitting || !token?.trim() || !newKey.trim()}>{submitting ? 'Creating...' : 'Create Endpoint'}</Button><Button type="button" disabled={submitting} onClick={() => setShowModal(false)}>Cancel</Button></div></form></Card>}
    <CandidateReview token={token || ''} onCreated={id => { setReleaseVersion(id); setNotice('Candidate review frozen. Inspect each criterion before downloading.'); void fetchEndpoints(); }} />
    <details className="workspace-details"><summary>Release overview and references</summary><div className="ops-chart-grid">
      <ChartPanel title="Reported release states" description={`${releaseVersions.length} versions in the loaded page · backend state does not certify production readiness.`}>{releaseVersions.length ? <SegmentBar data={states} unit="versions" /> : <ChartEmpty message="Create a candidate review to see its reported state." />}</ChartPanel>
      <ChartPanel title="Recorded release references" description={selected ? `Release revision ${selected.revision_no}` : 'Select a release version to inspect its recorded references.'}>
        {selected ? <div className="ops-release-lineage"><div><Box size={20} aria-hidden="true" /><small>{selected.candidate_type || 'Candidate'}</small><span>{selected.candidate_ref ? <Identifier value={selected.candidate_ref} label="Candidate reference" /> : 'Reference not reported'}</span></div><ArrowRight size={19} aria-hidden="true" /><div><Rocket size={20} aria-hidden="true" /><span>Release <Identifier value={selected.release_version_id} label="Release version ID" /></span><strong>Revision {selected.revision_no}</strong><Badge className={`state state-${selected.status}`}>{selected.status}</Badge></div></div> : <ChartEmpty message="Choose a version from the registry below. References use the selected record only." />}
      </ChartPanel>
    </div>
    </details>
    <div className={`ops-workspace ${selected ? 'with-inspector' : ''}`}>
      <Card className="panel"><div className="panel-title"><div><h2>Release versions</h2><p>Candidate records and effective states returned by the API.</p></div><Badge className="badge">Loaded page</Badge></div><div className="panel-body">
        <div className="toolbar"><select aria-label="Release version for SBOM" value={releaseVersion} onChange={e => { setReleaseVersion(e.target.value); setSbomJson(null); }}><option value="">Select release version</option>{releaseVersions.map(v => <option key={v.release_version_id} value={v.release_version_id}>Release · r{v.revision_no} · {v.status}</option>)}</select><Button disabled={!releaseVersion || sbomBusy || !token?.trim()} onClick={() => void handleGenerateSbom()}><FileText size={15} aria-hidden="true" />{sbomBusy ? 'Loading…' : 'View SPDX SBOM'}</Button><Button disabled={!releaseVersion || sbomBusy || !token?.trim()} onClick={() => void handleGenerateSbom(true)}>Save SPDX artifact</Button><Button disabled={!releaseVersion || sbomBusy || !token?.trim()} onClick={downloadReleaseBundle}>Download release bundle</Button></div>
        {!!releaseVersions.length && <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table"><thead><tr><th>Version</th><th>Candidate</th><th>Reported state</th><th>Created</th></tr></thead><tbody>{releaseVersions.map(v => <tr key={v.release_version_id} className={selected === v ? 'ops-selected-row' : ''}><td><Button className="text-button" onClick={() => { setReleaseVersion(v.release_version_id); setSbomJson(null); }}>Release · r{v.revision_no}</Button><Identifier value={v.release_version_id} label="Release version ID" /></td><td>{v.candidate_type || 'Not reported'}<Identifier value={v.candidate_ref} label="Candidate reference" /></td><td><Badge className={`state state-${v.status}`}>{v.status}</Badge>{v.recorded_status && v.recorded_status !== v.status && <small className="id-text">Recorded state: {v.recorded_status}</small>}</td><td>{v.created_at ? new Date(v.created_at).toLocaleString() : 'Not reported'}</td></tr>)}</tbody></RecordTable></div>}
        {!loading && !error && !releaseVersions.length && <div className="empty-state"><h3>No release versions loaded</h3><p>{token?.trim() ? 'Use New candidate release to review a completed CPU candidate and exact evaluation.' : 'Open Connection and enter an API key to connect to the release registry.'}</p></div>}
      </div></Card>
      {selected && <InspectorPanel eyebrow="Release details" title={`Release · r${selected.revision_no}`} closeLabel="Close release details" onClose={() => { setReleaseVersion(''); setSbomJson(null); }}><dl className="ops-facts"><div><dt>Reported state</dt><dd>{selected.status}</dd></div><div><dt>Recorded state</dt><dd>{selected.recorded_status || selected.status}</dd></div><div><dt>Candidate type</dt><dd>{selected.candidate_type || 'Not reported'}</dd></div><div><dt>Candidate reference</dt><dd className="id-text">{selected.candidate_ref ? <Identifier value={selected.candidate_ref} label="Candidate reference" /> : 'Not reported'}</dd></div><div><dt>Model version</dt><dd>{selected.model_version ? <Identifier value={selected.model_version} label="Model version record ID" /> : 'Not linked'}</dd></div><div><dt>Linked endpoint records</dt><dd>{linkedEndpoints.length} in loaded page</dd></div><div><dt>Manifest digest</dt><dd className="id-text">{selected.manifest_digest ? <Identifier value={selected.manifest_digest} label="Manifest SHA-256" /> : 'Not reported'}</dd></div></dl>{selected.local_review && <ReleaseGateChecklist criteria={selected.local_review.criteria} state={selected.local_review.state} evidenceHref={runHash('evaluation', selected.local_review.evaluation_run)} />}
<details open><summary>Recorded execution evidence</summary>{selected.execution_evidence ? <DataInspector value={selected.execution_evidence} /> : <p className="muted">No execution evidence was returned.</p>}</details><details><summary>Recorded gate results</summary><DataInspector value={selected.gate_results ?? []} /></details><details><summary>Model card</summary><DataInspector value={selected.model_card ?? {}} /></details><p className="ops-scope">Recorded gates and endpoint pointers do not establish live serving or production qualification.</p></InspectorPanel>}
    </div>
    {sbomJson && <Card className="panel"><div className="panel-title"><div><h2>SPDX 2.3 Software Bill of Materials (SBOM)</h2><p>Recorded document for the selected release version.</p></div><div className="actions"><Button onClick={downloadSbom}>Download JSON</Button><Button onClick={() => setSbomJson(null)}>Close</Button></div></div><div className="panel-body"><p>{sbomEvidence?.verified ? 'Model byte checksums verified against the committed bundle.' : 'Metadata inventory; model bytes are unverified.'}</p>{sbomEvidence?.warnings?.map(warning => <p className="muted" key={warning}>{warning}</p>)}<DataInspector value={JSON.parse(sbomJson)} title="Software inventory" /></div></Card>}
    <Card className="panel"><div className="panel-title"><div><h2>Serving endpoint records</h2><p>Authenticated local CPU serving. Startup probes and deployment failures are retained; check live health after interruptions.</p></div><Badge className="badge">{endpoints.length} in loaded page</Badge></div><div className="panel-body">
      {endpoints.length ? <div className="ops-endpoint-grid">{endpoints.map(ep => <article key={ep.endpoint_id} className="ops-endpoint"><div className="ops-endpoint-title"><Rocket size={19} aria-hidden="true" /><strong>{ep.name || ep.endpoint_key}</strong><Badge className="badge">{ep.active_deployment ? 'Pointer recorded' : 'No pointer'}</Badge></div><Identifier value={ep.endpoint_id} label="Endpoint ID" /><dl className="ops-facts"><div><dt>Deployment revision</dt><dd>{ep.active_deployment ? `Rev ${ep.active_deployment.revision_no}` : 'None'}</dd></div><div><dt>Last startup readiness</dt><dd>{ep.active_deployment?.readiness_state || 'Not reported'}</dd></div>{ep.active_deployment?.recorded_readiness_state && ep.active_deployment.recorded_readiness_state !== ep.active_deployment.readiness_state && <div><dt>Recorded readiness</dt><dd>{ep.active_deployment.recorded_readiness_state}</dd></div>}<div><dt>Updated</dt><dd>{ep.updated_at ? new Date(ep.updated_at).toLocaleString() : 'Not reported'}</dd></div></dl><div className="actions"><Button disabled={submitting || !selected?.local_review || selected.local_review.state !== 'approved'} onClick={() => void servingAction(ep, 'deploy-local')}>Deploy selected locally</Button><Button disabled={submitting || !ep.active_deployment} onClick={() => void servingAction(ep, 'local-health')}>Check live health</Button><Button disabled={submitting || !ep.active_deployment} onClick={() => void servingAction(ep, 'completions')}>Test authenticated inference</Button><Button disabled={submitting || !ep.active_deployment} onClick={() => void servingAction(ep, 'rollback')}>Rollback locally</Button></div>{ep.deployments && <details><summary>Deployment history, including failed attempts</summary><DataInspector value={ep.deployments} /></details>}{ep.active_deployment && <details><summary>Linked version and recorded evidence</summary><DataInspector value={ep.active_deployment} /></details>}</article>)}</div> : !loading && !error && <div className="empty-state"><h3>No serving endpoints loaded</h3><p>Create an endpoint record to track release deployment metadata.</p></div>}
    </div></Card>
  </div>;
}
