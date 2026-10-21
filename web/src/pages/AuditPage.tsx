import { Identifier } from '../components/Identifier';
import { Badge, Button, Card, Field, RecordTable } from '../components/ui';
import { InspectorPanel } from '../components/InspectorPanel';
import { useDraft } from '../components/Draft';
import { auditResourceHash } from '../api/resource-routes';
import { DataInspector } from '../components/DataInspector';
import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartPanel, ChartEmpty, BarChart, SegmentBar, EventTimeline } from '../components/Charts';
import { Download, ShieldCheck } from 'lucide-react';
import './operations.css';
interface Event { event_id: string; actor_id: string | null; actor_kind: string; action: string; resource_type: string; resource_id: string | null; result: string; created_at: string; input_snapshot: Record<string, unknown> }
const endpoint = '/api/v1/audit/';
export function AuditPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const filterDraft = useDraft('audit-filters', { query: '', resultFilter: 'all', actor: '', action: '', resourceType: '', resourceId: '', project: '', dateFrom: '', dateTo: '', scope: 'project', appliedQuery: '?scope=project', selectedId: '' });
  const [actor, setActor] = filterDraft.field('actor'), [action, setAction] = filterDraft.field('action');
  const [resourceType, setResourceType] = filterDraft.field('resourceType'), [resourceId, setResourceId] = filterDraft.field('resourceId');
  const [project, setProject] = filterDraft.field('project'), [dateFrom, setDateFrom] = filterDraft.field('dateFrom'), [dateTo, setDateTo] = filterDraft.field('dateTo');
  const [scope, setScope] = filterDraft.field('scope'), [appliedQuery, setAppliedQuery] = filterDraft.field('appliedQuery');
  const [selectedId, setSelectedId] = filterDraft.field('selectedId');
  const [resourceState, setResourceState] = useState<{ state: string; reason: string } | null>(null);
  const [exportBusy, setExportBusy] = useState(false), [exportNotice, setExportNotice] = useState('');
  const exportRequest = useRef<AbortController | null>(null);
  const [query, setQuery] = filterDraft.field('query');
  const [selected, setSelected] = useState<Event | null>(null);
  const [retry, setRetry] = useState(0);
  const [resultFilter, setResultFilter] = filterDraft.field('resultFilter');
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setEvents([]); setNext(null); setSelected(null);
    apiPage<Event>(endpoint + appliedQuery, token, c.signal).then(p => { if (!c.signal.aborted) { setEvents(p.results); setNext(p.next || null); } }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => { c.abort(); exportRequest.current?.abort(); };
  }, [token, refreshKey, retry, appliedQuery]);
  async function more() {
    if (!next) return; setLoading(true); setError(null);
    try { const p = await apiPage<Event>(nextPagePath(next, endpoint + appliedQuery), token); setEvents(current => [...current, ...p.results.filter(e => !current.some(x => x.event_id === e.event_id))]); setNext(p.next || null); }
    catch(e) { setError(errorMessage(e)); } finally { setLoading(false); }
  }
  const filtered = events;
  const days = events.reduce<Record<string, number>>((counts, e) => {
    if (Number.isFinite(Date.parse(e.created_at))) {
      const day = new Date(e.created_at).toISOString().slice(0, 10);
      counts[day] = (counts[day] || 0) + 1;
    }
    return counts;
  }, {});
  const outcomes = [...new Set(events.map(e => e.result))].map(label => ({ label: label || 'Not reported', value: events.filter(e => e.result === label).length }));
  const related = selected ? events.filter(e => e.resource_type === selected.resource_type && e.resource_id === selected.resource_id).sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)) : [];
  useEffect(() => {
    const c = new AbortController(); setResourceState(null);
    if (selectedId) Promise.all([apiRequest<Event>(`${endpoint}${selectedId}/${appliedQuery}`, token, { signal: c.signal }), apiRequest<{ state: string; reason: string }>(`${endpoint}${selectedId}/resource-state/${appliedQuery}`, token, { signal: c.signal })])
      .then(([event, state]) => { if (!c.signal.aborted) { setSelected(event); setResourceState(state); } }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); });
    return () => c.abort();
  }, [selectedId, appliedQuery, token, refreshKey, retry]);
  function applyFilters(event: React.FormEvent) {
    event.preventDefault(); const params = new URLSearchParams({ scope });
    for (const [key, value] of [['q', query], ['actor', actor], ['action', action], ['resource_type', resourceType], ['resource', resourceId], ['project', project], ['date_from', dateFrom], ['date_to', dateTo]]) if (value) params.set(key, value);
    if (resultFilter !== 'all') params.set('outcome', resultFilter);
    setSelectedId(''); setSelected(null); setAppliedQuery('?' + params.toString());
    window.history.replaceState(null, '', '#audit?' + params.toString());
  }
  async function exportEvents() {
    const c = new AbortController(); exportRequest.current = c; setExportBusy(true); setExportNotice('');
    const rows: Event[] = []; let cursor: string | null = null, metadata: Record<string, unknown> = {};
    try {
      do {
        const response: { results: Event[]; next_cursor: string | null; metadata: Record<string, unknown> } = await apiRequest(`${endpoint}export/${cursor ? '?cursor='+encodeURIComponent(cursor) : appliedQuery}`, token, { signal: c.signal });
        if (c.signal.aborted) return;
        rows.push(...response.results); metadata = response.metadata; cursor = response.next_cursor;
        setExportNotice(`Exported ${rows.length} of ${String(metadata.total_count)} scoped snapshot events…`);
      } while (cursor);
      const url = URL.createObjectURL(new Blob([JSON.stringify({ metadata, events: rows }, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = `modelanvil-audit-${metadata.complete ? 'complete' : 'PARTIAL'}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExportNotice(`${metadata.complete ? 'Complete' : 'Partial'} audit snapshot exported: ${rows.length} events, with period, filters and scope metadata.`);
    } catch (e) { if (!c.signal.aborted) setError(errorMessage(e)); } finally { if (!c.signal.aborted) setExportBusy(false); }
  }
  return <div className="resource-view operations-page">
    <div className="ops-heading"><div><span className="eyebrow">Workspace evidence</span><h2>Activity records</h2><p>Inspect recorded actions, actors and outcomes across your tenant.</p></div><Button disabled={loading || exportBusy || !!error} onClick={() => void exportEvents()}><Download size={15} aria-hidden="true" />Export scoped snapshot</Button></div>
    <details className="workspace-details"><summary>More audit filters</summary><form className="form-grid" onSubmit={applyFilters}><label>Audit scope<select value={scope} onChange={e => setScope(e.target.value)}><option value="project">Current project and shared setup events</option><option value="tenant">Tenant-wide (unrestricted keys only)</option></select></label><label>Actor ID<Field value={actor} onChange={e => setActor(e.target.value)} /></label><label>Exact action<Field value={action} onChange={e => setAction(e.target.value)} /></label><label>Resource type<Field value={resourceType} onChange={e => setResourceType(e.target.value)} /></label><label>Exact resource ID<Field value={resourceId} onChange={e => setResourceId(e.target.value)} /></label><label>Project ID<Field value={project} onChange={e => setProject(e.target.value)} /></label><label>From (UTC)<Field type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} /></label><label>Through (UTC)<Field type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} /></label><Button className="primary" disabled={exportBusy}>Apply audit filters</Button></form></details>
    {exportNotice && <p role="status">{exportNotice}</p>}
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
    <details className="workspace-details"><summary>Activity overview</summary><div className="ops-chart-grid">
      <ChartPanel title="Event volume" description={`${events.length} loaded events only · UTC calendar dates · not total tenant activity.`}><BarChart data={Object.entries(days).sort(([a], [b]) => a.localeCompare(b)).map(([label, value]) => ({ label, value, color: 0 }))} unit="loaded events" emptyMessage="Load audit events to display observed event volume." /></ChartPanel>
      <ChartPanel title="Recorded outcomes" description="Distribution across the loaded events, before search filters.">{events.length ? <SegmentBar data={outcomes} unit="events" /> : <ChartEmpty message="Recorded outcomes will appear when audit events are available." />}</ChartPanel>
    </div>
    </details>
    <div className={`ops-workspace ${selected ? 'with-inspector' : ''}`}>
      <Card className="panel"><div className="panel-title"><div><h2>Events</h2><p>Exact recorded actions and their resource identities.</p></div><Badge className="badge"><ShieldCheck size={13} aria-hidden="true" />Read only</Badge></div><div className="panel-body">
        <div className="toolbar"><Field aria-label="Search audit events" placeholder="Search server-side actions or resource types" value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="Filter audit outcome" value={resultFilter} onChange={e => setResultFilter(e.target.value)}><option value="all">All outcomes</option>{['ok', 'denied', 'error'].map(r => <option key={r} value={r}>{r || 'Not reported'}</option>)}</select><Button disabled={exportBusy} onClick={e => applyFilters(e)}>Apply search and outcome</Button><small className="muted">{events.length} matching events loaded from server filters</small></div>
        {!loading && !error && !filtered.length && <div className="empty-state"><h3>No audit events match</h3><p>Recorded tenant activity will appear here. The server applies your selected filters across all authorized records. Load more matching pages when available.</p></div>}
        {!!filtered.length && <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table"><thead><tr><th>Time</th><th>Action</th><th>Resource</th><th>Actor</th><th>Outcome</th></tr></thead><tbody>{filtered.map(e => <tr key={e.event_id} className={selected?.event_id === e.event_id ? 'ops-selected-row' : ''}><td>{new Date(e.created_at).toLocaleString()}</td><td><Button className="text-button" onClick={() => { setSelected(e); setSelectedId(e.event_id); }}>{e.action}</Button></td><td>{e.resource_type}<Identifier value={e.resource_id} label="Resource ID" /></td><td>{e.actor_kind}<Identifier value={e.actor_id} label="Actor ID" /></td><td><Badge className={`state state-${e.result}`}>{e.result || 'Not reported'}</Badge></td></tr>)}</tbody></RecordTable></div>}
        <div className="ops-table-footer"><small>{events.length} events loaded{next ? ' · more events are available' : ''}</small>{next && <Button disabled={loading} onClick={() => void more()}>Load more events</Button>}</div>
      </div></Card>
      {selected && <InspectorPanel eyebrow="Event details" title={selected.action} closeLabel="Close event details" onClose={() => { setSelected(null); setSelectedId(''); }}><Badge className={`state state-${selected.result}`}>{selected.result}</Badge><dl className="ops-facts"><div><dt>Time</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd></div><div><dt>Actor</dt><dd>{selected.actor_kind}<Identifier value={selected.actor_id} label="Actor ID" /></dd></div><div><dt>Resource</dt><dd>{selected.resource_type}<Identifier value={selected.resource_id} label="Resource ID" /></dd></div><div><dt>Event ID</dt><dd><Identifier value={selected.event_id} label="Audit event ID" /></dd></div></dl>{auditResourceHash(selected.resource_type, selected.resource_id || '') ? <a href={auditResourceHash(selected.resource_type, selected.resource_id || '')!}>Open exact authorized resource</a> : <p className="muted">Historical record only: this resource type has no browser detail route.</p>}{resourceState && <p role="status">{resourceState.state.replaceAll('_', ' ')}: {resourceState.reason}</p>}<h3>Loaded resource activity</h3><p className="muted">Events for this exact resource identity in the loaded list.</p><EventTimeline events={related.map(e => ({ label: e.action, detail: `${new Date(e.created_at).toLocaleString()} · ${e.actor_kind}`, status: e.result }))} /><details open><summary>Recorded input snapshot</summary><DataInspector value={selected.input_snapshot} /></details><details><summary>Exact event record</summary><DataInspector value={selected} /></details></InspectorPanel>}
    </div>
  </div>;
}
