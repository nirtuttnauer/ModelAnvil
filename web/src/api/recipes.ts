import { apiRequest } from './client.ts';

export type RecipeKind = 'source' | 'sample' | 'expression' | 'template' | 'generate' | 'validate' | 'merge' | 'output';
export interface RecipeStep { id: string; type: RecipeKind; input?: string; inputs?: string[]; format?: string; text_field?: string; group_field?: string | null; limit?: number; seed?: number; operation?: string; find?: string; replace?: string; template?: string; output?: string; max_tokens?: number; prompt_format?: string; min_characters?: number; required_keys?: string[]; contains?: string[] }
export interface RecipeDefinition { schema: 'modelanvil.recipe.v1'; name: string; steps: RecipeStep[] }
export interface RecipeBindings { recipe: string; sources: Record<string,string>; model?: string | null; device: string; pool: number; budget_policy: string; protected_sources: string[] }
export interface RecipeRun { run_id: string; job_id: string; status: string; preview: boolean; name?: string; attempt_count: number; max_attempts: number; desired_action: string; saved_rows: number; completed_steps: string[]; error: string; definition: RecipeDefinition; bindings: RecipeBindings; publication: {row_count?: number; rejected_count?: number; revision_id?: string; usage?: Record<string,number>}; result?: {rows: Record<string,unknown>[]; rejected: Record<string,unknown>[]} | null }

export function newStep(type: RecipeKind, id: string, input = ''): RecipeStep {
  const base = { id, type };
  if (type === 'source') return {...base, format:'json', text_field:'text'};
  if (type === 'sample') return {...base, input, limit:3, seed:42};
  if (type === 'expression') return {...base, input, operation:'strip'};
  if (type === 'template') return {...base, input, template:'Summarize this engineering note in one sentence: {{value}}'};
  if (type === 'generate') return {...base, input, output:'text', max_tokens:128, seed:42, prompt_format:'model'};
  if (type === 'validate') return {...base, input, min_characters:8, required_keys:[], contains:[]};
  if (type === 'merge') return {...base, inputs:input ? [input] : []};
  return {...base, input};
}

export function starterRecipe(generation = true): RecipeDefinition {
  const kinds: RecipeKind[] = generation ? ['source','sample','template','generate','validate','output'] : ['source','sample','expression','output'];
  return { schema:'modelanvil.recipe.v1', name:generation ? 'Engineering note summaries' : 'Document preparation',
    steps:kinds.map((kind,i) => newStep(kind,kind,i ? kinds[i-1] : '')) };
}

export function importRecipe(text: string): RecipeDefinition {
  if (new TextEncoder().encode(text).length > 64000) throw new Error('Recipe import exceeds 64,000 bytes.');
  const value = JSON.parse(text);
  if (value?.schema !== 'modelanvil.recipe.v1' || typeof value.name !== 'string' || !Array.isArray(value.steps) || value.steps.length < 2 || value.steps.length > 12 ||
      value.steps.some((s: RecipeStep) => !s || typeof s.id !== 'string' || !['source','sample','expression','template','generate','validate','merge','output'].includes(s.type))) {
    throw new Error('Import a supported recipe definition with 2–12 typed steps.');
  }
  return value;
}

export function graphErrors(recipe: RecipeDefinition): string[] {
  const seen = new Set<string>(); const errors: string[] = [];
  for (const step of recipe.steps) {
    if (!/^[a-z][a-z0-9_-]{0,31}$/.test(step.id) || seen.has(step.id)) errors.push(`Step ${step.id || '(unnamed)'} needs a unique valid ID.`);
    const inputs = step.type === 'source' ? [] : step.type === 'merge' ? step.inputs || [] : [step.input || ''];
    for (const input of inputs) if (!seen.has(input)) errors.push(`${step.id} depends on missing or later step ${input || '(none)'}.`);
    if (step.type === 'merge' && inputs.length < 2) errors.push(`${step.id} needs at least two inputs.`);
    seen.add(step.id);
  }
  if (recipe.steps.at(-1)?.type !== 'output') errors.push('The last step must publish the output.');
  return errors;
}

export async function uploadRecipeSource(token: string, file: File, format: string, signal?: AbortSignal) {
  if (!file.size || file.size > 16*1024**2) throw new Error('Choose a source file of at most 16 MiB.');
  const data = new FormData(); data.set('file',file); data.set('format',format);
  return apiRequest<{artifact_id:string}>('/api/v1/recipes/upload-source/',token,{method:'POST',body:data,signal});
}
