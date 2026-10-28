import type { ComponentPropsWithRef } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'quiet';
export type ButtonProps = ComponentPropsWithRef<'button'> & { variant?: ButtonVariant; size?: 'sm' | 'lg'; icon?: boolean };

export const join = (...values: (string | undefined | false | null)[]) => {
  const unique = [...new Set(values.filter(Boolean).flatMap(value => (value as string).split(/\s+/)))];
  return unique.length ? unique.join(' ') : undefined;
};

/** Resolve the variant from the prop or, for unmigrated callers, from legacy class names. */
function resolveVariant(variant: ButtonVariant | undefined, className?: string): ButtonVariant {
  if (variant) return variant;
  const legacy = className?.split(/\s+/) ?? [];
  if (legacy.includes('primary')) return 'primary';
  if (legacy.includes('text-button')) return 'quiet';
  return 'secondary';
}

export function Button({ variant, size, icon, className, ...props }: ButtonProps) {
  const resolved = resolveVariant(variant, className);
  const iconOnly = icon ?? className?.split(/\s+/).includes('icon-button');
  // Keep the native type default: existing forms intentionally rely on submit.
  return <button data-ui="button" data-variant={resolved} data-size={size} data-icon={iconOnly || undefined} {...props}
    className={join(className, resolved === 'primary' && 'primary', resolved === 'quiet' && 'text-button')} />;
}

export function LinkButton({ variant = 'secondary', size, icon, className, ...props }: ComponentPropsWithRef<'a'> & { variant?: ButtonVariant; size?: 'sm' | 'lg'; icon?: boolean }) {
  return <a data-ui="link-button" data-variant={variant} data-size={size} data-icon={icon || undefined} {...props} className={className} />;
}
