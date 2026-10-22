import { Button, Card, FactList, Field, MetricSummary, RecordTable } from '../components/ui';
import { Feedback } from '../components/Feedback';
import { InspectorPanel } from '../components/InspectorPanel';
import { useDraft } from '../components/Draft';
import { BudgetLedger } from '../components/BudgetLedger';
import { DataInspector } from '../components/DataInspector';
import { useState, useEffect } from 'react';
import { RefreshCw } from 'lucide-react';
import { apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartPanel, ChartEmpty, BarChart } from '../components/Charts';
import { ReceiptText } from 'lucide-react';
import './operations.css';
import { BudgetPolicyEditor } from '../components/BudgetPolicyEditor';

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
  const filters = useDraft('budget-filters', { scope: 'project', dateFrom: '', dateTo: '', unit: '', currency: 'all' });
  const [scope, setScope] = filters.field('scope'), [dateFrom, setDateFrom] = filters.field('dateFrom'), [dateTo, setDateTo] = filters.field('dateTo');
  const [unit, setUnit] = filters.field('unit'), [currency, setCurrency] = filters.field('currency');
  const params = new URLSearchParams({ scope });
  if (dateFrom) params.set('date_from', dateFrom); if (dateTo) params.set('date_to', dateTo);
  if (unit) params.set('unit', unit); if (currency !== 'all') params.set('currency', currency);
  const ledgerQuery = '?' + params.toString();
  const [summary, setSummary] = useState<UsageSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<UsageSummaryItem | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setSummary(null); setSelected(null);
    apiRequest<UsageSummaryResponse>('/api/v1/usage-events/summary/'+ledgerQuery, token, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setSummary(data); })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refreshKey, retry, ledgerQuery]);
  const stats = [
    { label: 'Active reservations', value: summary?.active_reservations_count ?? '—', hint: 'Awaiting completion or release' },
    { label: 'Reservation units', value: summary?.reserved_by_unit?.length ?? '—', hint: 'Each resource unit kept separate' },
    { label: 'Budget policies', value: summary?.total_policies ?? '—', hint: 'Configured spending policies' },
    { label: 'Resource units', value: summary ? new Set(summary.usage_by_unit.map(row => row.unit)).size : '—', hint: 'Units with recorded usage' },
  ];
  const currencies = [...new Set(summary?.usage_by_unit.map(u => u.currency) || [])];
  return <div className="resource-view operations-page">
    <div className="page-actions"><Button disabled={loading} onClick={() => setRetry(v => v + 1)}><RefreshCw size={15} aria-hidden="true" />Refresh usage</Button></div>
    <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
    <details className="workspace-details"><summary>Filter ledger scope, dates and units</summary><div className="form-grid"><label>Ledger scope<select value={scope} onChange={e => setScope(e.target.value)}><option value="project">Current project and accessible shared executions</option><option value="tenant">Tenant-wide (unrestricted keys only)</option></select></label><label>From (UTC)<Field type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} /></label><label>Through (UTC)<Field type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} /></label><label>Resource unit<Field value={unit} onChange={e => setUnit(e.target.value)} placeholder="All units" /></label><label>Currency<select value={currency} onChange={e => setCurrency(e.target.value)}><option value="all">All currencies, kept separate</option><option value="">Unpriced / no currency</option><option value="USD">USD</option><option value="EUR">EUR</option></select></label></div></details>
    <div className="cards">{stats.map(s => <MetricSummary as="article" key={s.label} label={s.label} value={s.value} detail={s.hint} />)}</div>
    <BudgetPolicyEditor token={token} refreshKey={refreshKey + retry} onChanged={() => setRetry(v => v + 1)} />
    <div className={`ops-workspace ${selected ? 'with-inspector' : ''}`}>
    <Card className="panel"><div className="panel-title"><div><h2>Recorded usage & costs</h2><p>Measured usage by resource unit. Currency is reported with each cost.</p></div></div><div className="panel-body">
      {summary && summary.usage_by_unit.length > 0 ? <div className="table-scroll" tabIndex={0}><RecordTable className="resource-table"><thead><tr><th>Resource unit</th><th>Total quantity</th><th>Recorded cost</th><th>Events</th></tr></thead><tbody>{summary.usage_by_unit.map(u => <tr key={`${u.unit}-${u.currency}`} className={selected === u ? 'ops-selected-row' : ''}><td><Button className="text-button" onClick={() => setSelected(u)}>{u.unit}</Button></td><td>{u.total_quantity}</td><td>{u.total_amount ?? 'Unpriced'} {u.currency}{!!u.unpriced_event_count && <small className="id-text">{u.unpriced_event_count} unpriced events</small>}</td><td>{u.event_count}</td></tr>)}</tbody></RecordTable></div> : !loading && !error && <Feedback state="empty" title="No usage recorded" description="Recorded usage will appear here when resources report billable events." />}
    </div></Card>
    {selected && <InspectorPanel eyebrow="Measured resource" title={selected.unit} closeLabel="Close resource usage details" onClose={() => setSelected(null)}><FactList><div><dt>Total quantity</dt><dd>{selected.total_quantity}</dd></div><div><dt>Recorded amount</dt><dd>{selected.total_amount ?? 'Unpriced'}</dd></div><div><dt>Currency</dt><dd>{selected.currency || 'Not reported'}</dd></div><div><dt>Usage events</dt><dd>{selected.event_count}</dd></div></FactList><p className="ops-scope">Values are reported by the usage summary. Costs in different currencies are kept separate.</p><details><summary>Exact API values</summary><DataInspector value={selected} /></details></InspectorPanel>}
    </div>
    <details className="workspace-details"><summary>Cost charts and reservation summary</summary><div className="ops-chart-grid">
      {currencies.length ? currencies.map(currency => <ChartPanel key={currency} title={`Recorded costs · ${currency || 'unspecified currency'}`} description="Measured amount by resource unit. Each currency uses a separate scale."><BarChart data={summary!.usage_by_unit.filter(u => u.currency === currency && u.total_amount !== null && u.total_amount.trim() !== '' && Number.isFinite(Number(u.total_amount))).map(u => ({ label: u.unit, value: Number(u.total_amount), detail: `${u.total_quantity} measured units · ${u.event_count} events`, color: 0 }))} unit={currency || 'currency not reported'} emptyMessage="No numeric cost measurements were reported in this currency." /></ChartPanel>) : <ChartPanel title="Recorded resource costs" description="Measurements will be grouped by their reported currency."><ChartEmpty message="Billable resource events are needed to display measured costs." /></ChartPanel>}
      <ChartPanel title="Reservation ledger" description="Summary returned by the usage API."><div className="ops-ledger"><ReceiptText size={30} aria-hidden="true" /><span>Reserved for pending work</span><strong>{summary?.reserved_by_unit?.length ? summary.reserved_by_unit.map(row => `${row.reserved_amount} ${row.unit}${row.currency ? ` · ${row.currency}` : ''}`).join(' / ') : summary?.total_reserved_amount ?? '—'}</strong><p>{summary ? `${summary.active_reservations_count} active reservations · ${summary.total_policies} configured policies` : 'Connect to retrieve the tenant reservation summary.'}</p><small>Reserved quantities are grouped by policy unit and currency. Policy limits and forecasts are not inferred.</small></div></ChartPanel>
    </div>
    </details>
    <BudgetLedger token={token} query={ledgerQuery} refreshKey={refreshKey + retry} />
  </div>;
}
