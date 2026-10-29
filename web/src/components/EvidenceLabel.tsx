import { evidenceTitle, productionTitle } from '../api/evidence-label';

export interface EvidenceRecord { level?: string; source?: string; production_qualified?: boolean }

export function EvidenceLabel({ evidence }: { evidence?: EvidenceRecord | null }) {
  const record = evidence || {};
  return <p className="evidence-label">
    <strong>{evidenceTitle(record.level)}</strong>
    <span className="muted">{record.source || 'No execution source reported'}</span>
    <span className="muted">{productionTitle(record.production_qualified)}</span>
  </p>;
}
