import type { ComponentPropsWithRef, ReactNode } from 'react';
import { CircleAlert, Inbox, LoaderCircle } from 'lucide-react';

type FeedbackProps = Omit<ComponentPropsWithRef<'div'>, 'title'> & {
  state: 'loading' | 'empty' | 'error';
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  /** `centered` for an empty region that owns its space; `inline` (default) for a row inside content. */
  layout?: 'inline' | 'centered';
};

export function Feedback({ state, title, description, action, layout, className, role, ...props }: FeedbackProps) {
  const Icon = state === 'loading' ? LoaderCircle : state === 'error' ? CircleAlert : Inbox;
  return <div {...props} className={className} data-ui="feedback" data-state={state} data-layout={layout} role={role ?? (state === 'error' ? 'alert' : state === 'loading' ? 'status' : undefined)}>
    <Icon className={`feedback-icon${state === 'loading' ? ' feedback-spinner' : ''}`} size={20} aria-hidden="true" />
    <div className="feedback-content">
      <strong className="feedback-title">{title}</strong>
      {description && <p className="feedback-description">{description}</p>}
      {action && <div className="feedback-action">{action}</div>}
    </div>
  </div>;
}

/** Empty region with an optional next action. */
export function EmptyState({ title, description, action, layout = 'inline', ...props }: Omit<FeedbackProps, 'state'>) {
  return <Feedback state="empty" title={title} description={description} action={action} layout={layout} {...props} />;
}
