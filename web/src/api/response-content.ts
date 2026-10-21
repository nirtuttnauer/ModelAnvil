export function structuredResponse(text: string | null | undefined, stripFence = true): object | null {
  if (!text) return null;
  const candidate = stripFence ? text.trim().replace(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i, '$1') : text.trim();
  if (!candidate.startsWith('{') && !candidate.startsWith('[')) return null;
  try {
    const value: unknown = JSON.parse(candidate);
    return value !== null && typeof value === 'object' ? value : null;
  } catch { return null; }
}
