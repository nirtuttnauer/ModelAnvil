export function ResourceState({ loading, error, onRetry }: { loading?: boolean; error?: string | null; onRetry?: () => void }) {
  if (error) return <div className="notice error" role="alert">{error}{onRetry && <button onClick={onRetry}>Try again</button>}</div>;
  if (loading) return <p className="muted" role="status">Loading workspace data…</p>;
  return null;
}
