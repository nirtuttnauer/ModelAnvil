import { Button, Disclosure, Field, KeyValueList, LinkButton, RecordTable, Section, Select, StatusBadge, TextControl, Toolbar } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { Identifier } from '../components/Identifier';
import { InspectorPanel } from '../components/InspectorPanel';
import { useDraft } from '../components/Draft';
import { auditResourceHash } from '../api/resource-routes';
import { DataInspector } from '../components/DataInspector';
import { useEffect, useRef, useState } from 'react';
import { apiPage, apiRequest, errorMessage, nextPagePath } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { statusLabel } from '../api/status';
import { ChartPanel, ChartEmpty, BarChart, SegmentBar, EventTimeline } from '../components/Charts';
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
  const resourceHref = selected ? auditResourceHash(selected.resource_type, selected.resource_id || '') : null;

  return <div className="ops-page">
    <Section title="Events" description="Recorded actions, actors and outcomes for this tenant." actions={<Button type="button" disabled={loading || exportBusy || !!error} onClick={() => void exportEvents()}>Export snapshot</Button>}>
      <form onSubmit={applyFilters} data-ui="form">
        <Toolbar label="Audit filters" actions={<Button type="submit" disabled={exportBusy}>Apply filters</Button>}>
          <Field aria-label="Search audit events" placeholder="Search actions or resource types" value={query} onChange={e => setQuery(e.target.value)} />
          <Select aria-label="Filter audit outcome" value={resultFilter} onChange={e => setResultFilter(e.target.value)}>
            <option value="all">All outcomes</option>{['ok', 'denied', 'error'].map(r => <option key={r} value={r}>{statusLabel(r)}</option>)}
          </Select>
        </Toolbar>
        <Disclosure summary="More audit filters" variant="quiet">
          <div data-ui="field-grid">
            <Select label="Audit scope" value={scope} onChange={e => setScope(e.target.value)} options={[{ value: 'project', label: 'Current project and shared setup events' }, { value: 'tenant', label: 'Tenant-wide (unrestricted keys only)' }]} />
            <TextControl label="Actor ID" value={actor} onChange={e => setActor(e.target.value)} />
            <TextControl label="Exact action" value={action} onChange={e => setAction(e.target.value)} />
            <TextControl label="Resource type" value={resourceType} onChange={e => setResourceType(e.target.value)} />
            <TextControl label="Exact resource ID" value={resourceId} onChange={e => setResourceId(e.target.value)} />
            <TextControl label="Project ID" value={project} onChange={e => setProject(e.target.value)} />
            <TextControl label="From (UTC)" type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
            <TextControl label="Through (UTC)" type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
          </div>
        </Disclosure>
      </form>
      {exportNotice && <p role="status">{exportNotice}</p>}
      <ResourceState loading={loading && !events.length} error={error} onRetry={() => setRetry(v => v + 1)} />
      <div data-ui="split" data-open={selected ? '' : undefined}>
        <div className="ops-main">
          {!loading && !error && <p className="ops-count">{events.length} events loaded{next ? ' · more available' : ''}</p>}
          {!loading && !error && !events.length && <EmptyState title="No audit events match" description="The server applies your filters across all authorized records." />}
          {!!events.length && <div className="table-scroll" tabIndex={0}><RecordTable>
            <thead><tr><th>Time</th><th>Action</th><th>Resource</th><th>Actor</th><th>Outcome</th></tr></thead>
            <tbody>{events.map(e => <tr key={e.event_id} aria-selected={selected?.event_id === e.event_id || undefined}>
              <td>{new Date(e.created_at).toLocaleString()}</td>
              <td><Button type="button" variant="quiet" size="sm" onClick={() => { setSelected(e); setSelectedId(e.event_id); }}>{e.action}</Button></td>
              <td>{e.resource_type}</td>
              <td>{e.actor_kind}</td>
              <td><StatusBadge status={e.result} label={e.result ? statusLabel(e.result) : 'Not reported'} /></td>
            </tr>)}</tbody>
          </RecordTable></div>}
          {next && <Button type="button" disabled={loading} onClick={() => void more()}>Load more events</Button>}
        </div>
        {selected && <InspectorPanel key={selected.event_id} eyebrow="Event" title={selected.action} closeLabel="Close event details" onClose={() => { setSelected(null); setSelectedId(''); }}>
          <div data-ui="actions"><StatusBadge status={selected.result} label={selected.result ? statusLabel(selected.result) : 'Not reported'} /></div>
          <KeyValueList items={[
            { label: 'Time', value: new Date(selected.created_at).toLocaleString() },
            { label: 'Actor', value: <>{selected.actor_kind}{selected.actor_id && <> <Identifier value={selected.actor_id} label="Actor ID" display="code" /></>}</> },
            { label: 'Resource', value: <>{selected.resource_type}{selected.resource_id && <> <Identifier value={selected.resource_id} label="Resource ID" display="code" /></>}</> },
            { label: 'Event ID', value: <Identifier value={selected.event_id} label="Audit event ID" display="code" /> },
          ]} />
          {resourceHref ? <div data-ui="actions"><LinkButton href={resourceHref}>Open resource</LinkButton></div> : <p className="muted">This resource type has no detail view.</p>}
          {resourceState && <p role="status">{statusLabel(resourceState.state)}: {resourceState.reason}</p>}
          <h3>Activity for this resource</h3>
          <EventTimeline events={related.map(e => ({ label: e.action, detail: `${new Date(e.created_at).toLocaleString()} · ${e.actor_kind}`, status: e.result }))} />
          <Disclosure summary="Recorded input snapshot" variant="quiet" open><DataInspector value={selected.input_snapshot} /></Disclosure>
          <Disclosure summary="Exact event record" variant="quiet"><DataInspector value={selected} /></Disclosure>
        </InspectorPanel>}
      </div>
    </Section>
    <Disclosure summary="Activity overview" variant="card"><div className="ops-charts">
      <ChartPanel title="Event volume" description={`${events.length} loaded events by UTC date.`}><BarChart data={Object.entries(days).sort(([a], [b]) => a.localeCompare(b)).map(([label, value]) => ({ label, value, color: 0 }))} unit="loaded events" emptyMessage="Load audit events to display observed event volume." /></ChartPanel>
      <ChartPanel title="Recorded outcomes" description="Distribution across the loaded events.">{events.length ? <SegmentBar data={outcomes} unit="events" /> : <ChartEmpty message="Recorded outcomes will appear when audit events are available." />}</ChartPanel>
    </div></Disclosure>
  </div>;
}
