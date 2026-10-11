export type RunKind = 'job' | 'training' | 'evaluation';

const RUN_KINDS: RunKind[] = ['job', 'training', 'evaluation'];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function runRoute(kind: RunKind, id: string): string {
  return `runs/${kind}/${id}`;
}

export function runHash(kind: RunKind, id: string): string {
  return `#${runRoute(kind, id)}`;
}

export function parseRunRoute(hash: string): { kind: RunKind; id: string } | null {
  const [head, kind, id, ...rest] = hash.replace(/^#/, '').split('?')[0].split('/');
  if (head !== 'runs' || rest.length) return null;
  if (!RUN_KINDS.includes(kind as RunKind)) return null;
  if (!UUID.test(id)) return null;
  return { kind: kind as RunKind, id };
}

export function detailPath(kind: RunKind, id: string): string {
  return `/api/v1/run-details/${kind}/${id}/`;
}

export function attemptsPath(kind: RunKind, id: string): string {
  return `${detailPath(kind, id)}attempts/`;
}