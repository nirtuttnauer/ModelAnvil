import { Identifier, isOpaqueIdentifier } from './Identifier';
import { Button } from './ui';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { CheckCircle2, CircleHelp, XCircle } from 'lucide-react';
import { DataInspector, dataLabel, TextContent } from './DataInspector';
import './workbench-components.css';

export interface PreflightReport {
  status: string; recipe_type: string; execution_mode: string; checked_at?: string;
  samples: { sample_id: string | null; text_preview: string; token_count: number; token_ids: number[] }[];
  checks: { check: string; category: string; status: string; blocking: boolean; reason: string; corrective_action?: string | null; detail?: Record<string, unknown> }[];
  estimate: { known: boolean; source: string; assumptions: string[]; units: Record<string, string | null>; currency: string | null; uncertainty: string;
    parameter_count?: number; total_tokens?: number; estimated_flops?: number; estimated_duration_seconds?: number;
    estimated_cost: { known: boolean; value?: number; reason?: string } };
  preflight_token: string | null; pins: Record<string, unknown> | null; requirements: Record<string, unknown>;
  budget: { unit: string; limit: string; committed: string; remaining: string; requested: number } | null;
  sample_count: number | null; capacity_note: string; expires_in_seconds: number; blocking_checks: string[];
  runtime_scope: { targets: { target_id: string; label: string; category: string; status: string; reason: string; corrective_action?: string | null }[]; available: string[]; unavailable: string[] };
}

