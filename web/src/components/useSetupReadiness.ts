import { useCallback, useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
import { allResources } from '../api/resources';
import type { Project, TokenizerVersion } from '../api/resources';
import type { GuidedOptions } from '../api/guided-training';
import { setupReadiness, type SetupBudget, type SetupDataset, type SetupModel, type SetupPool, type SetupReadinessState, type SetupRunner, type SetupWorker } from '../api/setup-readiness';

/** The one client-side readiness computation, shared by Overview and Training. */
export function useSetupReadiness(token: string, refreshKey: number, activeProject: Project | null) {
  const [state, setState] = useState<SetupReadinessState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const version = useRef(0);
  const projectId = activeProject?.id ?? null;
  useEffect(() => {
    const controller = new AbortController();
    const current = ++version.current;
    setState(null); setError(null);
    if (!token.trim()) { setLoading(false); return; }
    setLoading(true);
    const signal = controller.signal;
    Promise.allSettled([
      allResources<SetupDataset>('/api/v1/dataset-revisions/', token, signal),
      allResources<TokenizerVersion>('/api/v1/tokenizers/', token, signal),
      allResources<SetupModel>('/api/v1/model-versions/', token, signal),
      allResources<SetupPool>('/api/v1/worker-pools/', token, signal),
      allResources<SetupBudget>('/api/v1/budget-policies/', token, signal),
      allResources<SetupWorker>('/api/v1/worker-inventory/', token, signal),
      allResources<SetupRunner>('/api/v1/runner-manifests/', token, signal),
      apiRequest<GuidedOptions>('/api/v1/fine-tuning/options/', token, { signal }),
    ]).then(results => {
      if (signal.aborted || current !== version.current) return;
      const value = <T,>(index: number, fallback: T): T => { const r = results[index]; return r.status === 'fulfilled' ? (r.value as T) : fallback; };
      const lists = results.slice(0, 7);
      const failures = lists.filter(r => r.status === 'rejected') as PromiseRejectedResult[];
      if (failures.length) setError('Some prerequisites could not be verified. ' + errorMessage(failures[0].reason));
      const options = value<GuidedOptions | null>(7, null);
      setState({
        hasConnection: lists.some(r => r.status === 'fulfilled'),
        compute: options ? { available: options.compute.available, message: options.compute.message } : null,
        ...setupReadiness({ datasets: value(0, []), tokenizers: value(1, []), models: value(2, []), pools: value(3, []), budgets: value(4, []), workers: value(5, []), runners: value(6, []) }),
      });
      setLoading(false);
    });
    return () => controller.abort();
  }, [token, refreshKey, projectId, retry]);
  const reload = useCallback(() => setRetry(value => value + 1), []);
  return { state, loading, error, reload };
}
