import { useId, useState, type ChangeEvent, type ComponentPropsWithRef, type ReactNode } from 'react';
import { ChevronDown, Upload } from 'lucide-react';

export function Field(props: ComponentPropsWithRef<'input'>) { return <input data-ui="field" {...props} />; }
export function MultilineField(props: ComponentPropsWithRef<'textarea'>) { return <textarea data-ui="field" {...props} />; }

type ControlText = { label?: ReactNode; hint?: ReactNode; error?: ReactNode };

/** A labelled text field: label, input, optional hint and error in one accessible block. */
export function TextControl({ label, hint, error, id, className, ...props }: ComponentPropsWithRef<'input'> & ControlText) {
  const generated = useId(); const inputId = id ?? generated;
  const describedBy = [hint && `${inputId}-hint`, error && `${inputId}-error`].filter(Boolean).join(' ') || undefined;
  return <div data-ui="control" className={className}>
    {label && <label data-ui="control-label" htmlFor={inputId}>{label}</label>}
    <input data-ui="field" id={inputId} aria-describedby={describedBy} aria-invalid={error ? true : props['aria-invalid']} {...props} />
    {hint && <small data-ui="control-hint" id={`${inputId}-hint`}>{hint}</small>}
    {error && <small data-ui="control-error" id={`${inputId}-error`} role="alert">{error}</small>}
  </div>;
}

export type SelectOption = { value: string; label: ReactNode; disabled?: boolean };
export function Select({ label, hint, error, options, children, id, className, ...props }: Omit<ComponentPropsWithRef<'select'>, 'children'> & ControlText & { options?: SelectOption[]; children?: ReactNode }) {
  const generated = useId(); const selectId = id ?? generated;
  const describedBy = [hint && `${selectId}-hint`, error && `${selectId}-error`].filter(Boolean).join(' ') || undefined;
  const control = <span data-ui="select-wrap"><select data-ui="select" id={selectId} aria-describedby={describedBy} aria-invalid={error ? true : props['aria-invalid']} {...props}>
    {options?.map(option => <option key={option.value} value={option.value} disabled={option.disabled}>{option.label}</option>)}{children}
  </select></span>;
  if (!label && !hint && !error) return control;
  return <div data-ui="control" className={className}>
    {label && <label data-ui="control-label" htmlFor={selectId}>{label}</label>}
    {control}
    {hint && <small data-ui="control-hint" id={`${selectId}-hint`}>{hint}</small>}
    {error && <small data-ui="control-error" id={`${selectId}-error`} role="alert">{error}</small>}
  </div>;
}

export function Checkbox({ label, hint, className, ...props }: ComponentPropsWithRef<'input'> & { label: ReactNode; hint?: ReactNode }) {
  return <label data-ui="checkbox" className={className}><input type="checkbox" {...props} /><span>{label}{hint && <small>{hint}</small>}</span></label>;
}

export function Radio({ label, hint, className, ...props }: ComponentPropsWithRef<'input'> & { label: ReactNode; hint?: ReactNode }) {
  return <label data-ui="radio" className={className}><input type="radio" {...props} /><span>{label}{hint && <small>{hint}</small>}</span></label>;
}

/** A styled file picker. The native input stays in the tree (hidden) so uploads and tests keep working. */
export function FileInput({ label, hint, buttonLabel = 'Choose file', emptyLabel = 'No file selected', onChange, className, id, ...props }: Omit<ComponentPropsWithRef<'input'>, 'type'> & { label: ReactNode; hint?: ReactNode; buttonLabel?: string; emptyLabel?: string }) {
  const generated = useId(); const inputId = id ?? generated;
  const [names, setNames] = useState('');
  function change(event: ChangeEvent<HTMLInputElement>) {
    setNames(Array.from(event.target.files ?? []).map(file => file.name).join(', '));
    onChange?.(event);
  }
  return <div data-ui="file-input" className={className}>
    <label data-ui="control-label" htmlFor={inputId}>{label}</label>
    <span data-ui="file-input-control">
      <input type="file" data-ui="file-input-native" id={inputId} aria-describedby={hint ? `${inputId}-hint` : undefined} onChange={change} {...props} />
      <span data-ui="button" data-variant="secondary" data-size="sm" aria-hidden="true"><Upload size={15} aria-hidden="true" />{buttonLabel}</span>
      <span data-ui="file-input-name">{names || emptyLabel}</span>
    </span>
    {hint && <small data-ui="control-hint" id={`${inputId}-hint`}>{hint}</small>}
  </div>;
}

export function SegmentedControl<T extends string>({ label, value, onChange, options, className, ...props }: Omit<ComponentPropsWithRef<'div'>, 'onChange'> & {
  label: string; value: T; onChange(value: T): void; options: { value: T; label: ReactNode; disabled?: boolean }[];
}) {
  return <div role="group" aria-label={label} data-ui="segmented" className={className} {...props}>
    {options.map(option => <button key={option.value} type="button" aria-pressed={option.value === value} disabled={option.disabled} onClick={() => onChange(option.value)}>{option.label}</button>)}
  </div>;
}

export function Disclosure({ summary, variant = 'plain', children, className, ...props }: ComponentPropsWithRef<'details'> & { summary: ReactNode; variant?: 'plain' | 'card' | 'quiet' }) {
  return <details data-ui="disclosure" data-variant={variant} className={className} {...props}>
    <summary>{summary}<ChevronDown size={16} aria-hidden="true" /></summary>
    <div data-ui="disclosure-body">{children}</div>
  </details>;
}
