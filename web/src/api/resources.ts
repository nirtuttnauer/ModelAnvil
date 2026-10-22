import { apiPage, apiRequest, nextPagePath, type ApiPage } from './client.ts';

export async function allResources<T>(path: string, token: string, signal?: AbortSignal, scope: 'project' | 'organization' = 'project'): Promise<T[]> {
  const items: T[] = [];
  const visited = new Set<string>();
  let next: string | null = path;
  while (next) {
    if (visited.has(next)) throw new Error('The API returned a repeated pagination cursor.');
    visited.add(next);
    const page: ApiPage<T> = await apiPage<T>(next, token, signal, scope);
    items.push(...page.results);
    next = page.next ? nextPagePath(page.next, path) : null;
  }
  return items;
}

export async function downloadJson(path: string, token: string, filename: string) {
  const value = await apiRequest<unknown>(path, token);
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface ModelCapabilities {
  memory_requirements?: import('./model-hardware').ModelMemory;
  train: { eligible: boolean; recipes: string[]; reason: string };
  evaluate: { eligible: boolean; reason: string };
  chat: { eligible: boolean; devices: string[]; reason: string };
}
export interface RegisteredModel { id: number; model_version_id: string; model_name: string; revision_no: number; state: string; capabilities?: ModelCapabilities }

export interface Project {
  id: string;
  team: string;
  team_slug: string;
  slug: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface Team {
  id: string;
  slug: string;
  name: string;
  description: string;
}

export interface TokenizerVersion {
  id: number;
  tokenizer_id: string;
  name: string;
  revision_no: number;
  vocabulary_size: number;
  special_tokens: Record<string, string>;
  created_at: string;
}

export interface RegisteredModelVersion {
  id: number;
  model_version_id: string;
  model: number;
  model_name: string;
  revision_no: number;
  architecture_ref: string;
  tokenizer: number;
  state: string;
  parameters_count: number;
  license_evidence: string;
  created_at: string;
}
