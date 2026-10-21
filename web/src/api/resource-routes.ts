export type ResourceKind = 'model-version' | 'dataset-revision';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function resourceHash(kind: ResourceKind, id: string): string { return `#resources/${kind}/${encodeURIComponent(id)}`; }
export function parseResourceRoute(hash: string): { kind: ResourceKind; id: string } | null {
  const [head, kind, id, ...extra] = hash.slice(1).split('?')[0].split('/');
  return head === 'resources' && ['model-version', 'dataset-revision'].includes(kind) && UUID.test(id || '') && !extra.length ? { kind: kind as ResourceKind, id } : null;
}
export function handoffHash(screen: 'training' | 'chat' | 'evaluation' | 'annotation' | 'releases', kind: ResourceKind, id: string): string {
  return `#${screen}?${kind.replace('-', '_')}=${encodeURIComponent(id)}`;
}
export function auditResourceHash(type: string, id: string): string | null {
  if (!UUID.test(id)) return null;
  if (type === 'model_version') return resourceHash('model-version', id);
  if (type === 'dataset_revision') return resourceHash('dataset-revision', id);
  if (type === 'training_run') return `#runs/training/${id}`;
  if (type === 'evaluation_run') return `#runs/evaluation/${id}`;
  if (type === 'job') return `#runs/job/${id}`;
  if (type === 'release_version') return `#releases?release_version=${id}`;
  return null;
}
