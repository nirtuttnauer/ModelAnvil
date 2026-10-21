import { useEffect, useState } from 'react';
import { Cpu, CircleHelp, TriangleAlert, CheckCircle2 } from 'lucide-react';
import { formatMemory, memoryBytes, modelHardwareFit, type HardwareTarget, type ModelMemory } from '../api/model-hardware';
import './model-hardware.css';

export function ModelHardwareFit({ memory, targets = [], compatible = true, reason }: {
  memory?: ModelMemory; targets?: HardwareTarget[]; compatible?: boolean; reason?: string;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(timer); }, []);
  const fit = compatible ? modelHardwareFit(memory?.training, targets, Math.max(now, Date.now())) : { status: 'unsupported' as const, reason: reason || 'This model has no supported training profile.' };
  const profile = memory?.training;
  const target = fit.target;
  const host = memoryBytes(target?.hostBytes);
  const required = memoryBytes(profile?.host_memory_bytes);
  const current = fit.status !== 'offline';
  const titles = { meets: 'Meets declared memory minimum', partial: 'Host memory fits · accelerator memory unknown', insufficient: 'Memory minimum not met', unknown: 'Hardware fit unknown', offline: 'Hardware report unavailable', unsupported: 'Training compatibility unavailable' };
  const Icon = fit.status === 'meets' ? CheckCircle2 : ['insufficient', 'unsupported'].includes(fit.status) ? TriangleAlert : CircleHelp;
  return <section className={`model-hardware model-hardware-${fit.status}`} aria-label="Model hardware fit">
    <header><div><Cpu size={18} aria-hidden="true" /><h4>Hardware & memory</h4></div><span className="model-hardware-status" role="status"><Icon size={16} aria-hidden="true" />{titles[fit.status]}</span></header>
    <dl>
      {memoryBytes(memory?.weights_bytes) !== null && <div><dt>Serialized weight files</dt><dd>{formatMemory(memory?.weights_bytes)}</dd></div>}
      {profile && <><div><dt>Minimum host memory</dt><dd>{formatMemory(profile.host_memory_bytes)}</dd></div>
        <div><dt>Required device</dt><dd>{profile.accelerator_backends.join(' / ').toUpperCase()}</dd></div>
        {profile.accelerator_memory_bytes > 0 && <div><dt>Minimum accelerator memory</dt><dd>{formatMemory(profile.accelerator_memory_bytes)}</dd></div>}</>}
      {target && <><div><dt>Compared hardware</dt><dd>{target.name}{target.busy ? ' · busy' : ''}</dd></div>
        <div><dt>Reported total host memory</dt><dd>{current ? formatMemory(target.hostBytes) : 'Unavailable · stale or offline'}</dd></div>
        {profile && profile.accelerator_memory_bytes > 0 && <div><dt>Reported accelerator capacity</dt><dd>{current ? formatMemory(target.acceleratorBytes) : 'Unavailable'}</dd></div>}</>}
    </dl>
    {current && host !== null && required !== null && <div className="model-memory-meter"><meter min={0} max={host} value={Math.min(required, host)} aria-label="Minimum host memory as a share of reported capacity" /><span>{formatMemory(required)} required / {formatMemory(host)} reported</span></div>}
    <p>{fit.reason}</p>
    {target?.busy && <p>The worker is busy. Memory fit does not mean an execution slot is free.</p>}
    <p className="model-hardware-basis">{memoryBytes(memory?.weights_bytes) !== null ? 'Weight file size is a storage measurement, not runtime RAM or VRAM. ' : ''}{profile?.basis || 'Quantization, context, activations and optimizer state can change runtime memory. No estimate is inferred from file size.'}</p>
  </section>;
}