export function PreflightChecklist({ report, busy, form, onLaunch, onRefresh, title = 'Training preflight', launchLabel = 'Launch fine-tuning', focusOnReport = true, compact = false }: {
  report: PreflightReport; busy?: boolean; form?: string; onLaunch?: () => void; onRefresh?: () => void; title?: string; launchLabel?: string;
  focusOnReport?: boolean; compact?: boolean;
}) {
  const panel = useRef<HTMLElement>(null);
  const deadline = useMemo(() => (report.checked_at && Number.isFinite(Date.parse(report.checked_at)) ? Date.parse(report.checked_at) : Date.now()) + report.expires_in_seconds * 1000, [report]);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { if (focusOnReport) panel.current?.focus(); setNow(Date.now()); const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, [report, focusOnReport]);
  const expiryUnknown = !Number.isFinite(deadline);
  const expired = !expiryUnknown && now >= deadline;
  const ready = report.status === 'approved' && !!report.preflight_token && !expired && !expiryUnknown && !report.blocking_checks.length;
  const groups = [...new Set(report.checks.map(check => check.category))];
  const duration = report.estimate.estimated_duration_seconds;
  const finite = (value: unknown, transform?: (value: number) => ReactNode) => typeof value === 'number' && Number.isFinite(value) ? transform ? transform(value) : value.toLocaleString() : 'Unknown';
  return <section ref={panel} tabIndex={-1} className="preflight-checklist detail-box" aria-label={title}>
    <div className="wb-row"><h3>{title}</h3><span className={`wb-status ${ready ? 'wb-success' : 'wb-warning'}`} role="status">{expiryUnknown ? 'Expiry not reported' : expired ? 'Preview expired' : ready ? 'Ready to launch' : report.status === 'approved' && !report.preflight_token ? 'Launch token unavailable' : 'Blocked'}</span></div>
    {report.blocking_checks.length > 0 && <p className="wb-error">Blocking checks: {report.blocking_checks.map(dataLabel).join(', ')}</p>}
    {compact && ready && <p>Your model, dataset, compute, storage and training allowance passed their checks. You can start training.</p>}
    <details open={!compact || !ready || report.checks.some(check => !['pass', 'passed'].includes(check.status))}>
    <summary>Compatibility, capacity and budget details</summary>
    {groups.map(category => <section className="preflight-group" key={category} aria-label={`${dataLabel(category)} checks`}><h4>{dataLabel(category)}</h4><ul className="wb-checklist">{report.checks.filter(check => check.category === category).map(check => {
      const passed = ['pass', 'passed'].includes(check.status), failed = ['fail', 'failed'].includes(check.status);
      const Icon = passed ? CheckCircle2 : failed ? XCircle : CircleHelp;
      return <li key={check.check}><Icon size={20} aria-hidden="true" className={passed ? 'wb-success' : failed && check.blocking ? 'wb-error' : 'wb-warning'} /><div>
        <div className="wb-row"><strong title={check.check}>{dataLabel(check.check)}</strong><span>{passed ? 'Passed' : failed ? check.blocking ? 'Blocked' : 'Warning' : dataLabel(check.status)}</span></div>
        <p>{check.reason}</p>{check.corrective_action && <p className="wb-next-action"><strong>Next step:</strong> {check.corrective_action}</p>}
        {check.detail && Object.keys(check.detail).length > 0 && <details><summary>Check details and units</summary><DataInspector value={check.detail} /></details>}
      </div></li>;
    })}</ul></section>)}
    {!report.checks.length && <p className="wb-empty">No individual checks were returned.</p>}
    <div className="preflight-summary-grid"><section><h4>Resolved requirements</h4><dl className="wb-facts">
      <div><dt>Runtime</dt><dd>{String(report.requirements.runtime ?? 'Unresolved')}</dd></div>
      <div><dt>Worker slots</dt><dd>{finite(report.requirements.cpu_slots)}</dd></div>
      <div><dt>Host memory</dt><dd>{finite(report.requirements.memory_bytes, value => `${value / 1048576} MiB`)}</dd></div>
      <div><dt>Projected storage</dt><dd>{finite(report.requirements.storage_bytes, value => `${(value / 1048576).toFixed(2)} MiB`)}</dd></div>
      {report.requirements.accelerator != null && <><div><dt>GPU devices</dt><dd>{finite(report.requirements.gpu_count)}</dd></div><div><dt>Precision</dt><dd>{String(report.requirements.precision ?? 'Unknown')}</dd></div></>}
    </dl>{report.requirements.storage_assumption != null && <p className="wb-muted">{String(report.requirements.storage_assumption)}</p>}
    {report.requirements.accelerator != null && <details><summary>Resolved GPU device and capacity source</summary><DataInspector value={report.requirements.accelerator} /></details>}
    <details><summary>Resolved recipe parameters</summary><DataInspector value={{ config: report.requirements.config, optimizer: report.requirements.optimizer }} /></details></section>
    <section><h4>Estimate and budget</h4><dl className="wb-facts"><div><dt>Engine time</dt><dd>{report.estimate.known && typeof duration === 'number' && Number.isFinite(duration) ? `${Number(duration.toPrecision(3))} ${report.estimate.units.duration || 'seconds'}` : 'Unknown — no matching measured pilot'}</dd></div>
      <div><dt>Next-token pairs</dt><dd>{finite(report.estimate.total_tokens)}</dd></div><div><dt>Estimated cost</dt><dd>{report.estimate.estimated_cost.known && typeof report.estimate.estimated_cost.value === 'number' && Number.isFinite(report.estimate.estimated_cost.value) ? `${report.estimate.estimated_cost.value} ${report.estimate.currency || ''}` : `Unknown — ${report.estimate.estimated_cost.reason || 'No recorded rate'}`}</dd></div>
      {report.budget && <><div><dt>Requested</dt><dd>{report.budget.requested} {report.budget.unit}</dd></div><div><dt>Remaining / limit</dt><dd>{report.budget.remaining} / {report.budget.limit} {report.budget.unit}</dd></div><div><dt>Already committed</dt><dd>{report.budget.committed} {report.budget.unit}</dd></div></>}
    </dl><p className="wb-muted">{report.estimate.source} · uncertainty: {report.estimate.uncertainty}</p>{report.estimate.assumptions.length > 0 && <details><summary>Estimate assumptions</summary><ul>{report.estimate.assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul></details>}</section></div>
    {!!report.samples.length && <details><summary>Encoded training samples · {report.sample_count ?? 'Unknown'} total, showing {report.samples.length}</summary><ol className="preflight-samples">{report.samples.map((sample, index) => <li key={index}><strong>{sample.sample_id && !isOpaqueIdentifier(sample.sample_id) ? sample.sample_id : `Sample ${index + 1}`}</strong><Identifier value={sample.sample_id} label="Source sample ID" /><p className="wb-muted">{sample.token_count} tokens</p><TextContent text={sample.text_preview} /><details><summary>Exact token IDs</summary><div className="wb-token-ids">{sample.token_ids.map((token, i) => <code key={i}>{token}</code>)}</div></details></li>)}</ol></details>}
    <details><summary>Pinned input revisions and digests</summary><DataInspector value={report.pins} /></details>
    </details>
    <p className="wb-muted">{report.capacity_note}</p><p className="wb-muted">{expired || expiryUnknown ? 'Run preflight again to refresh the launch approval.' : `Preview expires in ${Math.max(1, Math.ceil((deadline - now) / 60000))} minutes.`}</p>
    <div className="actions">{onRefresh && <Button type="button" disabled={busy} onClick={onRefresh}>Refresh preflight</Button>}{(form || onLaunch) && <Button form={form} type={form ? 'submit' : 'button'} className="primary" disabled={busy || !ready} onClick={onLaunch}>{busy ? 'Launching…' : launchLabel}</Button>}</div>
  </section>;
}
