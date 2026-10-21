import type { ComponentPropsWithRef, ReactNode } from 'react';
import { CircleAlert, Inbox, LoaderCircle } from 'lucide-react';

type FeedbackProps = Omit<ComponentPropsWithRef<'div'>, 'title'> & {
  state: 'loading' | 'empty' | 'error';
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
};

export function Feedback({ state, title, description, action, className, role, ...props }: FeedbackProps) {
  const Icon = state === 'loading' ? LoaderCircle : state === 'error' ? CircleAlert : Inbox;
  return <div {...props} className={`workspace-feedback ${className || ''}`.trim()} data-ui="feedback" data-state={state} role={role ?? (state === 'error' ? 'alert' : state === 'loading' ? 'status' : undefined)}>
    <Icon className={`feedback-icon${state === 'loading' ? ' feedback-spinner' : ''}`} size={20} aria-hidden="true" />
    <div className="feedback-content">
      <strong className="feedback-title">{title}</strong>
      {description && <p className="feedback-description">{description}</p>}
      {action && <div className="feedback-action">{action}</div>}
    </div>
  </div>;
}
