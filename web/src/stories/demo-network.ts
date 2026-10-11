import { delay, http, HttpResponse } from 'msw';
import { dataActions, dataResponses } from './data-fixtures';
import { mlActions, mlResponses } from './ml-fixtures';
import { operationsActions, operationsResponses } from './operations-fixtures';
import { workspaceActions, workspaceResponses } from './workspace-fixtures';

export const demoRequests: Array<{ path: string; method: string; status: number }> = [];
export const resetDemoRequests = () => { demoRequests.length = 0; };
export type DemoState = 'populated' | 'empty' | 'loading' | 'error';
const scopePaths = new Set(['/api/v1/health/', '/api/v1/tenants/', '/api/v1/projects/', '/api/v1/teams/']);
export function demoHandlers(state: DemoState = 'populated') {
  return [http.all('/api/v1/*', async ({ request }) => {
    const path = new URL(request.url).pathname;
    const respond = (value: unknown, status = 200) => { demoRequests.push({ path, method: request.method, status }); return HttpResponse.json(value as never, { status }); };
    const responses = { ...mlResponses, ...dataResponses, ...operationsResponses, ...workspaceResponses };
    const actions = { ...mlActions, ...dataActions, ...operationsActions, ...workspaceActions };
    if (!scopePaths.has(path)) {
      if (state === 'loading') await delay('infinite');
      if (state === 'error') return respond({ detail: 'Demo request failed. Try again.' }, 503);
    }
    if (request.method !== 'GET' && actions[path]) {
      const body = await request.json().catch(() => ({})) as Record<string, unknown>;
      return respond(actions[path](body));
    }
    let value = request.method === 'GET' ? responses[path] : undefined;
    if (value === undefined) {
      console.error(`Unmocked demo request: ${request.method} ${path}`);
      return respond({ detail: `No demo fixture for ${path}` }, 501);
    }
    if (state === 'empty' && !scopePaths.has(path)) {
      if (Array.isArray(value)) value = [];
      else if (path === '/api/v1/dataset-bank/sources/') value = { sources: [] };
    }
    return respond(Array.isArray(value) ? { results: value, count: value.length, next: null, previous: null } : value as never);
  })];
}
