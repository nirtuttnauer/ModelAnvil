export const DRAFT_TTL_MS = 8 * 60 * 60 * 1000;
const PREFIX = 'modelanvil.draft.v1:';
export type DraftValues = Record<string, string | number | boolean>;
export type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'key' | 'length'>;

export function draftKey(organization: string, project: string | null, form: string, resource = 'new'): string {
  return PREFIX + JSON.stringify([organization, project, form, resource]);
}
function validate<T extends DraftValues>(values: unknown, defaults: T): T {
  if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error('Invalid draft.');
  const result = { ...defaults };
  for (const field of Object.keys(defaults)) {
    if (/password|secret|credential|api.?key|preflight.?token|authorization/i.test(field)) throw new Error('Credentials cannot be stored in drafts.');
    const value = (values as DraftValues)[field];
    if (value === undefined) continue;
    if (typeof value !== typeof defaults[field] || (typeof value === 'number' && !Number.isFinite(value))) throw new Error('Invalid draft field.');
    result[field as keyof T] = value as T[keyof T];
  }
  return result;
}
export function assertDraftFields(defaults: DraftValues): void { validate(defaults, defaults); }
export function readDraft<T extends DraftValues>(storage: DraftStorage, key: string, defaults: T, now = Date.now()): T | null {
  const raw = storage.getItem(key);
  if (!raw) return null;
  try {
    const item = JSON.parse(raw);
    if (!Number.isFinite(item.expiresAt) || item.expiresAt <= now || item.expiresAt > now + DRAFT_TTL_MS) throw new Error('Expired draft.');
    return validate(item.values, defaults);
  } catch { storage.removeItem(key); return null; }
}
export function writeDraft<T extends DraftValues>(storage: DraftStorage, key: string, values: T, defaults: T, now = Date.now()): void {
  const body = JSON.stringify({ expiresAt: now + DRAFT_TTL_MS, values: validate(values, defaults) });
  if (body.length > 1_000_000) throw new Error('Draft exceeds the local storage limit.');
  storage.setItem(key, body);
}
export function pruneDrafts(storage: DraftStorage, now = Date.now()): void {
  for (let i = storage.length - 1; i >= 0; i--) {
    const key = storage.key(i);
    if (!key?.startsWith(PREFIX)) continue;
    try { const item = JSON.parse(storage.getItem(key) || '{}'); if (!Number.isFinite(item.expiresAt) || item.expiresAt <= now) storage.removeItem(key); }
    catch { storage.removeItem(key); }
  }
}
