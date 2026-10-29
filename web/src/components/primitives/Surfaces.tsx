import { createElement, useId, type ComponentPropsWithRef, type HTMLAttributes, type ReactNode, type Ref } from 'react';

export type Tone = 'neutral' | 'info' | 'success' | 'caution' | 'error' | 'running';
type BoxProps = HTMLAttributes<HTMLElement> & { as?: 'section' | 'div' | 'article' | 'aside' | 'p'; ref?: Ref<HTMLElement> };

export function Card({ as: Element = 'section', tone = 'surface', padded, className, ...props }: BoxProps & { tone?: 'surface' | 'subtle' | 'accent'; padded?: boolean }) {
  return createElement(Element, { 'data-ui': 'card', 'data-tone': tone, 'data-padded': padded || undefined, ...props, className });
}

export function Notice({ as: Element = 'div', tone = 'neutral', className, ...props }: BoxProps & { tone?: Tone }) {
  return createElement(Element, { ...props, 'data-ui': 'notice', 'data-tone': tone, className });
}

export function Badge({ tone = 'neutral', className, ...props }: ComponentPropsWithRef<'span'> & { tone?: Tone }) {
  return <span {...props} data-ui="badge" data-tone={tone} className={className} />;
}

export function PageHeader({ title, description, actions, children, ...props }: Omit<ComponentPropsWithRef<'div'>, 'title'> & { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return <div data-ui="page-header" {...props}><div><h1>{title}</h1>{description && <p>{description}</p>}{children}</div>{actions}</div>;
}

export function Section({ title, description, actions, level = 2, variant = 'plain', id, children, ...props }: Omit<ComponentPropsWithRef<'section'>, 'title'> & {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; level?: 2 | 3; variant?: 'plain' | 'card';
}) {
  const generated = useId();
  const headingId = id ? `${id}-title` : generated;
  return <section data-ui="section" data-variant={variant} id={id} aria-labelledby={headingId} {...props}>
    <header data-ui="section-header"><div>{createElement(`h${level}`, { id: headingId }, title)}{description && <p>{description}</p>}</div>{actions && <div data-ui="actions">{actions}</div>}</header>
    {children}
  </section>;
}

export function Divider(props: ComponentPropsWithRef<'hr'>) { return <hr data-ui="divider" {...props} />; }

export function StatRow(props: ComponentPropsWithRef<'div'>) { return <div data-ui="stat-row" role="list" {...props} />; }

export function Stat({ label, value, hint, tone, ...props }: ComponentPropsWithRef<'div'> & { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: 'neutral' | 'success' | 'caution' | 'error' }) {
  return <div data-ui="stat" data-tone={tone} role="listitem" {...props}><span data-ui="stat-label">{label}</span><strong data-ui="stat-value">{value}</strong>{hint != null && <small>{hint}</small>}</div>;
}

export function KeyValueList({ items, columns = 1, ...props }: ComponentPropsWithRef<'dl'> & { items: { label: ReactNode; value: ReactNode; key?: string }[]; columns?: 1 | 2 }) {
  return <dl data-ui="kv" data-columns={columns} {...props}>{items.map((item, index) => <div key={item.key ?? index}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl>;
}

export function Toolbar({ label, actions, children, ...props }: ComponentPropsWithRef<'div'> & { label?: string; actions?: ReactNode }) {
  return <div data-ui="toolbar" role={label ? 'group' : undefined} aria-label={label} {...props}><div data-ui="toolbar-filters">{children}</div>{actions && <div data-ui="toolbar-actions">{actions}</div>}</div>;
}
