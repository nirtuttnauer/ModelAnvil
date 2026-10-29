import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CircleAlert, CircleCheck, Info } from 'lucide-react';
import './identifier.css';

export function isOpaqueIdentifier(value: string): boolean {
  return /^(?:sha256:)?[a-f\d]{32,}$|^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(value);
}

/** Keep technical identity available without making it the visible name. */
export function Identifier({ value, label = 'ID', display = 'icon' }: { value: string | number | null | undefined; label?: string; display?: 'icon' | 'code' }) {
  const text = value == null ? '' : String(value);
  const tooltipId = useId();
  const trigger = useRef<HTMLButtonElement>(null), tooltip = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<{ value: string; state: 'copied' | 'failed' } | null>(null);
  const [position, setPosition] = useState({ left: 0, top: 0, side: 'above' });
  const state = result?.value === text ? result.state : null;
  const currentValue = useRef(text); currentValue.current = text;
  function show() { if (closeTimer.current) clearTimeout(closeTimer.current); setOpen(true); }
  function hide() { closeTimer.current = setTimeout(() => { if (document.activeElement !== trigger.current) setOpen(false); }, 120); }
  useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current); }, []);
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      if (!trigger.current || !tooltip.current) return;
      const anchor = trigger.current.getBoundingClientRect(), box = tooltip.current.getBoundingClientRect();
      const above = anchor.top >= box.height + 12;
      setPosition({ left: Math.max(8, Math.min(window.innerWidth - box.width - 8, anchor.left + anchor.width / 2 - box.width / 2)),
        top: above ? anchor.top - box.height - 6 : Math.min(window.innerHeight - box.height - 8, anchor.bottom + 6), side: above ? 'above' : 'below' });
    }
    const dismiss = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (closeTimer.current) clearTimeout(closeTimer.current); setOpen(false); } };
    if (tooltip.current?.showPopover && !tooltip.current.matches(':popover-open')) tooltip.current.showPopover();
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true); document.addEventListener('keydown', dismiss);
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); document.removeEventListener('keydown', dismiss); };
  }, [open, text, state]);
  async function copy() {
    const copied = text; setResult(null); show();
    try { await navigator.clipboard.writeText(copied); if (currentValue.current === copied) setResult({ value: copied, state: 'copied' }); }
    catch { if (currentValue.current === copied) setResult({ value: copied, state: 'failed' }); }
  }
  if (!text) return null;
  const Icon = state === 'copied' ? CircleCheck : state === 'failed' ? CircleAlert : Info;
  return <span className="identifier" data-display={display}>
    {display === 'code' && <code className="identifier-code">{text}</code>}
    <button ref={trigger} type="button" className="identifier-trigger" aria-label={`Copy ${label}`} aria-describedby={open ? tooltipId : undefined}
      onPointerEnter={show} onPointerLeave={hide} onFocus={show} onBlur={hide}
      onClick={event => { event.preventDefault(); event.stopPropagation(); void copy(); }}><Icon size={16} aria-hidden="true" /></button>
    <span className="identifier-status" role="status">{state === 'copied' ? `${label} copied.` : state === 'failed' ? `Could not copy ${label}. Select the value in the tooltip to copy it manually.` : ''}</span>
    {open && createPortal(<div ref={tooltip} id={tooltipId} popover="manual" role="tooltip" className="identifier-tooltip" data-side={position.side}
      style={{ left: position.left, top: position.top }} onPointerEnter={show} onPointerLeave={hide}>
      <span>{label}{state === 'copied' ? ' · Copied' : ''}</span><code>{text}</code>
      <small>{state === 'failed' ? 'Copy unavailable. Select this value to copy manually.' : 'Click the circle to copy'}</small>
    </div>, trigger.current?.closest('dialog[open]') || document.body)}
  </span>;
}
