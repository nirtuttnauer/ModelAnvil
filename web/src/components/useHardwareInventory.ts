import { useEffect, useState } from 'react';
import { allResources } from '../api/resources';
import { errorMessage } from '../api/client';
import type { HardwareWorker } from '../api/model-hardware';

export function useHardwareInventory(token: string, refreshKey = 0) {
  const [workers, setWorkers] = useState<HardwareWorker[]>([]);
  const [reportedAt, setReportedAt] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); let pending = false;
    setWorkers([]); setError('');
    async function load() {
      if (!token.trim() || pending) return;
      pending = true;
      try {
        const rows = await allResources<HardwareWorker>('/api/v1/worker-inventory/', token, controller.signal);
        if (!controller.signal.aborted) { setWorkers(rows); setReportedAt(Date.now()); setError(''); }
      } catch (e) { if (!controller.signal.aborted) { setWorkers([]); setError(errorMessage(e)); } }
      finally { pending = false; }
    }
    void load();
    const timer = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 10000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [token, refreshKey]);
  return { workers, reportedAt, error };
}
