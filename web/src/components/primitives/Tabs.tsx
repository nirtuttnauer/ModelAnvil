import type { ComponentPropsWithRef } from 'react';
import { Button } from './Button';

export function Tab(props: ComponentPropsWithRef<'button'>) {
  return <Button type="button" {...props} role="tab" data-ui="tab" />;
}

export function TabList({ label, ...props }: ComponentPropsWithRef<'div'> & { label: string }) {
  return <div role="tablist" aria-label={label} data-ui="tabs" {...props} />;
}
