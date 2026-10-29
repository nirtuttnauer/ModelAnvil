import type { ComponentPropsWithRef, ReactNode } from 'react';
import { Circle, CircleAlert, CircleCheck, CircleDot, CircleX } from 'lucide-react';
import { statusLabel, statusTone, type StatusTone } from '../../api/status';
import { Badge } from './Surfaces';
import { join } from './Button';

const ICONS = { neutral: Circle, info: CircleDot, running: CircleDot, success: CircleCheck, caution: CircleAlert, error: CircleX } as const;

/** Text plus icon for any lifecycle string; keeps the legacy `state` class for existing queries. */
export function StatusBadge({ status, label, tone, className, ...props }: Omit<ComponentPropsWithRef<'span'>, 'children'> & { status: string | null | undefined; label?: ReactNode; tone?: StatusTone }) {
  const resolved = tone ?? statusTone(status);
  const Icon = ICONS[resolved];
  return <Badge tone={resolved} data-status={status || undefined} className={join('state', className)} {...props}><Icon size={14} aria-hidden="true" />{label ?? statusLabel(status)}</Badge>;
}
