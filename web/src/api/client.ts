export class ApiRequestError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

let activeProjectId: string | null = null;

export function setActiveProjectId(id: string | null): void {
  activeProjectId = id ? id.trim() : null;
}

export function getActiveProjectId(): string | null {
  return activeProjectId;
}

export function apiPath(path: string): string {
  const base = new URL(typeof window === 'undefined' ? 'http://localhost' : window.location.origin);
  const url = new URL(path, base);
  if (path.startsWith('//') || url.origin !== base.origin || !url.pathname.startsWith('/api/v1/') || url.username || url.password || url.hash) {
    throw new Error('Invalid API path.');
  }
  return url.pathname + url.search;
}

export async function apiRequest<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const safePath = apiPath(path);
  if (!token.trim()) throw new Error('Enter an API key to connect to this workspace.');
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token.trim()}`);
  if (activeProjectId) {
    headers.set('X-Project-ID', activeProjectId);
  }
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(safePath, { ...init, headers, redirect: 'error' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new Error('Could not reach the API. Check the Docker stack and try Refresh.');
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status}).`;
    if (response.status === 401) message = 'Authentication failed. Check your API key and reconnect.';
    else if (response.status === 403) message = 'Your API key does not have permission for this action.';
    else if (response.status < 500) {
      message = body?.error?.message || body?.detail || (typeof body?.error === 'string' ? body.error : message);
      const details = body?.error?.details;
      if (Array.isArray(details)) message += ' ' + details.map((d: { path?: string; message?: string }) => `${d.path || 'Request'}: ${d.message || 'Invalid value'}`).join(' ');
    }
    throw new ApiRequestError(message, response.status);
  }
  if (body === null) throw new Error('The API returned an invalid JSON response.');
  return body as T;
}

export interface ApiPage<T> { results: T[]; next?: string | null; previous?: string | null; count?: number }
export async function apiPage<T>(path: string, token: string, signal?: AbortSignal): Promise<ApiPage<T>> {
  const page = await apiRequest<ApiPage<T>>(path, token, { signal });
  if (!Array.isArray(page.results)) throw new Error('The API returned an invalid resource list.');
  return page;
}

export function nextPagePath(next: string, resource: string): string {
  // The Docker proxy can report an internal host in next links. Copy only
  // cursor parameters to the known local resource; never follow that host.
  const url = new URL(next, 'http://localhost');
  if (url.pathname !== resource || url.username || url.password || url.hash ||
      [...url.searchParams.keys()].some(key => !['cursor', 'page_size'].includes(key))) {
    throw new Error('Invalid pagination path.');
  }
  return apiPath(resource + url.search);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The request failed. Please try again.';
}

export async function apiDownload(path: string, token: string): Promise<Blob> {
  if (!token.trim()) throw new Error('Connect to your workspace before downloading.');
  const headers = new Headers({ Authorization: `Bearer ${token.trim()}` });
  if (activeProjectId) headers.set('X-Project-ID', activeProjectId);
  const response = await fetch(apiPath(path), { headers, redirect: 'error' });
  if (!response.ok) throw new ApiRequestError(`Download failed (HTTP ${response.status}).`, response.status);
  if (!response.headers.get('Content-Type')?.startsWith('application/zip')) throw new Error('The API did not return a model archive.');
  return response.blob();
}
