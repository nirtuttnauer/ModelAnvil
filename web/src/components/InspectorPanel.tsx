import { Button, Card } from './ui';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import './workbench-components.css';

export function InspectorPanel({ title, eyebrow, closeLabel = 'Close details', onClose, children, footer, focusOnOpen = true }: {
  title: string; eyebrow?: string; closeLabel?: string; onClose(): void; children: ReactNode; footer?: ReactNode;
  focusOnOpen?: boolean;
}) {
  const panel = useRef<HTMLElement>(null), id = useId();
  useEffect(() => {
    if (!focusOnOpen) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const element = panel.current; element?.focus();
    return () => {
      if (trigger?.isConnected && (element?.contains(document.activeElement) || document.activeElement === document.body)) trigger.focus();
    };
  }, [focusOnOpen]);
  return <Card as="aside" ref={panel} tabIndex={-1} className="panel ops-inspector inspector-panel" aria-labelledby={id} onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); onClose(); } }}>
    <div className="panel-title"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2 id={id}>{title}</h2></div><Button type="button" className="icon-button" aria-label={closeLabel} onClick={onClose}><X size={17} aria-hidden="true" /></Button></div>
    <div className="panel-body">{children}</div>{footer && <div className="inspector-footer">{footer}</div>}
  </Card>;
}
