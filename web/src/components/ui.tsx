import { useId, useRef, Children, cloneElement, createElement, isValidElement, type ComponentPropsWithRef, type HTMLAttributes, type ReactElement, type ReactNode, type Ref } from 'react';

type Tone = 'neutral' | 'success' | 'caution' | 'error';
const classes = (...values: (string | undefined)[]) => [...new Set(values.filter(Boolean).flatMap(value => value!.split(/\s+/)))].join(' ');

export function Button({ variant, className, ...props }: ComponentPropsWithRef<'button'> & { variant?: 'primary' | 'secondary' | 'quiet' }) {
  // Keep the native type default: existing forms intentionally rely on submit.
  return <button data-ui="button" {...props} className={classes(className, variant === 'primary' ? 'primary' : variant === 'quiet' ? 'text-button' : undefined)} />;
}

export function Tab(props: ComponentPropsWithRef<'button'>) {
  return <Button type="button" {...props} role="tab" data-ui="tab" />;
}

type BoxProps = HTMLAttributes<HTMLElement> & { as?: 'section' | 'div' | 'article' | 'aside' | 'p'; ref?: Ref<HTMLElement> };
export function Card({ as: Element = 'section', tone = 'surface', className, ...props }: BoxProps & { tone?: 'surface' | 'subtle' | 'accent' }) {
  return createElement(Element, { ...props, 'data-ui': 'card', 'data-tone': tone, className: classes('panel', className) });
}

export function Notice({ as: Element = 'div', tone = 'caution', className, ...props }: BoxProps & { tone?: Tone }) {
  return createElement(Element, { ...props, 'data-ui': 'notice', className: classes('notice', tone, className) });
}

export function Badge({ tone = 'neutral', className, ...props }: ComponentPropsWithRef<'span'> & { tone?: Tone }) {
  return <span {...props} data-ui="badge" data-tone={tone} className={classes(className?.split(' ').includes('state') ? undefined : 'badge', className)} />;
}

export function Field(props: ComponentPropsWithRef<'input'>) {
  return <input data-ui="field" {...props} />;
}
export function MultilineField(props: ComponentPropsWithRef<'textarea'>) {
  return <textarea data-ui="field" {...props} />;
}

export function NavigationItem({ selected, icon, children, className, ...props }: ComponentPropsWithRef<'button'> & { selected: boolean; icon: ReactNode }) {
  return <Button {...props} data-ui="navigation-item" className={classes(className, selected ? 'selected' : undefined)} aria-current={selected ? 'page' : undefined}>
    {icon}<span>{children}</span>{selected && <span className="nav-indicator" aria-hidden="true" />}
  </Button>;
}

export function WorkspaceHeader(props: ComponentPropsWithRef<'header'>) {
  return <header {...props} className={classes('topbar', props.className)} />;
}

type MetricSummaryContent = { label: ReactNode; value: ReactNode; detail?: ReactNode; icon?: ReactNode };
type MetricSummaryProps = MetricSummaryContent & (
  | ({ as?: 'button' } & Omit<ComponentPropsWithRef<'button'>, 'value'>)
  | ({ as: 'article' } & ComponentPropsWithRef<'article'>)
);

export function MetricSummary({ label, value, detail, icon, ...props }: MetricSummaryProps) {
  const content = <><span className="summary-top"><span>{label}</span>{icon}</span><b>{value}</b>{detail != null && <small>{detail}</small>}</>;
  if (props.as === 'article') {
    const { as: _, ...native } = props;
    return <article {...native} data-ui="metric-summary" className={classes('summary-card', native.className)}>{content}</article>;
  }
  const { as: _, ...native } = props;
  return <Button type="button" {...native} data-ui="metric-summary" className={classes('summary-card', native.className)}>{content}</Button>;
}

type NativeProps = { children?: ReactNode; colSpan?: number; rowSpan?: number; role?: string; scope?: string; 'data-label'?: string };
const elements = (nodes: ReactNode) => Children.toArray(nodes).filter(isValidElement) as ReactElement<NativeProps>[];
const labelText = (nodes: ReactNode): string => Children.toArray(nodes).map(node => isValidElement<NativeProps>(node) ? labelText(node.props.children) : typeof node === 'string' || typeof node === 'number' ? String(node) : '').join('');

/** Retain one semantic table and the same interactive controls at every width. */
export function RecordTable({ children, className, ...props }: ComponentPropsWithRef<'table'>) {
  const sections = elements(children);
  const head = sections.find(section => section.type === 'thead');
  const headers = elements(elements(head?.props.children)[0]?.props.children);
  const bodies = sections.filter(section => section.type === 'tbody');
  const rows = bodies.flatMap(body => elements(body.props.children));
  // Complex/multi-level tables keep their local scroll container.
  const responsive = headers.length > 0 && elements(head?.props.children).length === 1 && rows.every(row => row.type === 'tr') &&
    [...headers, ...rows.flatMap(row => elements(row.props.children))].every(cell => !cell.props.colSpan && !cell.props.rowSpan && !cell.props['data-label']) &&
    rows.every(row => elements(row.props.children).every(cell => cell.type === 'td'));
  return <table {...props} role="table" className={classes('resource-table', responsive ? 'record-table' : undefined, className)}>
    {sections.map(section => {
      if (!responsive || section.type !== 'tbody') return section;
      return cloneElement(section, { role: 'rowgroup' }, elements(section.props.children).map(row => cloneElement(row, { role: 'row' },
        elements(row.props.children).map((cell, index) => cloneElement(cell, { role: 'cell' },
          <><span className="record-label" aria-hidden="true">{labelText(headers[index]?.props.children)}</span><div className="record-value">{cell.props.children}</div></>
        ))
      )));
    })}
  </table>;
}

export function FactList({ children, variant = 'ops' }: { children: ReactNode; variant?: 'ops' | 'runs' | 'data' | 'datasets' }) {
  const variantClass = variant === 'runs' ? 'runs-kv' : variant === 'data' ? 'data-facts' : variant === 'datasets' ? 'datasets-facts' : 'ops-facts';
  return <dl className={variantClass}>{children}</dl>;
}

export function WorkspaceTabs<T extends string>({ label, tabs, value, onChange, children }: {
  label: string; tabs: { value: T; label: string }[]; value: T; onChange: (value: T) => void; children: ReactNode;
}) {
  const id = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const active = Math.max(0, tabs.findIndex(tab => tab.value === value));
  return <>
    <div className="workspace-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab, index) => <Tab key={tab.value} id={`${id}-tab-${index}`} aria-controls={`${id}-panel`}
        ref={button => { buttons.current[index] = button; }} tabIndex={index === active ? 0 : -1}
        aria-selected={value === tab.value} onClick={() => onChange(tab.value)} onKeyDown={event => {
          const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length
            : event.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length
            : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
          if (next < 0) return;
          event.preventDefault(); buttons.current[next]?.focus(); onChange(tabs[next].value);
        }}>{tab.label}</Tab>)}
    </div>
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-tab-${active}`} tabIndex={0}>{children}</div>
  </>;
}
