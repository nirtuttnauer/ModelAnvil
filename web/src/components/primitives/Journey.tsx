import type { ComponentPropsWithRef } from 'react';

/** Numbered journey steps; the current step is highlighted and earlier steps marked done. */
export function JourneySteps({ steps, current, compact, label = 'Steps', ...props }: ComponentPropsWithRef<'ol'> & { steps: readonly string[]; current: number; compact?: boolean; label?: string }) {
  return <ol data-ui="journey" data-compact={compact || undefined} aria-label={label} {...props}>
    {steps.map((step, index) => <li key={step} aria-current={index === current ? 'step' : undefined} data-done={index < current || undefined}>{step}</li>)}
  </ol>;
}
