import { useEffect, useRef, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';

export function useResourceHandoff(token: string, receive: (kind: 'model-version' | 'dataset-revision', value: { id: number; tokenizer?: number; model_version_id?: string; revision_id?: string; chat_template?: string; capabilities?: { train?: { eligible: boolean }; chat?: { eligible: boolean }; evaluate?: { eligible: boolean } } }) => void) {
  const callback = useRef(receive); callback.current = receive;
  const [error, setError] = useState('');
  useEffect(() => {
    let controller: AbortController | null = null;
    function load() {
      controller?.abort(); controller = new AbortController(); const request = controller;
      setError(''); const query = new URLSearchParams(window.location.hash.split('?')[1]);
      for (const [parameter, kind, path] of [['model_version', 'model-version', 'model-versions'], ['dataset_revision', 'dataset-revision', 'dataset-revisions']] as const) {
        const id = query.get(parameter); if (!id) continue;
        void apiRequest<Parameters<typeof receive>[1]>(`/api/v1/${path}/${encodeURIComponent(id)}/`, token, { signal: request.signal })
          .then(value => { if (!request.signal.aborted) callback.current(kind, value); })
          .catch(e => { if (!request.signal.aborted) setError(`Selected resource is unavailable: ${errorMessage(e)}`); });
      }
    }
    load(); window.addEventListener('hashchange', load);
    return () => { controller?.abort(); window.removeEventListener('hashchange', load); };
  }, [token]);
  return error;
}
