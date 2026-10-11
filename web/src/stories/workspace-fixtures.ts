// All values in this module are synthetic visual-verification fixtures.
const trainingId = '30000000-0000-4000-8000-000000000001';
const recipeId = 'a0000000-0000-4000-8000-000000000001';
const time = '2026-10-11T09:15:00Z';
const checkpoint = { checkpoint_id: '70000000-0000-4000-8000-000000000003', step: 50, state_digest: '3'.repeat(64), is_valid: true, contract_digest: 'd'.repeat(64), weights_sha256: 'f'.repeat(64), created_at: time };
const candidate = { available: true, reason: 'Valid demo checkpoint.', checkpoint_id: checkpoint.checkpoint_id, step: 50, state_digest: checkpoint.state_digest, contract_digest: checkpoint.contract_digest };
export const workspaceResponses: Record<string, unknown> = {
  '/api/v1/health/': { status: 'ok' },
  '/api/v1/tenants/': [{ tenant_id: 'demo-tenant', name: 'Anvil Research · Demo' }],
  '/api/v1/teams/': [{ id: 'demo-team', slug: 'research', name: 'Research', description: 'Synthetic Storybook team.' }],
  '/api/v1/projects/': [{ id: '1', team: 'demo-team', team_slug: 'research', slug: 'assistant', name: 'Assistant Research · Demo', description: 'Synthetic Storybook workspace.', created_at: time, updated_at: time }],
  '/api/v1/context-recipe-versions/': [{ recipe_version_id: recipeId, recipe: 1, revision_no: 4, model_limit_tokens: 8192, output_reserve_tokens: 1024, budget_policy: 'trim_lowest_priority', blocks: [
    { block_key: 'system', content_template: 'You are the demo support assistant. Answer using the supplied evidence.' },
    { block_key: 'retrieved_evidence', content_template: 'Published dataset revisions are immutable. Validate splits before launching training.' },
    { block_key: 'question', content_template: 'How should I prepare this dataset for training?' },
    { block_key: 'optional_examples', content_template: 'Optional examples have a lower priority than the source evidence.' },
  ] }],
  [`/api/v1/run-details/training/${trainingId}/`]: {
    kind: 'training', id: trainingId, name: 'Anvil Assistant · SFT demo', project: '1', execution_mode: 'worker',
    observed: { state: 'completed', job_state: 'succeeded', current_step: 50, total_steps: 50, progress: 1, latest_loss: 1.372, attempts: '1 recorded attempt', created_at: time, started_at: time, completed_at: '2026-10-11T09:24:00Z', updated_at: '2026-10-11T09:24:00Z' },
    desired: { action: '', acknowledged: false, note: '' },
    ownership: { state: 'released', worker: 'CPU research worker · Demo', worker_status: 'idle', lease_expires_at: null, reason: 'Demo attempt completed and released its lease.' },
    inputs: { model_version: '10000000-0000-4000-8000-000000000002', dataset_revision: '20000000-0000-4000-8000-000000000002', recipe_type: 'full_sft', seed: 42 },
    metrics: { total: 11, truncated: false, latest_loss: 1.372, rows: [4.852, 3.731, 2.943, 2.401, 2.122, 1.887, 1.716, 1.598, 1.486, 1.421, 1.372].map((loss, index) => ({ step: index * 5, loss })) },
    checkpoints: { total: 1, truncated: false, rows: [checkpoint], resume_candidate: candidate },
    usage: { reservations: [{ reservation_id: 'demo-reservation', policy_name: 'Research training · Demo', unit: 'training_steps', state: 'settled', estimated_amount: '50', settled_amount: '50' }], events: [{ usage_id: 'demo-usage', quantity: '50', unit: 'training_steps', occurred_at: time }], events_truncated: false },
    links: { dataset_revision: '20000000-0000-4000-8000-000000000002', output_model_version: '10000000-0000-4000-8000-000000000002', job: '40000000-0000-4000-8000-000000000001' },
    evidence: { level: 'fixture', source: 'Storybook synthetic demo. No model was executed or qualified.' },
    actions: { cancel: { available: false, requested: false, acknowledged: false, endpoint: null, blocked_by: ['Demo run is terminal.'] }, resume: { available: false, blocked_by: ['Completed runs cannot be resumed.'], permission: { role: 'operator', required: 'operator', satisfied: true }, checkpoint: candidate, preserves_history: 'Prior attempts and checkpoints remain immutable.' } },
    generated_at: time,
  },
  [`/api/v1/run-details/training/${trainingId}/attempts/`]: [{ attempt_id: 'demo-attempt', job_id: '40000000-0000-4000-8000-000000000001', worker: 'CPU research worker · Demo', worker_status: 'idle', status: 'succeeded', progress: 1, error: '', lease_expires_at: null, started_at: time, completed_at: '2026-10-11T09:24:00Z', has_result: true }],
};
export const workspaceActions: Record<string, (body: Record<string, unknown>) => unknown> = {
  [`/api/v1/context-recipe-versions/${recipeId}/compile/`]: (body) => ({ serialized_prompt: `You are the demo support assistant.\n\nPublished dataset revisions are immutable. Validate splits before launching training.\n\n${(body.variables as Record<string, unknown> | undefined)?.question || 'How should I prepare this dataset for training?'}`, token_count: 1842, included_blocks: ['system', 'retrieved_evidence', 'question'], dropped_blocks: ['optional_examples'], budget_exhausted: false }),
};

// These authoring actions are synthetic and never reach the live API.
workspaceActions['/api/v1/context-recipes/'] = body => {
  const input = body.initial_version as Record<string, unknown>;
  const versions = workspaceResponses['/api/v1/context-recipe-versions/'] as Array<Record<string, unknown>>;
  const version = { ...input, recipe_version_id: 'a0000000-0000-4000-8000-000000000002', recipe: 2, revision_no: 1 };
  versions.push(version);
  workspaceActions[`/api/v1/context-recipe-versions/${version.recipe_version_id}/compile/`] = data => {
    const blocks: Array<Record<string, unknown>> = (input.blocks as Array<Record<string, unknown>>).map(block => ({ ...block, content_template: (data.variables as Record<string, unknown> | undefined)?.[String(block.block_key)] ?? block.content_template }));
    return { serialized_prompt: blocks.map(block => `<|im_start|>${block.role}\n${block.content_template}<|im_end|>`).join('\n'), token_count: 80, included_blocks: blocks.map(block => block.block_key), dropped_blocks: [], budget_exhausted: false, token_count_method: 'synthetic_fixture' };
  };
  return { id: 2, recipe_id: 'a0000000-0000-4000-8000-000000000003', name: body.name, versions: [version] };
};
const initialWorkspaceResponses = structuredClone(workspaceResponses);
const initialWorkspaceActions = new Set(Object.keys(workspaceActions));
export function resetWorkspaceFixtures(): void {
  for (const key of Object.keys(workspaceResponses)) delete workspaceResponses[key];
  Object.assign(workspaceResponses, structuredClone(initialWorkspaceResponses));
  for (const key of Object.keys(workspaceActions)) if (!initialWorkspaceActions.has(key)) delete workspaceActions[key];
}
