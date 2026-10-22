import type { ReactNode } from 'react';
import { Identifier } from './Identifier';
import { Badge, Button } from './ui';

export function RunDetailHeader({ title, id, idLabel = 'Run ID', status, onClose, children }: {
  title: ReactNode;
  id?: string;
  idLabel?: string;
  status?: string;
  onClose?: () => void;
  children?: ReactNode;
}) {
  return <div className="actions" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
    <div>
      <h3>{title}{id && <> <Identifier value={id} label={idLabel} /></>}</h3>
      {status && <Badge className={`state state-${status}`}>{status}</Badge>}
    </div>
    <div style={{ display: 'flex', gap: 'var(--space-8)', flexWrap: 'wrap' }}>
      {children}
      {onClose && <Button type="button" onClick={onClose}>Close details</Button>}
    </div>
  </div>;
}
