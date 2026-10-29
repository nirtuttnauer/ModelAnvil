import { Button, RecordTable, StatusBadge } from './ui';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { BarChart3, ChevronDown } from 'lucide-react';
import { chartRange, formatValue, interval, validPoints, type BarDatum, type Point } from './chart-data';
import './charts.css';


function usePlotWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(736);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(entries => {
      const measured = entries[0]?.contentRect.width;
      if (measured) setWidth(Math.max(280, Math.round(measured)));
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

const colors = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-neutral)'];

/** A chart with its heading. Pass `bordered={false}` when the chart already sits inside a card or section. */
export function ChartPanel({ title, description, children, action, bordered = false }: { title: string; description?: string; children: ReactNode; action?: ReactNode; bordered?: boolean }) {
  return <section className="chart-panel" data-ui="chart-panel" data-bordered={bordered || undefined}><div className="chart-heading"><div><h3>{title}</h3>{description && <p>{description}</p>}</div>{action}</div>{children}</section>;
}

export function ChartEmpty({ message = 'No measurements recorded yet.' }: { message?: string }) {
  return <div className="chart-empty"><BarChart3 size={28} aria-hidden="true" /><strong>Waiting for recorded data</strong><p>{message}</p></div>;
}

function DataTable({ children }: { children: ReactNode }) {
  return <details className="chart-data" data-ui="disclosure" data-variant="quiet"><summary>View data <ChevronDown size={14} aria-hidden="true" /></summary><div className="table-scroll" tabIndex={0}><RecordTable>{children}</RecordTable></div></details>;
}

export interface Series { name: string; points: Point[] }
export function LineChart({ series, xLabel = 'Step', yLabel = 'Value' }: { series: Series[]; xLabel?: string; yLabel?: string }) {
  const id = useId();
  const { ref, width } = usePlotWidth();
  const [hidden, setHidden] = useState<string[]>([]);
  const [selection, setSelection] = useState<{ name: string; x: number; y: number } | null>(null);
  const available = series.map(s => ({ ...s, points: validPoints(s.points) }));
  const visible = available.filter(s => !hidden.includes(s.name));
  const points = visible.flatMap(s => s.points);
  const activeSelection = selection && visible.some(s => s.name === selection.name && s.points.some(p => p.x === selection.x && p.y === selection.y)) ? selection : null;
  if (!available.some(s => s.points.length)) return <div className="chart" ref={ref}><ChartEmpty message="Run an experiment to record measurements. Curves will use the exact recorded steps." /></div>;
  const [xMin, xMax] = chartRange(points.map(p => p.x));
  const [yMin, yMax] = chartRange(points.map(p => p.y));
  const sx = (n: number) => 80 + (n - xMin) / (xMax - xMin) * (width - 120);
  const sy = (n: number) => 250 - (n - yMin) / (yMax - yMin) * 216;
  return <div className="chart" ref={ref}><div className="chart-legend">{available.map((s, i) => <Button key={s.name} type="button" aria-pressed={!hidden.includes(s.name)} className={hidden.includes(s.name) ? 'series-hidden' : ''} onClick={() => { setHidden(h => h.includes(s.name) ? h.filter(n => n !== s.name) : [...h, s.name]); setSelection(null); }}><span style={{ background: colors[i % colors.length] }} />{s.name}</Button>)}</div>
    <svg viewBox={`0 0 ${width} 300`} role="group" aria-labelledby={id}><title id={id}>{yLabel} by {xLabel}. Focus a point to inspect its value. Use the legend to toggle series.</title>
      {Array.from({ length: 5 }, (_, i) => { const f = i / 4; return <g key={i}><line className="chart-grid" x1={80} x2={width - 40} y1={250 - f * 216} y2={250 - f * 216} /><text className="chart-tick" x={70} y={254 - f * 216} textAnchor="end">{formatValue(yMin + f * (yMax - yMin), (yMax - yMin) / 4)}</text><line className="chart-grid" x1={80 + f * (width - 120)} x2={80 + f * (width - 120)} y1={34} y2={250} /><text className="chart-tick" x={80 + f * (width - 120)} y={273} textAnchor="middle">{formatValue(xMin + f * (xMax - xMin))}</text></g>; })}
      <text className="chart-axis" x={(width + 40) / 2} y={295} textAnchor="middle">{xLabel}</text><text className="chart-axis" x={15} y={142} textAnchor="middle" transform="rotate(-90 15 142)">{yLabel}</text>
      {visible.map(s => { const color = colors[available.findIndex(a => a.name === s.name) % colors.length]; return <g key={s.name}><polyline fill="none" stroke={color} strokeWidth="2.2" strokeLinejoin="round" points={s.points.map(p => `${sx(p.x)},${sy(p.y)}`).join(' ')} />{s.points.map((p, i) => <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={s.points.length === 1 ? 5 : 3} fill={color} stroke="var(--surface)" strokeWidth="1" tabIndex={0} role="button" aria-label={`${s.name}: ${xLabel} ${formatValue(p.x)}, ${yLabel} ${formatValue(p.y, (yMax - yMin) / 4)}`} onMouseEnter={() => setSelection({ name: s.name, ...p })} onFocus={() => setSelection({ name: s.name, ...p })} onClick={() => setSelection({ name: s.name, ...p })} onKeyDown={e => { if (e.key === 'Escape') setSelection(null); if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelection({ name: s.name, ...p }); } }}><title>{s.name}: {xLabel} {formatValue(p.x)} · {yLabel} {formatValue(p.y, (yMax - yMin) / 4)}</title></circle>)}</g>; })}
      {activeSelection && <line className="chart-crosshair" x1={sx(activeSelection.x)} x2={sx(activeSelection.x)} y1={34} y2={250} />}
    </svg><p className="chart-selection" aria-live="polite">{activeSelection ? `${activeSelection.name} · ${xLabel} ${formatValue(activeSelection.x)} · ${yLabel} ${formatValue(activeSelection.y, (yMax - yMin) / 4)}` : ''}</p>
    <DataTable><thead><tr><th>Series</th><th>{xLabel}</th><th>{yLabel}</th></tr></thead><tbody>{available.flatMap(s => s.points.map((p, i) => <tr key={`${s.name}-${i}`}><td>{s.name}</td><td>{String(p.x)}</td><td>{String(p.y)}</td></tr>))}</tbody></DataTable>
  </div>;
}

