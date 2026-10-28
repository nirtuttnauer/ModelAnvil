import { useEffect, useId, useRef, type ComponentPropsWithRef, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { Button } from './Button';

/** Native modal dialog rendered in place (no portal) so tests scoped to the app tree can see it. */
export function Dialog({ title, description, open, onClose, footer, size, closeLabel = 'Close', children, ...props }: Omit<ComponentPropsWithRef<'dialog'>, 'title' | 'open'> & {
  title: ReactNode; description?: ReactNode; open: boolean; onClose(): void; footer?: ReactNode; size?: 'md' | 'lg'; closeLabel?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null); const id = useId();
  useEffect(() => {
    const element = ref.current; if (!element) return;
    if (open && !element.open) element.showModal();
    else if (!open && element.open) element.close();
  }, [open]);
  return <dialog ref={ref} data-ui="dialog" data-size={size} aria-labelledby={`${id}-title`} aria-describedby={description ? `${id}-description` : undefined}
    onCancel={event => { event.preventDefault(); onClose(); }} onClose={() => { if (open) onClose(); }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }} {...props}>
    <header><div><h2 id={`${id}-title`}>{title}</h2>{description && <p id={`${id}-description`}>{description}</p>}</div>
      <Button type="button" variant="quiet" icon aria-label={closeLabel} onClick={onClose}><X size={18} aria-hidden="true" /></Button></header>
    <div data-ui="dialog-body">{children}</div>
    {footer && <footer>{footer}</footer>}
  </dialog>;
}

/** A disclosure-based popover menu with outside-click and Escape handling. */
export function Menu({ label, icon, children, ...props }: ComponentPropsWithRef<'details'> & { label: string; icon: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const element = ref.current; if (!element) return;
    const onPointer = (event: Event) => { if (element.open && !element.contains(event.target as Node)) element.open = false; };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && element.open) { event.preventDefault(); element.open = false; element.querySelector('summary')?.focus(); }
    };
    document.addEventListener('click', onPointer); document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('click', onPointer); document.removeEventListener('keydown', onKey); };
  }, []);
  return <details ref={ref} data-ui="menu" {...props}>
    <summary data-ui="button" data-variant="quiet" data-icon aria-label={label} title={label}>{icon}</summary>
    <div data-ui="menu-panel">{children}</div>
  </details>;
}

export function MenuSection({ label, children, ...props }: ComponentPropsWithRef<'div'> & { label?: ReactNode }) {
  return <div data-ui="menu-section" {...props}>{label && <span>{label}</span>}{children}</div>;
}
