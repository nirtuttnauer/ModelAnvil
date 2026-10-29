import { Button } from './ui';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

/** A side panel for one selected record: title, close button, body and an optional footer. Escape closes it and focus returns to the trigger. */
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
  return <aside ref={panel} tabIndex={-1} data-ui="inspector" aria-labelledby={id} onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); onClose(); } }}>
    <header><div>{eyebrow && <p data-ui="kicker">{eyebrow}</p>}<h2 id={id}>{title}</h2></div><Button type="button" variant="quiet" icon aria-label={closeLabel} onClick={onClose}><X size={18} aria-hidden="true" /></Button></header>
    <div data-ui="inspector-body">{children}</div>
    {footer && <footer>{footer}</footer>}
  </aside>;
}
