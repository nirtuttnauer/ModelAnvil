import { evidenceTitle, productionTitle } from '../api/evidence-label';
import type { StatusTone } from '../api/status';
import { StatusBadge } from './ui';

export interface EvidenceRecord { level?: string; source?: string; production_qualified?: boolean }

const TONES: Record<string, StatusTone> = { integrated_execution: 'success', hardware_qualified: 'success', configuration_only: 'neutral', simulation: 'caution', fixture: 'caution' };

export function EvidenceLabel({ evidence }: { evidence?: EvidenceRecord | null }) {
  const record = evidence || {};
  return <div data-ui="actions">
    <StatusBadge status={record.level || 'unknown'} tone={TONES[record.level || ''] ?? 'caution'} label={evidenceTitle(record.level)} />
    <span className="muted">{record.source || 'No execution source reported'}</span>
    <span className="muted">{productionTitle(record.production_qualified)}</span>
  </div>;
}
