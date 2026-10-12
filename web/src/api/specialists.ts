import { apiRequest } from './client.ts';

export type SpecialistKind = 'ocr' | 'laya' | 'layout';
export interface SpecialistModel { id: string; name: string; kind: SpecialistKind; load_tested: boolean }
export interface SpecialistPin { name: string; repo_id: string; revision: string; license: string; byte_size: number }
export interface SpecialistCatalog { models: SpecialistModel[]; catalog: Record<SpecialistKind, SpecialistPin> }
export interface SpecialistResult {
  request_id: string; elapsed_seconds: number; device: string;
  text?: string; answers?: Record<string, Record<string, unknown>>;
  output_artifact?: { artifact_id: string; sha256: string }; envelope?: Record<string, unknown>;
  usage: Record<string, unknown>; provenance: Record<string, unknown>;
  pages?: { page: number; image_dimensions: [number, number]; regions?: LayoutRegion[] }[];
}

export interface LayoutRegion { region_id: string; order: number; label: string; confidence: number; box: [number, number, number, number]; text?: string }
export interface SpecialistJob { request_id: string; job_id: string; status: string; kind?: SpecialistKind; attempt_count: number; max_attempts: number; desired_action: string; error: string; completed_pages?: number[]; page_count?: number; result?: SpecialistResult | null }

export async function queueSpecialist(token: string, kind: SpecialistKind, request: Record<string, unknown>, pool: string, policy: string, signal?: AbortSignal) {
  if (!pool || !policy) throw new Error('Select a specialist worker pool and attempt quota.');
  return apiRequest<SpecialistJob>('/api/v1/specialists/jobs/', token, { method: 'POST', signal,
    body: JSON.stringify({ kind, request, pool: Number(pool), budget_policy: policy, idempotency_key: crypto.randomUUID() }) });
}

export function questionInput(type: 'choice' | 'score' | 'noul', instructions: string, options: string) {
  if (!instructions.trim()) throw new Error('Enter a question.');
  if (type === 'noul') return { type, instructions };
  const lines = options.split('\n').map(line => line.trim()).filter(Boolean);
  if (lines.length < 2 || lines.length > 8) throw new Error('Enter 2–8 options, one per line.');
  if (type === 'score') return { type, instructions, criteria: lines };
  const criteria: Record<string, string> = {};
  for (const line of lines) {
    const colon = line.indexOf(':');
    const label = (colon < 0 ? line : line.slice(0, colon)).trim();
    const description = (colon < 0 ? line : line.slice(colon + 1)).trim();
    if (!label || !description || Object.hasOwn(criteria, label)) throw new Error('Choice labels must be unique and have a description.');
    Object.defineProperty(criteria, label, { value: description, enumerable: true });
  }
  return { type, instructions, criteria };
}

export async function uploadOcrImage(token: string, file: File, signal?: AbortSignal) {
  if (!file.size || file.size > 8 * 1024 * 1024 || !['image/png', 'image/jpeg', 'application/pdf'].includes(file.type)) {
    throw new Error('Choose a PNG, JPEG or PDF of at most 8 MiB.');
  }
  const data = new FormData(); data.set('file', file);
  return apiRequest<{ artifact_id: string }>('/api/v1/specialists/upload-image/', token, { method: 'POST', body: data, signal });
}
