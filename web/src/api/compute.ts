export interface ComputeWorker {
  id: number; status: string; connection_state?: string;
  capabilities: { setup_profile?: string; training_runtime?: string; memory_bytes?: number };
}

export function computeReadiness(worker: ComputeWorker): string {
  if (worker.connection_state === 'credential_unavailable') return 'Credential expired or revoked';
  if (worker.connection_state === 'not_connected' || !worker.connection_state) return 'Waiting for a worker heartbeat';
  if (worker.connection_state === 'stale') return 'Heartbeat stale — reconnect the worker';
  if (worker.connection_state === 'offline' || worker.status === 'offline') return 'Worker offline';
  if (worker.status === 'draining') return 'Worker draining';
  if (worker.status === 'busy') return 'Worker connected — capacity busy';
  return 'Worker connected';
}
