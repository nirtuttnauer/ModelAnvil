import { useEffect, useState } from 'react';
import { apiPage, errorMessage, nextPagePath } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartPanel, ChartEmpty, BarChart, SegmentBar, EventTimeline } from '../components/Charts';
import { Download, X, ShieldCheck } from 'lucide-react';
import './operations.css';
interface Event { event_id: string; actor_id: string; actor_kind: string; action: string; resource_type: string; resource_id: string; result: string; created_at: string; input_snapshot: Record<string, unknown> }
const endpoint = '/api/v1/audit/';
export function AuditPage({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Event | null>(null);
  const [retry, setRetry] = useState(0);
  const [resultFilter, setResultFilter] = useState('all');
  useEffect(() => {
    const c = new AbortController(); setLoading(true); setError(null); setEvents([]); setNext(null); setSelected(null);
    apiPage<Event>(endpoint, token, c.signal).then(p => { if (!c.signal.aborted) { setEvents(p.results); setNext(p.next || null); } }).catch(e => { if (!c.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!c.signal.aborted) setLoading(false); });
    return () => c.abort();
  }, [token, refreshKey, retry]);
  async function more() {
    if (!next) return; setLoading(true); setError(null);
    try { const p = await apiPage<Event>(nextPagePath(next, endpoint), token); setEvents(current => [...current, ...p.results.filter(e => !current.some(x => x.event_id === e.event_id))]); setNext(p.next || null); }
    catch(e) { setError(errorMessage(e)); } finally { setLoading(false); }
  }
  const filtered = events.filter(e => `${e.action} ${e.resource_type} ${e.resource_id} ${e.actor_id}`.toLowerCase().includes(query.toLowerCase()) && (resultFilter === 'all' || e.result === resultFilter));
  const days = events.reduce<Record<string, number>>((counts, e) => {
    if (Number.isFinite(Date.parse(e.created_at))) {
      const day = new Date(e.created_at).toISOString().slice(0, 10);
      counts[day] = (counts[day] || 0) + 1;
    }
    return counts;
  }, {});
  const outcomes = [...new Set(events.map(e => e.result))].map(label => ({ label: label || 'Not reported', value: events.filter(e => e.result === label).length }));
  const related = selected ? events.filter(e => e.resource_type === selected.resource_type && e.resource_id === selected.resource_id).sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)) : [];
  function exportEvents() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(filtered, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'modelanvil-loaded-audit-events.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="resource-view operations-page">
    <div className="ops-heading"><div><span className="eyebrow">Workspace evidence</span><h2>Activity records</h2><p>Inspect recorded actions, actors and outcomes across your tenant.</p></div><button disabled={!filtered.length} onClick={exportEvents}><Download size={15} aria-hidden="true" />Export loaded events</button></div>
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
    <div className="ops-chart-grid">
      <ChartPanel title="Event volume" description={`${events.length} loaded events only · UTC calendar dates · not total tenant activity.`}><BarChart data={Object.entries(days).sort(([a], [b]) => a.localeCompare(b)).map(([label, value]) => ({ label, value, color: 0 }))} unit="loaded events" emptyMessage="Load audit events to display observed event volume." /></ChartPanel>
      <ChartPanel title="Recorded outcomes" description="Distribution across the loaded events, before search filters.">{events.length ? <SegmentBar data={outcomes} unit="events" /> : <ChartEmpty message="Recorded outcomes will appear when audit events are available." />}</ChartPanel>
    </div>
    <div className={`ops-workspace ${selected ? 'with-inspector' : ''}`}>
      <section className="panel"><div className="panel-title"><div><h2>Events</h2><p>Exact recorded actions and their resource identities.</p></div><span className="badge"><ShieldCheck size={13} aria-hidden="true" />Read only</span></div><div className="panel-body">
        <div className="toolbar"><input aria-label="Search audit events" placeholder="Filter loaded events by action, actor, or resource" value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="Filter audit outcome" value={resultFilter} onChange={e => setResultFilter(e.target.value)}><option value="all">All outcomes</option>{[...new Set(events.map(e => e.result))].map(r => <option key={r} value={r}>{r || 'Not reported'}</option>)}</select><small className="muted">{filtered.length} of {events.length} loaded events</small></div>
        {!loading && !error && !filtered.length && <div className="empty-state"><h3>No audit events match</h3><p>Recorded tenant activity will appear here. Search applies only to the loaded events.</p></div>}
        {!!filtered.length && <div className="table-scroll" tabIndex={0}><table className="resource-table"><thead><tr><th>Time</th><th>Action</th><th>Resource</th><th>Actor</th><th>Outcome</th></tr></thead><tbody>{filtered.map(e => <tr key={e.event_id} className={selected?.event_id === e.event_id ? 'ops-selected-row' : ''}><td>{new Date(e.created_at).toLocaleString()}</td><td><button className="text-button" onClick={() => setSelected(e)}>{e.action}</button></td><td>{e.resource_type}<small className="id-text">{e.resource_id}</small></td><td>{e.actor_kind}<small className="id-text">{e.actor_id}</small></td><td><span className={`state state-${e.result}`}>{e.result || 'Not reported'}</span></td></tr>)}</tbody></table></div>}
        <div className="ops-table-footer"><small>{events.length} events loaded{next ? ' · more events are available' : ''}</small>{next && <button disabled={loading} onClick={() => void more()}>Load more events</button>}</div>
      </div></section>
      {selected && <aside className="panel ops-inspector"><div className="panel-title"><div><span className="eyebrow">Event details</span><h2>{selected.action}</h2></div><button className="icon-button" aria-label="Close event details" onClick={() => setSelected(null)}><X size={17} aria-hidden="true" /></button></div><div className="panel-body"><span className={`state state-${selected.result}`}>{selected.result}</span><dl className="ops-facts"><div><dt>Time</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd></div><div><dt>Actor</dt><dd>{selected.actor_kind}<small className="id-text">{selected.actor_id}</small></dd></div><div><dt>Resource</dt><dd>{selected.resource_type}<small className="id-text">{selected.resource_id}</small></dd></div><div><dt>Event ID</dt><dd className="id-text">{selected.event_id}</dd></div></dl><h3>Loaded resource activity</h3><p className="muted">Events for this exact resource identity in the loaded list.</p><EventTimeline events={related.map(e => ({ label: e.action, detail: `${new Date(e.created_at).toLocaleString()} · ${e.actor_kind} ${e.actor_id}`, status: e.result }))} /><details open><summary>Recorded input snapshot</summary><pre>{JSON.stringify(selected.input_snapshot, null, 2)}</pre></details><details><summary>Exact event record</summary><pre>{JSON.stringify(selected, null, 2)}</pre></details></div></aside>}
    </div>
  </div>;
}
