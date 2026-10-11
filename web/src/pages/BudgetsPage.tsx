import { useState, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';
import { apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartPanel, ChartEmpty, BarChart } from '../components/Charts';
import { ReceiptText, X } from 'lucide-react';
import './operations.css';

export interface UsageSummaryItem {
  unit: string;
  total_quantity: string;
  total_amount: string | null;
  priced_event_count?: number;
  unpriced_event_count?: number;
  event_count: number;
  currency: string;
}

export interface UsageSummaryResponse {
  tenant_id: string;
  usage_by_unit: UsageSummaryItem[];
  total_policies: number;
  active_reservations_count: number;
  total_reserved_amount: string | null;
  reserved_by_unit?: { unit: string; currency: string; reserved_amount: string; reservation_count: number }[];
}

export interface BudgetsPageProps {
  token: string;
  refreshKey?: number;
}

export function BudgetsPage({ token, refreshKey = 0 }: BudgetsPageProps) {
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<UsageSummaryItem | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setSummary(null); setSelected(null);
    apiRequest<UsageSummaryResponse>('/api/v1/usage-events/summary/', token, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setSummary(data); })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refreshKey, retry]);
  const stats = [
    { label: 'Active reservations', value: summary?.active_reservations_count ?? '—', hint: 'Awaiting completion or release' },
    { label: 'Reservation units', value: summary?.reserved_by_unit?.length ?? '—', hint: 'Each resource unit kept separate' },
    { label: 'Budget policies', value: summary?.total_policies ?? '—', hint: 'Configured spending policies' },
    { label: 'Resource units', value: summary ? new Set(summary.usage_by_unit.map(row => row.unit)).size : '—', hint: 'Units with recorded usage' },
  ];
  const currencies = [...new Set(summary?.usage_by_unit.map(u => u.currency) || [])];
  return <div className="resource-view operations-page">
    <div className="ops-heading"><div><span className="eyebrow">Resource accounting</span><h2>Resource accounting</h2><p>Inspect measured costs and reservations for pending work.</p></div><button disabled={loading} onClick={() => setRetry(v => v + 1)}><RefreshCw size={15} aria-hidden="true" />Refresh usage</button></div>
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
    <div className="cards">{stats.map(s => <article className="summary-card" key={s.label}><span>{s.label}</span><b>{s.value}</b><small>{s.hint}</small></article>)}</div>
    <div className="ops-chart-grid">
      {currencies.length ? currencies.map(currency => <ChartPanel key={currency} title={`Recorded costs · ${currency || 'unspecified currency'}`} description="Measured amount by resource unit. Each currency uses a separate scale."><BarChart data={summary!.usage_by_unit.filter(u => u.currency === currency && u.total_amount !== null && u.total_amount.trim() !== '' && Number.isFinite(Number(u.total_amount))).map(u => ({ label: u.unit, value: Number(u.total_amount), detail: `${u.total_quantity} measured units · ${u.event_count} events`, color: 0 }))} unit={currency || 'currency not reported'} emptyMessage="No numeric cost measurements were reported in this currency." /></ChartPanel>) : <ChartPanel title="Recorded resource costs" description="Measurements will be grouped by their reported currency."><ChartEmpty message="Billable resource events are needed to display measured costs." /></ChartPanel>}
      <ChartPanel title="Reservation ledger" description="Summary returned by the usage API."><div className="ops-ledger"><ReceiptText size={30} aria-hidden="true" /><span>Reserved for pending work</span><strong>{summary?.reserved_by_unit?.length ? summary.reserved_by_unit.map(row => `${row.reserved_amount} ${row.unit}${row.currency ? ` · ${row.currency}` : ''}`).join(' / ') : summary?.total_reserved_amount ?? '—'}</strong><p>{summary ? `${summary.active_reservations_count} active reservations · ${summary.total_policies} configured policies` : 'Connect to retrieve the tenant reservation summary.'}</p><small>Reserved quantities are grouped by policy unit and currency. Policy limits and forecasts are not inferred.</small></div></ChartPanel>
    </div>
    <div className={`ops-workspace ${selected ? 'with-inspector' : ''}`}>
    <section className="panel"><div className="panel-title"><div><h2>Recorded usage & costs</h2><p>Measured usage by resource unit. Currency is reported with each cost.</p></div><button disabled={loading} onClick={() => setRetry(v => v + 1)}><RefreshCw size={15} aria-hidden="true" />Refresh usage</button></div><div className="panel-body">
      {summary && summary.usage_by_unit.length > 0 ? <div className="table-scroll" tabIndex={0}><table className="resource-table"><thead><tr><th>Resource unit</th><th>Total quantity</th><th>Recorded cost</th><th>Events</th></tr></thead><tbody>{summary.usage_by_unit.map(u => <tr key={`${u.unit}-${u.currency}`} className={selected === u ? 'ops-selected-row' : ''}><td><button className="text-button" onClick={() => setSelected(u)}>{u.unit}</button></td><td>{u.total_quantity}</td><td>{u.total_amount ?? 'Unpriced'} {u.currency}{!!u.unpriced_event_count && <small className="id-text">{u.unpriced_event_count} unpriced events</small>}</td><td>{u.event_count}</td></tr>)}</tbody></table></div> : <div className="empty-state"><h3>{loading ? 'Loading usage' : error ? 'Usage unavailable' : 'No usage recorded'}</h3><p>{loading ? 'Retrieving measured usage for this tenant.' : error ? 'Reconnect or retry to inspect recorded usage.' : 'Recorded usage will appear here when resources report billable events.'}</p></div>}
    </div></section>
    {selected && <aside className="panel ops-inspector"><div className="panel-title"><div><span className="eyebrow">Measured resource</span><h2>{selected.unit}</h2></div><button className="icon-button" aria-label="Close resource usage details" onClick={() => setSelected(null)}><X size={17} aria-hidden="true" /></button></div><div className="panel-body"><dl className="ops-facts"><div><dt>Total quantity</dt><dd>{selected.total_quantity}</dd></div><div><dt>Recorded amount</dt><dd>{selected.total_amount ?? 'Unpriced'}</dd></div><div><dt>Currency</dt><dd>{selected.currency || 'Not reported'}</dd></div><div><dt>Usage events</dt><dd>{selected.event_count}</dd></div></dl><p className="ops-scope">Values are reported by the usage summary. Costs in different currencies are kept separate.</p><details><summary>Exact API values</summary><pre>{JSON.stringify(selected, null, 2)}</pre></details></div></aside>}
    </div>
  </div>;
}
