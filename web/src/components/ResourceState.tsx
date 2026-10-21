import { Button } from './ui';
import { Feedback } from './Feedback';
export function ResourceState({ loading, error, onRetry }: { loading?: boolean; error?: string | null; onRetry?: () => void }) {
  if (error) return <Feedback state="error" title={error} action={onRetry && <Button type="button" onClick={onRetry}>Try again</Button>} />;
  if (loading) return <Feedback state="loading" title="Loading workspace data…" />;
  return null;
}
