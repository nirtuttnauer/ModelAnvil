import { useCallback, useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../../api/client';
import { allResources } from '../../api/resources';

export interface ModelImport {
  job_id?: string | null; import_id: string; name: string; status: string; job_status: string | null; candidate_id: string | null;
  files: Record<string, unknown>; acquired_files: Record<string, unknown>;
}

const LIVE = ['queued', 'running'];

/** Model imports for the project, polled while a download is still running. */
export function useModelImports(token: string, refreshKey = 0) {
  const [imports, setImports] = useState<ModelImport[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const reload = useCallback(async (signal?: AbortSignal) => {
    const rows = await allResources<ModelImport>('/api/v1/model-imports/', token, signal);
    if (!signal?.aborted) setImports(rows);
  }, [token]);
  useEffect(() => {
    if (!token.trim()) return;
    const controller = new AbortController(); setError('');
    void reload(controller.signal).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
  }, [token, reload, refreshKey]);
  useEffect(() => {
    if (!imports.some(item => LIVE.includes(item.job_status || ''))) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => { void reload(controller.signal).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); }); }, 3000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [imports, reload]);
  async function change(item: ModelImport, action: 'cancel' | 'resume') {
    setBusy(true); setError('');
    try { await apiRequest(`/api/v1/model-imports/${item.import_id}/${action}/`, token, { method: 'POST', body: '{}' }); await reload(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return { imports, error, busy, reload, change };
}
