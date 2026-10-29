import { Identifier } from './Identifier';
import { useEffect, useState } from 'react';
import { apiRequest, errorMessage } from '../api/client';
export function BuildIdentity({ token, refreshKey }: { token: string; refreshKey: number }) {
  const [server, setServer] = useState<typeof __API_BUILD__ | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setServer(null); setError(null);
    if (token.trim()) apiRequest<typeof __API_BUILD__>('/api/v1/build/', token, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setServer(value); })
      .catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); });
    return () => controller.abort();
  }, [token, refreshKey]);
  const compatible = server?.protocol === __API_BUILD__.protocol;
  const matching = compatible && server?.source_digest === __API_BUILD__.source_digest;
  return <div className="build-info"><span>ModelAnvil <Identifier value={__API_BUILD__.revision} label="Client source revision" /><Identifier value={__API_BUILD__.source_digest} label="Client source digest" /></span>
    {server && <small role={matching ? undefined : 'alert'}>{matching ? 'API build matches' : compatible ? 'API build changed; rebuild or reload this client before acceptance testing' : 'API protocol incompatible; install matching browser and API builds'} · Imports: {server.dataset_formats.join(', ').toUpperCase()}</small>}
    {error && <small>API build check unavailable: {error}</small>}
  </div>;
}
