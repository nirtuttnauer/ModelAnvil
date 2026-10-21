import { CheckCircle2, CircleHelp, XCircle } from 'lucide-react';
import { DataValue, dataLabel } from './DataInspector';
import './workbench-components.css';

export interface ReleaseCriterion { key: string; required: unknown; actual: unknown; passed: boolean; evidenceHref?: string }
export function ReleaseGateChecklist({ criteria, state, evidenceHref }: { criteria: ReleaseCriterion[]; state: string; evidenceHref?: string }) {
  return <section className="gate-checklist" aria-label="Release gate checklist">
    <div className="wb-row"><h3>Local export review</h3><span className="wb-status">{dataLabel(state)}</span></div>
    <p className="wb-muted">Frozen local review. Production qualification remains unavailable.</p>
    {evidenceHref && <a href={evidenceHref}>Open exact evaluation</a>}
    {criteria.length ? <ul className="wb-checklist">{criteria.map(criterion => {
      const missing = criterion.actual == null;
      const Icon = missing ? CircleHelp : criterion.passed ? CheckCircle2 : XCircle;
      const status = missing ? 'Missing evidence' : criterion.passed ? 'Passed' : 'Failed';
      return <li key={criterion.key}><Icon size={20} aria-hidden="true" className={missing ? 'wb-warning' : criterion.passed ? 'wb-success' : 'wb-error'} /><div>
        <div className="wb-row"><strong title={criterion.key}>{dataLabel(criterion.key)}</strong><span className={missing ? 'wb-warning' : criterion.passed ? 'wb-success' : 'wb-error'}>{status}</span></div>
        <dl className="wb-gate-values"><div><dt>Required</dt><dd><DataValue value={criterion.required} /></dd></div><div><dt>Recorded</dt><dd><DataValue value={criterion.actual} /></dd></div></dl>
        {criterion.evidenceHref && <a href={criterion.evidenceHref}>Inspect criterion evidence</a>}
      </div></li>;
    })}</ul> : <p className="wb-empty">No review criteria were returned. A recorded state alone does not establish a passing review.</p>}
  </section>;
}