export function BarChart({ data, unit = 'Value', emptyMessage }: { data: BarDatum[]; unit?: string; emptyMessage?: string }) {
  const id = useId();
  const { ref, width } = usePlotWidth();
  const valid = data.filter(d => Number.isFinite(d.value));
  if (!valid.length) return <div className="chart" ref={ref}><ChartEmpty message={emptyMessage} /></div>;
  const [min, max] = chartRange(valid.flatMap(d => [d.value, ...(d.lower === undefined ? [] : [d.lower]), ...(d.upper === undefined ? [] : [d.upper])]), true);
  const left = Math.min(230, width * .34);
  const labelLength = Math.max(10, Math.floor((left - 20) / 7));
  const x = (v: number) => left + (v - min) / (max - min) * (width - left - 85);
  const height = Math.max(150, valid.length * 45 + 55);
  return <div className="chart" ref={ref}><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={id}><title id={id}>{unit}: {valid.map(d => `${d.label} ${formatValue(d.value)}`).join(', ')}. Full values in the data table.</title>
    {Array.from({ length: 5 }, (_, i) => { const v = min + (max - min) * i / 4; return <g key={i}><line className="chart-grid" x1={x(v)} x2={x(v)} y1={10} y2={height - 36} /><text className="chart-tick" x={x(v)} y={height - 15} textAnchor="middle">{formatValue(v)}</text></g>; })}
    {valid.map((d, i) => { const y = 18 + i * 45; return <g key={`${d.label}-${i}`}><text className="chart-row-label" x={8} y={y + 17}>{d.label.length > labelLength ? `${d.label.slice(0, labelLength - 1)}…` : d.label}</text><rect x={Math.min(x(0), x(d.value))} y={y} width={Math.max(0, Math.abs(x(d.value) - x(0)))} height={25} rx={3} fill={colors[(d.color ?? i) % colors.length]} opacity=".92"><title>{d.label}: {formatValue(d.value)} {unit}{d.detail ? ` · ${d.detail}` : ''}</title></rect>{d.lower !== undefined && d.upper !== undefined && <g className="chart-interval"><line x1={x(d.lower)} x2={x(d.upper)} y1={y + 12} y2={y + 12} /><line x1={x(d.lower)} x2={x(d.lower)} y1={y + 6} y2={y + 18} /><line x1={x(d.upper)} x2={x(d.upper)} y1={y + 6} y2={y + 18} /></g>}<text className="chart-row-value" x={width - 70} y={y + 17}>{formatValue(d.value)}</text></g>; })}
  </svg><div className="chart-unit">{unit}{valid.some(d => d.lower !== undefined) ? ' · intervals as recorded' : ''}</div>
    <DataTable><thead><tr><th>Label</th><th>{unit}</th><th>Context</th><th>Interval</th></tr></thead><tbody>{valid.map((d, i) => <tr key={i}><td>{d.label}</td><td>{String(d.value)}</td><td>{d.detail || '—'}</td><td>{d.lower !== undefined && d.upper !== undefined ? `${d.lower} – ${d.upper}` : 'Not reported'}</td></tr>)}</tbody></DataTable>
  </div>;
}

