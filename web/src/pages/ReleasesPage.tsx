import React from 'react';
import { apiPage, apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { Rocket, Plus, FileText, CheckCircle2, ArrowRight, Box, X } from 'lucide-react';
import { ChartPanel, ChartEmpty, SegmentBar } from '../components/Charts';
import './operations.css';

interface ReleaseVersion {
  release_version_id: string; revision_no: number; release: number; status: string; recorded_status?: string;
  candidate_type?: string; candidate_ref?: string; model_version?: number | null; manifest_digest?: string; created_at?: string;
  execution_evidence?: unknown; gate_results?: unknown; model_card?: unknown;
}
interface ServingEndpoint {
  endpoint_id: string; endpoint_key: string; name: string; created_at?: string; updated_at?: string;
  active_deployment: { deployment_id: string; release_version: string; revision_no: number; readiness_state: string; recorded_readiness_state?: string; execution_evidence?: unknown } | null;
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
  const [releaseVersion, setReleaseVersion] = React.useState('');
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

  React.useEffect(() => { setReleaseVersion(''); setSbomJson(null); setNotice(null); }, [token]);

  React.useEffect(() => {
    fetchEndpoints();
  }, [fetchEndpoints, refreshKey]);

  async function handleCreateEndpoint(e: React.FormEvent) {
    e.preventDefault();
    if (!token?.trim() || !newKey.trim()) return;
    setSubmitting(true); setError(null);
    try {
      const headers: Record<string, string> = {
        Authorization: `Bearer ${token.trim()}`,
        'Content-Type': 'application/json',
      };
      const res = await fetch('/api/v1/serving-endpoints/', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          endpoint_key: newKey.trim(),
          name: newName.trim() || newKey.trim(),
        }),
      });
      if (res.ok) {
        setShowModal(false);
        setNewKey('');
        setNewName('');
        setNotice(`Serving endpoint "${newKey}" created.`);
        setTimeout(() => setNotice(null), 4000);
        await fetchEndpoints();
      } else {
        const err = await res.json();
        setError(err?.error?.message || 'Failed to create endpoint.');
      }
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
      const bundle = await apiRequest<{model_bundle?: unknown}>(`/api/v1/release-versions/${releaseVersion}/export-bundle/`, token || '');
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = `release-${releaseVersion}.bundle.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(bundle.model_bundle ? 'Downloaded release bundle with committed model bytes and local loading verification.' : 'Downloaded release metadata. This candidate has no committed model weights.');
    } catch (err) { setError(errorMessage(err)); } finally { setSbomBusy(false); }
  }

  const selected = releaseVersions.find(v => v.release_version_id === releaseVersion);
  const states = [...new Set(releaseVersions.map(v => v.status))].map(label => ({ label, value: releaseVersions.filter(v => v.status === label).length }));
  const linkedEndpoints = selected ? endpoints.filter(ep => ep.active_deployment?.release_version === selected.release_version_id) : [];
  return <div className="resource-view releases-view operations-page">
    <div className="ops-heading"><div><span className="eyebrow">Release registry</span><h2>Candidate review</h2><p>Inspect candidate versions, endpoint records and recorded release evidence.</p></div><button className="primary" disabled={!token?.trim() || submitting} aria-expanded={showModal} onClick={() => setShowModal(v => !v)}><Plus size={16} aria-hidden="true" />New Endpoint</button></div>
    <p className="notice">Release exports contain metadata. Live serving and production qualification remain unavailable; simulated gates cannot authorize promotion.</p>
    <ResourceState loading={loading} error={error} onRetry={() => void fetchEndpoints()} />
    {notice && <div className="notice success" role="status"><CheckCircle2 size={16} aria-hidden="true" />{notice}</div>}
    {showModal && <section className="panel"><div className="panel-title"><div><h2>Create serving endpoint</h2><p>Creates an endpoint record. Promotion and deployment are managed through the API.</p></div><button className="icon-button" aria-label="Close endpoint form" disabled={submitting} onClick={() => setShowModal(false)}><X size={17} aria-hidden="true" /></button></div><form onSubmit={handleCreateEndpoint} className="form-grid"><label htmlFor="endpoint-key">Endpoint Key<input type="text" id="endpoint-key" placeholder="e.g. svg-generation-primary" value={newKey} onChange={e => setNewKey(e.target.value)} required /></label><label htmlFor="endpoint-name">Display Name<input type="text" id="endpoint-name" placeholder="e.g. SVG Generation Primary Cluster" value={newName} onChange={e => setNewName(e.target.value)} /></label><div className="full-width actions"><button className="primary" type="submit" disabled={submitting || !token?.trim() || !newKey.trim()}>{submitting ? 'Creating...' : 'Create Endpoint'}</button><button type="button" disabled={submitting} onClick={() => setShowModal(false)}>Cancel</button></div></form></section>}
    <div className="ops-chart-grid">
      <ChartPanel title="Reported release states" description={`${releaseVersions.length} versions in the loaded page · backend state does not certify production readiness.`}>{releaseVersions.length ? <SegmentBar data={states} unit="versions" /> : <ChartEmpty message="Create a candidate release version through the API to see reported states." />}</ChartPanel>
      <ChartPanel title="Recorded release references" description={selected ? `Release #${selected.release} · revision ${selected.revision_no}` : 'Select a release version to inspect its recorded references.'}>
        {selected ? <div className="ops-release-lineage"><div><Box size={20} aria-hidden="true" /><small>{selected.candidate_type || 'Candidate'}</small><strong>{selected.candidate_ref || 'Reference not reported'}</strong></div><ArrowRight size={19} aria-hidden="true" /><div><Rocket size={20} aria-hidden="true" /><small>Release #{selected.release}</small><strong>Revision {selected.revision_no}</strong><span className={`state state-${selected.status}`}>{selected.status}</span></div></div> : <ChartEmpty message="Choose a version from the registry below. References use the selected record only." />}
      </ChartPanel>
    </div>
    <div className={`ops-workspace ${selected ? 'with-inspector' : ''}`}>
      <section className="panel"><div className="panel-title"><div><h2>Release versions</h2><p>Candidate records and effective states returned by the API.</p></div><span className="badge">Loaded page</span></div><div className="panel-body">
        <div className="toolbar"><select aria-label="Release version for SBOM" value={releaseVersion} onChange={e => { setReleaseVersion(e.target.value); setSbomJson(null); }}><option value="">Select release version</option>{releaseVersions.map(v => <option key={v.release_version_id} value={v.release_version_id}>Release #{v.release} · r{v.revision_no} · {v.status}</option>)}</select><button disabled={!releaseVersion || sbomBusy || !token?.trim()} onClick={() => void handleGenerateSbom()}><FileText size={15} aria-hidden="true" />{sbomBusy ? 'Loading…' : 'View SPDX SBOM'}</button><button disabled={!releaseVersion || sbomBusy || !token?.trim()} onClick={() => void handleGenerateSbom(true)}>Save SPDX artifact</button><button disabled={!releaseVersion || sbomBusy || !token?.trim()} onClick={downloadReleaseBundle}>Download release bundle</button></div>
        {!!releaseVersions.length && <div className="table-scroll" tabIndex={0}><table className="resource-table"><thead><tr><th>Version</th><th>Candidate</th><th>Reported state</th><th>Created</th></tr></thead><tbody>{releaseVersions.map(v => <tr key={v.release_version_id} className={selected === v ? 'ops-selected-row' : ''}><td><button className="text-button" onClick={() => { setReleaseVersion(v.release_version_id); setSbomJson(null); }}>Release #{v.release} · r{v.revision_no}</button><small className="id-text">{v.release_version_id.slice(0, 8)}</small></td><td>{v.candidate_type || 'Not reported'}<small className="id-text">{v.candidate_ref}</small></td><td><span className={`state state-${v.status}`}>{v.status}</span>{v.recorded_status && v.recorded_status !== v.status && <small className="id-text">Recorded state: {v.recorded_status}</small>}</td><td>{v.created_at ? new Date(v.created_at).toLocaleString() : 'Not reported'}</td></tr>)}</tbody></table></div>}
        {!loading && !error && !releaseVersions.length && <div className="empty-state"><h3>No release versions loaded</h3><p>{token?.trim() ? 'Create a release candidate through the API to inspect its evidence and SBOM.' : 'Open Connection and enter an API key to connect to the release registry.'}</p></div>}
      </div></section>
      {selected && <aside className="panel ops-inspector"><div className="panel-title"><div><span className="eyebrow">Release details</span><h2>Release #{selected.release} · r{selected.revision_no}</h2></div><button className="icon-button" aria-label="Close release details" onClick={() => { setReleaseVersion(''); setSbomJson(null); }}><X size={17} aria-hidden="true" /></button></div><div className="panel-body"><dl className="ops-facts"><div><dt>Reported state</dt><dd>{selected.status}</dd></div><div><dt>Recorded state</dt><dd>{selected.recorded_status || selected.status}</dd></div><div><dt>Candidate type</dt><dd>{selected.candidate_type || 'Not reported'}</dd></div><div><dt>Candidate reference</dt><dd className="id-text">{selected.candidate_ref || 'Not reported'}</dd></div><div><dt>Model version</dt><dd>{selected.model_version ?? 'Not linked'}</dd></div><div><dt>Linked endpoint records</dt><dd>{linkedEndpoints.length} in loaded page</dd></div><div><dt>Manifest digest</dt><dd className="id-text">{selected.manifest_digest || 'Not reported'}</dd></div></dl><details open><summary>Recorded execution evidence</summary>{selected.execution_evidence ? <pre>{JSON.stringify(selected.execution_evidence, null, 2)}</pre> : <p className="muted">No execution evidence was returned.</p>}</details><details><summary>Recorded gate results</summary><pre>{JSON.stringify(selected.gate_results ?? [], null, 2)}</pre></details><details><summary>Model card</summary><pre>{JSON.stringify(selected.model_card ?? {}, null, 2)}</pre></details><p className="ops-scope">Recorded gates and endpoint pointers do not establish live serving or production qualification.</p></div></aside>}
    </div>
    {sbomJson && <section className="panel"><div className="panel-title"><div><h2>SPDX 2.3 Software Bill of Materials (SBOM)</h2><p>Recorded document for the selected release version.</p></div><div className="actions"><button onClick={downloadSbom}>Download JSON</button><button onClick={() => setSbomJson(null)}>Close</button></div></div><div className="panel-body"><p>{sbomEvidence?.verified ? 'Model byte checksums verified against the committed bundle.' : 'Metadata inventory; model bytes are unverified.'}</p>{sbomEvidence?.warnings?.map(warning => <p className="muted" key={warning}>{warning}</p>)}<pre>{sbomJson}</pre></div></section>}
    <section className="panel"><div className="panel-title"><div><h2>Serving endpoint records</h2><p>Recorded deployment pointers and readiness states; live serving is not verified.</p></div><span className="badge">{endpoints.length} in loaded page</span></div><div className="panel-body">
      {endpoints.length ? <div className="ops-endpoint-grid">{endpoints.map(ep => <article key={ep.endpoint_id} className="ops-endpoint"><div className="ops-endpoint-title"><Rocket size={19} aria-hidden="true" /><strong>{ep.name || ep.endpoint_key}</strong><span className="badge">{ep.active_deployment ? 'Pointer recorded' : 'No pointer'}</span></div><small className="id-text">{ep.endpoint_key}</small><dl className="ops-facts"><div><dt>Deployment revision</dt><dd>{ep.active_deployment ? `Rev ${ep.active_deployment.revision_no}` : 'None'}</dd></div><div><dt>Reported readiness</dt><dd>{ep.active_deployment?.readiness_state || 'Not reported'}</dd></div>{ep.active_deployment?.recorded_readiness_state && ep.active_deployment.recorded_readiness_state !== ep.active_deployment.readiness_state && <div><dt>Recorded readiness</dt><dd>{ep.active_deployment.recorded_readiness_state}</dd></div>}<div><dt>Updated</dt><dd>{ep.updated_at ? new Date(ep.updated_at).toLocaleString() : 'Not reported'}</dd></div></dl>{ep.active_deployment && <details><summary>Linked version and recorded evidence</summary><pre>{JSON.stringify(ep.active_deployment, null, 2)}</pre></details>}</article>)}</div> : !loading && !error && <div className="empty-state"><h3>No serving endpoints loaded</h3><p>Create an endpoint record to track release deployment metadata.</p></div>}
    </div></section>
  </div>;
}
