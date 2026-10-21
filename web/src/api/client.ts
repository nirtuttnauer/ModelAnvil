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

export function authHeaders(token: string): Headers {
  const headers = new Headers();
  if (token === 'session') {
    const csrf = typeof document === 'undefined' ? '' : document.cookie.split('; ').find(v => v.startsWith('csrftoken='))?.slice(10);
    if (csrf) headers.set('X-CSRFToken', decodeURIComponent(csrf));
  } else if (token.trim()) headers.set('Authorization', `Bearer ${token.trim()}`);
  return headers;
}

export async function apiRequest<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const safePath = apiPath(path);
  if (!token.trim()) throw new Error('Enter an API key to connect to this workspace.');
  const headers = new Headers(init.headers);
  authHeaders(token).forEach((value, name) => headers.set(name, value));
  if (activeProjectId) {
    headers.set('X-Project-ID', activeProjectId);
  }
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(safePath, { ...init, headers, redirect: 'error' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new Error(token === 'session' ? 'Could not reach ModelAnvil. Try again when the app is available.' : 'Could not reach the API. Check the Docker stack and try Refresh.');
  }
  if (response.ok && response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status}).`;
    if (response.status === 401) message = token === 'session' ? 'Your session expired. Sign in again.' : 'Authentication failed. Check your API key and reconnect.';
    else if (response.status === 403) message = token === 'session' ? 'Your account does not have permission for this action. If you just signed in, refresh and try again.' : 'Your API key does not have permission for this action.';
    else if (response.status < 500) {
      message = body?.error?.message || body?.detail || (typeof body?.error === 'string' ? body.error : message);
      const details = body?.error?.details;
      if (Array.isArray(details)) message += ' ' + details.map((d: { path?: string; message?: string }) => `${d.path && d.path !== '(root)' ? d.path + ': ' : ''}${d.message || 'Invalid value'}`).join(' ');
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
  const base = new URL(apiPath(resource), 'http://localhost');
  const filters = [...base.searchParams.keys()].filter(key => !['cursor', 'page_size'].includes(key));
  if (url.pathname !== base.pathname || url.username || url.password || url.hash ||
      [...url.searchParams.keys()].some(key => !['cursor', 'page_size', ...filters].includes(key)) ||
      filters.some(key => url.searchParams.get(key) !== base.searchParams.get(key))) {
    throw new Error('Invalid pagination path.');
  }
  return apiPath(base.pathname + url.search);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'The request failed. Please try again.';
}

export async function apiDownload(path: string, token: string): Promise<Blob> {
  if (!token.trim()) throw new Error('Connect to your workspace before downloading.');
  const headers = authHeaders(token);
  if (activeProjectId) headers.set('X-Project-ID', activeProjectId);
  const response = await fetch(apiPath(path), { headers, redirect: 'error' });
  if (!response.ok) throw new ApiRequestError(`Download failed (HTTP ${response.status}).`, response.status);
  if (!response.headers.get('Content-Type')?.startsWith('application/zip')) throw new Error('The API did not return a model archive.');
  return response.blob();
}

/** Stream large artifacts directly to disk with the workspace's current authorization. */
export async function saveArtifact(id: string, name: string, token: string, signal?: AbortSignal): Promise<void> {
  if (!token.trim()) throw new Error('Enter an API key to download files.');
  const picker = (window as unknown as { showSaveFilePicker?: (options: { suggestedName: string }) => Promise<{ createWritable(): Promise<WritableStream> }> }).showSaveFilePicker;
  if (!picker) throw new Error('Saving large files requires a browser with the file save picker, such as Chrome or Edge. You can also stream the artifact download API with an authenticated client.');
  const project = getActiveProjectId();
  const handle = await picker.call(window, { suggestedName: name });
  if (signal?.aborted) return;
  const headers = authHeaders(token);
  if (project) headers.set('X-Project-ID', project);
  const response = await fetch(apiPath(`/api/v1/artifacts/${encodeURIComponent(id)}/download/`), { headers, signal, redirect: 'error' });
  if (!response.ok || !response.body) throw new Error(`Download failed (HTTP ${response.status}).`);
  const writable = await handle.createWritable();
  await response.body.pipeTo(writable, { signal });
}