export function SegmentBar({ data, unit = 'items' }: { data: BarDatum[]; unit?: string }) {
  const valid = data.filter(d => Number.isFinite(d.value) && d.value >= 0);
  const total = valid.reduce((s, d) => s + d.value, 0);
  return <div className="segment-chart"><div className="segment-total"><span>Total {unit}</span><strong>{formatValue(total)}</strong></div><div className="segment-track" role="img" aria-label={valid.map(d => `${d.label}: ${formatValue(d.value)} ${unit}`).join(', ') || 'No recorded allocation'}>{valid.map((d, i) => <span key={i} style={{ width: `${total ? d.value / total * 100 : 0}%`, background: colors[(d.color ?? i) % colors.length] }} title={`${d.label}: ${formatValue(d.value)} ${unit}`} />)}</div><dl className="segment-legend">{valid.map((d, i) => <div key={i}><dt><i style={{ background: colors[(d.color ?? i) % colors.length] }} />{d.label}</dt><dd>{formatValue(d.value)} <small>{unit}{total ? ` · ${(d.value / total * 100).toFixed(1)}%` : ''}</small></dd></div>)}</dl></div>;
}

export interface RecordedMetric { key: string; slice_name: string; value: number; sample_count: number; uncertainty_interval?: unknown }
export function MetricsChart({ metrics }: { metrics: RecordedMetric[] }) {
  const keys = [...new Set(metrics.map(m => m.key))];
  const [selected, setSelected] = useState('');
  const key = keys.includes(selected) ? selected : keys[0];
  return <ChartPanel title="Performance by slice" description="Values, sample counts, and uncertainty as recorded." action={keys.length > 0 && <select aria-label="Metric to visualize" value={key} onChange={e => setSelected(e.target.value)}>{keys.map(k => <option key={k}>{k}</option>)}</select>}><BarChart data={metrics.filter(m => m.key === key).map(m => ({ label: m.slice_name || 'All samples', value: m.value, detail: `${m.sample_count} samples`, ...interval(m.uncertainty_interval), color: 0 }))} unit={key || 'Metric'} emptyMessage="Select an evaluation with recorded slice metrics. Missing evidence is not shown as zero." /></ChartPanel>;
}

export function EventTimeline({ events }: { events: { label: string; detail?: string; status?: string }[] }) {
  return <ol className="event-timeline">{events.map((e, i) => <li key={i}><span className={`timeline-dot state-${e.status || 'pending'}`} /><div><strong>{e.label}</strong>{e.detail && <small>{e.detail}</small>}</div>{e.status && <StatusBadge status={e.status} />}</li>)}</ol>;
}
