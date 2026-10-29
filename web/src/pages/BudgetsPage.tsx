import { Button, Disclosure, KeyValueList, RecordTable, Section, Select, TextControl } from '../components/ui';
import { EmptyState } from '../components/Feedback';
import { InspectorPanel } from '../components/InspectorPanel';
import { useDraft } from '../components/Draft';
import { BudgetLedger } from '../components/BudgetLedger';
import { DataInspector } from '../components/DataInspector';
import { useState, useEffect } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { ResourceState } from '../components/ResourceState';
import { ChartPanel, ChartEmpty, BarChart } from '../components/Charts';
import { BudgetPolicyEditor } from '../components/BudgetPolicyEditor';
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
  const currencies = [...new Set(summary?.usage_by_unit.map(u => u.currency) || [])];
  const rows = summary?.usage_by_unit ?? [];
  const reserved = summary?.reserved_by_unit?.length ? summary.reserved_by_unit.map(row => `${row.reserved_amount} ${row.unit}${row.currency ? ` · ${row.currency}` : ''}`).join(' / ') : summary?.total_reserved_amount ?? 'None';

  return <div className="ops-page">
    <BudgetPolicyEditor token={token} refreshKey={refreshKey + retry} onChanged={() => setRetry(v => v + 1)} />
    <Section title="Usage" description="Measured usage by resource unit for the selected scope." actions={<Button type="button" variant="quiet" disabled={loading} onClick={() => setRetry(v => v + 1)}>Refresh usage</Button>}>
      <Disclosure summary="Filters" variant="quiet"><div data-ui="field-grid">
        <Select label="Ledger scope" value={scope} onChange={e => setScope(e.target.value)} options={[{ value: 'project', label: 'Current project and shared executions' }, { value: 'tenant', label: 'Tenant-wide (unrestricted keys only)' }]} />
        <TextControl label="Resource unit" value={unit} onChange={e => setUnit(e.target.value)} placeholder="All units" />
        <TextControl label="From (UTC)" type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        <TextControl label="Through (UTC)" type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
        <Select label="Currency" value={currency} onChange={e => setCurrency(e.target.value)} options={[{ value: 'all', label: 'All currencies, kept separate' }, { value: '', label: 'Unpriced / no currency' }, { value: 'USD', label: 'USD' }, { value: 'EUR', label: 'EUR' }]} />
      </div></Disclosure>
      <ResourceState loading={loading} error={error} onRetry={() => setRetry(v => v + 1)} />
      {summary && <p className="ops-count">{summary.active_reservations_count} active {summary.active_reservations_count === 1 ? 'reservation' : 'reservations'} · reserved {reserved} · {summary.total_policies} {summary.total_policies === 1 ? 'policy' : 'policies'}</p>}
      <div data-ui="split" data-open={selected ? '' : undefined}>
        <div className="ops-main">
          {!loading && !error && !rows.length && <EmptyState title="No usage recorded" description="Recorded usage appears here when resources report billable events." />}
          {rows.length > 0 && <div className="table-scroll" tabIndex={0}><RecordTable>
            <thead><tr><th>Resource unit</th><th>Total quantity</th><th>Recorded cost</th><th>Events</th></tr></thead>
            <tbody>{rows.map(u => <tr key={`${u.unit}-${u.currency}`} aria-selected={selected === u || undefined}>
              <td><Button type="button" variant="quiet" size="sm" onClick={() => setSelected(u)}>{u.unit}</Button></td>
              <td>{u.total_quantity}</td>
              <td>{u.total_amount ?? 'Unpriced'} {u.currency}{!!u.unpriced_event_count && <small>{u.unpriced_event_count} unpriced events</small>}</td>
              <td>{u.event_count}</td>
            </tr>)}</tbody>
          </RecordTable></div>}
        </div>
        {selected && <InspectorPanel key={`${selected.unit}-${selected.currency}`} eyebrow="Resource unit" title={selected.unit} closeLabel="Close resource usage details" onClose={() => setSelected(null)}>
          <KeyValueList items={[
            { label: 'Total quantity', value: selected.total_quantity },
            { label: 'Recorded amount', value: selected.total_amount ?? 'Unpriced' },
            { label: 'Currency', value: selected.currency || 'Not reported' },
            { label: 'Usage events', value: selected.event_count },
            { label: 'Unpriced events', value: selected.unpriced_event_count ?? 0 },
          ]} />
          <Disclosure summary="Exact API values" variant="quiet"><DataInspector value={selected} /></Disclosure>
          <p className="ops-footnote">Costs in different currencies are kept separate.</p>
        </InspectorPanel>}
      </div>
    </Section>
    <BudgetLedger token={token} query={ledgerQuery} refreshKey={refreshKey + retry} />
    <Disclosure summary="Insights" variant="card"><div className="ops-charts">
      {currencies.length ? currencies.map(currency => <ChartPanel key={currency} title={`Recorded costs · ${currency || 'unspecified currency'}`} description="Measured amount by resource unit. Each currency uses a separate scale."><BarChart data={summary!.usage_by_unit.filter(u => u.currency === currency && u.total_amount !== null && u.total_amount.trim() !== '' && Number.isFinite(Number(u.total_amount))).map(u => ({ label: u.unit, value: Number(u.total_amount), detail: `${u.total_quantity} measured units · ${u.event_count} events`, color: 0 }))} unit={currency || 'currency not reported'} emptyMessage="No numeric cost measurements were reported in this currency." /></ChartPanel>) : <ChartPanel title="Recorded resource costs" description="Measurements are grouped by their reported currency."><ChartEmpty message="Billable resource events are needed to display measured costs." /></ChartPanel>}
      <ChartPanel title="Reservations" description="Summary returned by the usage API."><KeyValueList items={[
        { label: 'Reserved for pending work', value: reserved },
        { label: 'Active reservations', value: summary?.active_reservations_count ?? 'Not loaded' },
        { label: 'Budget policies', value: summary?.total_policies ?? 'Not loaded' },
      ]} /></ChartPanel>
    </div></Disclosure>
  </div>;
}
