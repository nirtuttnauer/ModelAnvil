import type { ComputeWorker } from './compute.ts';

export interface TrainingMemory {
  host_memory_bytes: number; accelerator_memory_bytes: number; accelerator_backends: string[];
  runtime_contract: string; basis: string;
}
export interface ModelMemory { weights_bytes: number | null; training: TrainingMemory | null }
export interface HardwareWorker extends ComputeWorker {
  name: string; pool: number; pool_name: string; last_heartbeat_at?: string | null;
  capabilities: ComputeWorker['capabilities'] & { model_import?: boolean; gpu_backend?: string; gpu_memory_bytes?: number; accelerator?: string };
}
export interface HardwareTarget {
  id: string; name: string; hostBytes: number | null; acceleratorBytes: number | null;
  backend: string; runtimeContract: string; connected: boolean; busy: boolean;
  observedAt: number; maxAgeSeconds: number;
}
export function memoryBytes(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null;
}
export function formatMemory(value: unknown): string {
  const bytes = memoryBytes(value);
  if (bytes === null) return 'Unknown';
  const gib = bytes / 1024**3;
  return gib >= 1 ? `${Number(gib.toFixed(2))} GiB` : `${Number((bytes / 1024**2).toFixed(1))} MiB`;
}
export function workerHardware(worker: HardwareWorker, reportedAt: number): HardwareTarget {
  return { id: String(worker.id), name: `${worker.name} · ${worker.pool_name}`,
    hostBytes: memoryBytes(worker.capabilities.memory_bytes), acceleratorBytes: memoryBytes(worker.capabilities.gpu_memory_bytes),
    backend: worker.capabilities.gpu_backend || worker.capabilities.accelerator || '',
    runtimeContract: worker.capabilities.training_runtime || '',
    connected: worker.connection_state === 'connected' && ['available', 'busy'].includes(worker.status),
    busy: worker.status === 'busy', observedAt: worker.last_heartbeat_at ? Date.parse(worker.last_heartbeat_at) : reportedAt, maxAgeSeconds: 60 };
}
export type HardwareFitStatus = 'meets' | 'partial' | 'insufficient' | 'unknown' | 'offline' | 'unsupported';
export interface HardwareFit { status: HardwareFitStatus; reason: string; target?: HardwareTarget }

export function modelHardwareFit(requirements: TrainingMemory | null | undefined, targets: HardwareTarget[], now: number): HardwareFit {
  if (!requirements || memoryBytes(requirements.host_memory_bytes) === null || !Number.isSafeInteger(requirements.accelerator_memory_bytes) || requirements.accelerator_memory_bytes < 0) {
    return { status: 'unknown', reason: 'Training memory requirements have not been reported for this model.' };
  }
  const matching = targets.filter(target => !!requirements.runtime_contract && target.runtimeContract === requirements.runtime_contract);
  if (!matching.length) return { status: 'unknown', reason: 'No hardware reporting the matching training runtime is connected in this selection.' };
  const fits = matching.map((target): HardwareFit => {
    const age = (now - target.observedAt) / 1000;
    if (!target.connected || !Number.isFinite(age) || age < 0 || age > target.maxAgeSeconds) return { status: 'offline', target, reason: 'Hardware is offline or its report is stale. Refresh or reconnect before relying on capacity.' };
    if (!target.backend) return { status: 'unknown', target, reason: 'The device backend has not been reported. Preflight must check compatibility.' };
    if (!requirements.accelerator_backends.includes(target.backend)) return { status: 'unsupported', target, reason: 'This model’s training profile needs a different device backend.' };
    const host = memoryBytes(target.hostBytes), accelerator = memoryBytes(target.acceleratorBytes);
    if (host !== null && host < requirements.host_memory_bytes || accelerator !== null && accelerator < requirements.accelerator_memory_bytes) {
      return { status: 'insufficient', target, reason: 'Reported memory is below the training profile minimum. Choose a smaller model or a larger compatible worker.' };
    }
    if (host === null) return { status: 'unknown', target, reason: 'Host memory has not been reported. Preflight must check capacity.' };
    if (requirements.accelerator_memory_bytes > 0 && accelerator === null) return { status: 'partial', target, reason: 'Host memory meets the minimum. Accelerator memory and live headroom have not been reported.' };
    return { status: 'meets', target, reason: 'Reported capacity meets the profile minimum. Free memory, allocation and exact inputs are checked at preflight.' };
  });
  const order: Record<HardwareFitStatus, number> = { meets: 0, partial: 1, unknown: 2, insufficient: 3, unsupported: 4, offline: 5 };
  return fits.sort((a, b) => order[a.status] - order[b.status] || Number(a.target?.busy) - Number(b.target?.busy))[0];
}
