export const EVIDENCE_LABELS: Record<string, string> = {
  configuration_only: 'Configuration only',
  simulation: 'Simulation',
  fixture: 'Simulation',
  integrated_execution: 'Integrated execution',
  hardware_qualified: 'Hardware qualified',
  unknown: 'Unknown evidence',
};

export function evidenceTitle(level?: string) {
  return EVIDENCE_LABELS[level || ''] || EVIDENCE_LABELS.unknown;
}

export function productionTitle(qualified?: boolean) {
  return qualified ? 'Production qualified' : 'Production qualification unavailable';
}
