import { Children, cloneElement, isValidElement, type ComponentPropsWithRef, type ReactElement, type ReactNode } from 'react';
import { Button, join } from './primitives/Button';

export * from './primitives';

export function NavigationItem({ selected, icon, children, className, ...props }: ComponentPropsWithRef<'button'> & { selected: boolean; icon: ReactNode }) {
  return <Button {...props} data-ui="navigation-item" className={className} aria-current={selected ? 'page' : undefined}>
    {icon}<span>{children}</span>
  </Button>;
}

export function WorkspaceHeader(props: ComponentPropsWithRef<'header'>) {
  return <header data-ui="topbar" {...props} />;
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
    return <article {...native} data-ui="metric-summary" className={native.className}>{content}</article>;
  }
  const { as: _, ...native } = props;
  return <Button type="button" {...native} data-ui="metric-summary" className={native.className}>{content}</Button>;
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
  return <table {...props} data-ui="table" role="table" className={join(responsive ? 'record-table' : undefined, className)}>
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
