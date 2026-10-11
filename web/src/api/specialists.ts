import { apiRequest } from './client.ts';

export type SpecialistKind = 'ocr' | 'laya';
export interface SpecialistModel { id: string; name: string; kind: SpecialistKind; load_tested: boolean }
export interface SpecialistPin { name: string; repo_id: string; revision: string; license: string; byte_size: number }
export interface SpecialistCatalog { models: SpecialistModel[]; catalog: Record<SpecialistKind, SpecialistPin> }
export interface SpecialistResult {
  request_id: string; elapsed_seconds: number; device: string;
  text?: string; answers?: Record<string, Record<string, unknown>>;
  output_artifact?: { artifact_id: string; sha256: string }; envelope?: Record<string, unknown>;
  usage: Record<string, unknown>; provenance: Record<string, unknown>;
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
  if (!file.size || file.size > 8 * 1024 * 1024 || !['image/png', 'image/jpeg'].includes(file.type)) {
    throw new Error('Choose a PNG or JPEG of at most 8 MiB.');
  }
  const data = new FormData(); data.set('file', file);
  return apiRequest<{ artifact_id: string }>('/api/v1/specialists/upload-image/', token, { method: 'POST', body: data, signal });
}
