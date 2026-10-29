import { delay, http, HttpResponse } from 'msw';
import { dataActions, dataResponses } from './data-fixtures';
import { mlActions, mlResponses } from './ml-fixtures';
import { operationsActions, operationsResponses } from './operations-fixtures';
import { workspaceActions, workspaceResponses } from './workspace-fixtures';

export const demoRequests: Array<{ path: string; method: string; status: number; body?: Record<string, unknown> }> = [];
export const resetDemoRequests = () => { demoRequests.length = 0; };
export type DemoState = 'populated' | 'empty' | 'loading' | 'error';
const scopePaths = new Set(['/api/v1/build/', '/api/v1/health/', '/api/v1/accounts/access/', '/api/v1/tenants/', '/api/v1/projects/', '/api/v1/teams/', '/api/v1/activation/events/', '/api/v1/deployment-capabilities/']);
export function demoHandlers(state: DemoState = 'populated') {
  return [http.all('/api/v1/*', async ({ request }) => {
    const path = new URL(request.url).pathname;
    const respond = (value: unknown, status = 200, body?: Record<string, unknown>) => {
      demoRequests.push({ path, method: request.method, status, ...(body ? { body } : {}) });
      if (path.startsWith('/api/v1/annotation-tasks/') || /labeling-batches\/[^/]+\/tasks\//.test(path)) {
        if (new URL(request.url).searchParams.get('blind') === '1' || body?.blind_review === true) {
          const redact = (item: unknown): unknown => {
            if (Array.isArray(item)) return item.map(redact);
            if (!item || typeof item !== 'object') return item;
            const row = structuredClone(item) as Record<string, unknown>;
            if (row.content && typeof row.content === 'object') for (const key of ['draft_prediction', 'arena_vote', 'comparison_origin']) delete (row.content as Record<string, unknown>)[key];
            if (row.latest_review) row.latest_review = redact(row.latest_review);
            if (row.results) row.results = redact(row.results);
            if ('human_label' in row) { row.human_label = {}; row.original_prediction = {}; row.preference_choice = ''; }
            return row;
          };
          value = redact(value);
        }
      }
      return HttpResponse.json(value as never, { status });
    };
    const responses = { ...mlResponses, ...dataResponses, ...operationsResponses, ...workspaceResponses };
    const actions = { ...mlActions, ...dataActions, ...operationsActions, ...workspaceActions };
    if (!scopePaths.has(path)) {
      if (state === 'loading') await delay('infinite');
      if (state === 'error') return respond({ detail: 'Demo request failed. Try again.' }, 503);
    }
    if (request.method !== 'GET' && actions[path]) {
      const body = await request.json().catch(() => ({})) as Record<string, unknown>;
      return respond(actions[path](body), 200, body);
    }
    const speechOutput = path.match(/^\/api\/v1\/audio\/jobs\/[^/]+\/audio\/$/);
    if (request.method === 'GET' && speechOutput) {
      demoRequests.push({ path, method: request.method, status: 200 });
      return new HttpResponse(syntheticWav(), { status: 200, headers: { 'Content-Type': 'audio/wav' } });
    }
    const exportRun = path.match(/^\/api\/v1\/training-runs\/([^/]+)\/download\/$/);
    if (request.method === 'GET' && exportRun) {
      const exported = mlResponses[`/api/v1/training-runs/${exportRun[1]}/export/`] as { bundle: unknown } | undefined;
      const format = new URL(request.url).searchParams.get('export_format');
      return exported && format === 'json' ? respond(exported.bundle) : respond({ detail: 'This demo supports JSON fixture exports only.' }, 400);
    }
    const inspectedRevision = path.match(/^\/api\/v1\/dataset-revisions\/([^/]+)\/inspect\/$/);
    if (request.method === 'GET' && inspectedRevision) {
      const revisions = responses['/api/v1/dataset-revisions/'] as { revision_id?: string; row_count?: number }[];
      const revision = revisions?.find(row => row.revision_id === inspectedRevision[1]);
      return revision ? respond({ rows: [], total: revision.row_count || 0, next_cursor: null, recipe: {} }) : respond({ detail: 'Synthetic revision unavailable.' }, 404);
    }
    const decisionGate = path.match(/^\/api\/v1\/evaluation-runs\/([^/]+)\/decision-report\/$/);
    if (request.method === 'GET' && decisionGate) {
      return respond({ eligible: false, decisive: false, recommended_outcome: 'undecided', sample_count: 0, candidate_accuracy: null, baseline_accuracy: null, minimum_decisive_cases: 20, production_qualified: false, slices: [], gate: { passed: false, reason: 'Synthetic demo: no decision gate was evaluated.' } });
    }
    const retrievalEvidence = path.match(/^\/api\/v1\/index-versions\/[^/]+\/(judgment-pool|traces|comparisons|projection)\/$/);
    if (request.method === 'GET' && retrievalEvidence) {
      return respond(retrievalEvidence[1] === 'projection'
        ? { available: false, reason: 'Synthetic preview: no measured embedding projection has been supplied.' }
        : { results: [], total: 0, next_offset: null, limit: 50 });
    }
    if (request.method === 'GET' && path === '/api/v1/context-experiments/') return respond({ results: [], next: null, count: 0 });
    let value = request.method === 'GET' ? responses[path] : undefined;
    if (value === undefined) {
      console.error(`Unmocked demo request: ${request.method} ${path}`);
      return respond({ detail: `No demo fixture for ${path}` }, 501);
    }
    if (state === 'empty' && !scopePaths.has(path)) {
      if (Array.isArray(value)) value = [];
      else if (path === '/api/v1/dataset-bank/sources/') value = { sources: [] };
    }
    return respond(Array.isArray(value) && !['/api/v1/recipes/', '/api/v1/recipes/runs/', '/api/v1/specialists/jobs/', '/api/v1/audio/jobs/', '/api/v1/tools/jobs/'].includes(path) ? { results: value, count: value.length, next: null, previous: null } : value as never);
  })];
}

/** A quarter second of silent 16 kHz mono PCM16 WAV so the audio demo can play a verified output without a speech model. */
function syntheticWav(): ArrayBuffer {
  const sampleRate = 16000, samples = 4000, dataBytes = samples * 2;
  const buffer = new ArrayBuffer(44 + dataBytes), view = new DataView(buffer);
  const text = (offset: number, value: string) => { for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index)); };
  text(0, 'RIFF'); view.setUint32(4, 36 + dataBytes, true); text(8, 'WAVE');
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, dataBytes, true);
  return buffer;
}
