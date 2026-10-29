import { Button, Disclosure } from './ui';
import { createContext, useContext, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { assertDraftFields, draftKey, pruneDrafts, readDraft, writeDraft, type DraftValues } from '../api/drafts';
import { DRAFT_TTL_MS } from '../api/drafts';

const memoryDrafts = new Map<string, { values: DraftValues; expiresAt: number; status: string }>();
/** Reset volatile drafts when creating an isolated preview session. */
export function resetDraftMemory() { memoryDrafts.clear(); }

export const DraftScope = createContext<{ organization: string; project: string | null } | null>(null);

export function useDraft<T extends DraftValues>(form: string, defaults: T, resource = 'new') {
  assertDraftFields(defaults);
  const scope = useContext(DraftScope);
  const key = scope ? draftKey(scope.organization, scope.project, form, resource) : '';
  const activeKey = useRef(key); activeKey.current = key;
  function load() {
    const memory = key ? memoryDrafts.get(key) : null;
    if (memory && memory.expiresAt > Date.now()) return { key, values: memory.values as T, status: memory.status === 'unsaved' ? 'unsaved' : 'restored' };
    if (key) memoryDrafts.delete(key);
    try {
      pruneDrafts(sessionStorage);
      const saved = key ? readDraft(sessionStorage, key, defaults) : null;
      if (saved) memoryDrafts.set(key, { values: saved, expiresAt: JSON.parse(sessionStorage.getItem(key)!).expiresAt, status: 'saved' });
      return { key, values: saved || { ...defaults }, status: saved ? 'restored' : 'empty' };
    } catch { return { key, values: { ...defaults }, status: 'unavailable' }; }
  }
  const [state, setState] = useState(load);
  // Resource switches must show the new resource's values in the same render.
  const loaded = state.key === key ? state : load();
  const current = loaded.status === 'empty' ? { ...loaded, values: { ...defaults } } : loaded;
  const currentRef = useRef(current); currentRef.current = current;
  useEffect(() => { if (state.key !== key) setState(load()); }, [key]);
  useEffect(() => {
    const expire = setInterval(() => {
      for (const [key, item] of memoryDrafts) if (item.expiresAt <= Date.now()) {
        memoryDrafts.delete(key);
        if (key === currentRef.current.key) setState(current => ({ ...current, status: 'expired' }));
      }
      try { pruneDrafts(sessionStorage); } catch { /* Browser storage may be unavailable. */ }
    }, 60000);
    const warn = (e: BeforeUnloadEvent) => { if (['unsaved', 'expired'].includes(currentRef.current.status)) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', warn);
    return () => { clearInterval(expire); window.removeEventListener('beforeunload', warn); };
  }, []);
  function field<K extends keyof T>(name: K): [T[K], Dispatch<SetStateAction<T[K]>>] {
    return [current.values[name], update => {
      if (activeKey.current !== key) return;
      const prior = currentRef.current;
      const value = typeof update === 'function' ? (update as (v: T[K]) => T[K])(prior.values[name]) : update;
      if (value === prior.values[name]) return;
      const values = { ...prior.values, [name]: value };
      let status = 'unsaved';
      try { if (key) { writeDraft(sessionStorage, key, values, defaults); status = 'saved'; } } catch { /* Keep edits in memory when browser storage is unavailable. */ }
      if (key) memoryDrafts.set(key, { values, status, expiresAt: Date.now() + DRAFT_TTL_MS });
      const next = { key, values, status }; currentRef.current = next; setState(next);
    }];
  }
  function discard() {
    if (activeKey.current !== key) return;
    try { if (key) sessionStorage.removeItem(key); } catch { /* Reset in-memory values too. */ }
    if (key) memoryDrafts.delete(key);
    const next = { key, values: { ...defaults }, status: 'empty' }; currentRef.current = next; setState(next);
  }
  function restore() { if (activeKey.current === key) { const next = load(); currentRef.current = next; setState(next); } }
  return { field, discard, restore, status: current.status };
}

/** One-line draft state with Restore/Discard; the storage explanation folds away. */
export function DraftIndicator({ draft, disabled = false }: { draft: { status: string; restore(): void; discard(): void }; disabled?: boolean }) {
  const text = ({ saved: 'Draft saved in this tab', restored: 'Draft restored', empty: 'No draft', unsaved: 'Draft unsaved · browser storage unavailable', expired: 'Draft expired', unavailable: 'Draft storage unavailable' } as Record<string, string>)[draft.status] ?? 'Draft unsaved';
  return <div data-ui="draft" aria-label="Local draft">
    <span role="status">{text}</span>
    {['saved', 'restored'].includes(draft.status) && <Button type="button" variant="quiet" size="sm" disabled={disabled} onClick={draft.restore}>Restore</Button>}
    {draft.status !== 'empty' && <Button type="button" variant="quiet" size="sm" disabled={disabled} onClick={draft.discard}>Discard draft</Button>}
    <Disclosure summary="About drafts" variant="quiet"><p className="muted">Drafts use this tab’s session storage and expire 8 hours after an edit. File contents and credentials are never stored.</p></Disclosure>
  </div>;
}
