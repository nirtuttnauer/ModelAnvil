// All values in this module are synthetic visual-verification fixtures.
const trainingId = '30000000-0000-4000-8000-000000000001';
const recipeId = 'a0000000-0000-4000-8000-000000000001';
const time = '2026-10-11T09:15:00Z';
const checkpoint = { checkpoint_id: '70000000-0000-4000-8000-000000000003', step: 50, state_digest: '3'.repeat(64), is_valid: true, contract_digest: 'd'.repeat(64), weights_sha256: 'f'.repeat(64), created_at: time };
const candidate = { available: true, reason: 'Valid demo checkpoint.', checkpoint_id: checkpoint.checkpoint_id, step: 50, state_digest: checkpoint.state_digest, contract_digest: checkpoint.contract_digest };
const speechJobId = 'b0000000-0000-4000-8000-000000000001';
const speechQueuedId = 'b0000000-0000-4000-8000-000000000002';
const toolRunId = 'b1000000-0000-4000-8000-000000000001';
const researchSessionId = 'b2000000-0000-4000-8000-000000000001';
const fixtureEvidence = (what: string) => ({ level: 'fixture', source: `Storybook synthetic demo. ${what}` });
const speechJob = { request_id: speechJobId, job_id: '40000000-0000-4000-8000-000000000041', status: 'succeeded', desired_action: 'run', text: 'Hello world.', seed: 42, max_seconds: 6,
  result: { report: { duration_seconds: 0.25, frames: 4000, sample_rate: 16000 }, model: { id: 'speecht5-demo', name: 'SpeechT5 TTS · Demo', revision: '0'.repeat(40) }, processor: { name: 'speecht5-processor · Demo', revision: '0'.repeat(40) },
    vocoder: { name: 'hifigan · Demo', revision: '0'.repeat(40) }, conditioning: 'published-demo-speaker', evidence: fixtureEvidence('No speech model was executed; the WAV is generated silence.') } };
const speechQueued = { request_id: speechQueuedId, job_id: '40000000-0000-4000-8000-000000000042', status: 'queued', desired_action: 'run', text: 'Your dataset is ready.', seed: 7, max_seconds: 4 };
const toolRun = { request_id: toolRunId, job_id: '40000000-0000-4000-8000-000000000043', status: 'succeeded', desired_action: 'run', attempt_count: 1,
  answer: '17 plus 25 is **42**.\n\nThe `add` tool returned 42, so the sum is confirmed from its actual result.',
  trace: [
    { kind: 'model_turn', content: 'I will call add with 17 and 25.', usage: { generated_tokens: 18 } },
    { kind: 'tool_call', id: 'call-1', name: 'add', successful: true, content: '{"a": 17, "b": 25}' },
    { kind: 'tool_result', id: 'call-1', name: 'add', successful: true, content: '42' },
    { kind: 'model_turn', content: '17 plus 25 is 42.', usage: { generated_tokens: 43 } },
  ],
  usage: { generated_tokens: 61, context_tokens: 912, tool_calls: 1, model_turns: 2, evidence: fixtureEvidence('No tool model was executed.') },
  trace_artifact: { artifact_id: 'b1000000-0000-4000-8000-000000000011', bytes: 2048 } };
const researchSession = { session_id: researchSessionId, title: 'Dataset preparation notes · Demo', revision_no: 3, evidence_available: true,
  memory: { retained_turns: 1, retained_tokens: 96, omitted_prefixes: 0, compaction: 'pinned_verbatim', evidence: fixtureEvidence('Memory counts are synthetic.') },
  documents: [
    { document_id: 'b2000000-0000-4000-8000-000000000011', title: 'Dataset preparation guide.md', available: true, source_uri: 'upload://dataset-preparation-guide.md', metadata: { kind: 'upload', bytes: 1842, extractor: 'utf8-text', sha256: '1'.repeat(64) } },
    { document_id: 'b2000000-0000-4000-8000-000000000012', title: 'Revoked release notes', available: false, source_uri: 'https://docs.example.test/releases', metadata: {} },
  ],
  turns: [{ question: 'How should I prepare this dataset before training?', generation: { status: 'answered', answer: 'Validate the splits first, then publish an immutable revision before launching training [1].',
    citations: [{ label: 1, title: 'Dataset preparation guide.md', source_uri: 'upload://dataset-preparation-guide.md', span_start: 0, span_end: 118, chunk_id: 'b2000000-0000-4000-8000-000000000021' }],
    receipt: { generation_executed: false, reason: 'synthetic_fixture', elapsed_ms: 0, usage: { prompt_tokens: 212, completion_tokens: 24 }, evidence: fixtureEvidence('No answer model was executed.') } } }],
  research_steps: [] };
export const workspaceResponses: Record<string, unknown> = {
  '/api/v1/deployment-capabilities/': { mode: 'local', role: 'engineer', operations: {
    classification: { enabled: false, reason: 'Synthetic preview; no local training worker.' },
    local_training: { enabled: false, reason: 'Synthetic preview; no local training worker.' },
    evaluation: { enabled: true, reason: 'Synthetic fixture actions only.', limits: { max_cases: 64, max_output_tokens: 32 } },
    chat: { enabled: false, reason: 'Synthetic preview.' }, model_export: { enabled: true, reason: 'Fixture exports only.' }, team_management: { enabled: false, reason: 'Installation owner only.' },
  }, readiness: { training_enabled: false, training_busy: false, qualification_scope: 'synthetic-preview', production_qualified: false } },
  '/api/v1/activation/report/': { week_start: '2026-10-26', weekly_improvement_cycles: 0, weekly_accepted_improvements: 0, weekly_rejected_candidates: 0, reported_active_seconds: 0, time_to_first_decision_seconds: null },
  '/api/v1/artifacts/': [],
  '/api/v1/inference/models/': { data: [{ id: '10000000-0000-4000-8000-000000000002', name: 'Local text model · Demo', format: 'cpu-reference', chat_template: '', devices: ['cpu'], max_tokens: 128, context_limit: 2048, load_tested: false }] },
  '/api/v1/recipes/': [],
  '/api/v1/recipes/runs/': [],
  '/api/v1/specialists/': {
    models: [{ id: 'demo-ocr', name: 'OCR model · Demo', kind: 'ocr', load_tested: false }, { id: 'demo-decisions', name: 'Decision model · Demo', kind: 'laya', load_tested: false }],
    catalog: Object.fromEntries(['ocr', 'laya', 'layout'].map(kind => [kind, { name: `${kind} · Demo`, repo_id: `storybook/demo-${kind}`, revision: '0'.repeat(40), license: 'Synthetic fixture only', byte_size: 0 }])),
  },
  '/api/v1/specialists/jobs/': [],
  '/api/v1/chat-conversations/': [],
  '/api/v1/chat-comparisons/': [],
  '/api/v1/audio/': { models: [{ id: 'speecht5-demo', name: 'SpeechT5 TTS · Demo', trained: false }, { id: 'speecht5-support-demo', name: 'SpeechT5 support voice · Demo', trained: true }] },
  '/api/v1/audio/jobs/': [speechQueued, speechJob],
  [`/api/v1/audio/jobs/${speechJobId}/`]: speechJob,
  [`/api/v1/audio/jobs/${speechQueuedId}/`]: speechQueued,
  '/api/v1/tools/': { models: [{ id: 'qwen3-tools-demo', name: 'Qwen3 tool model · Demo' }], mcp_targets: ['bounded-math'], code_execution: true, sandbox: { available: true },
    installed_mcp_targets: [
      { id: 'bounded-math', name: 'Bounded math', kind: 'local', available: true, allowed_tools: ['add', 'multiply'], endpoint: 'stdio://bounded-math' },
      { id: 'remote-docs', name: 'Remote docs', kind: 'remote', available: false, allowed_tools: ['search'], endpoint: 'https://docs.example.test/mcp', reason: 'Offline mode blocks remote targets.' },
    ] },
  '/api/v1/tools/jobs/': [toolRun],
  [`/api/v1/tools/jobs/${toolRunId}/`]: toolRun,
  '/api/v1/research-sessions/': { sessions: [{ session_id: researchSessionId, title: researchSession.title }], models: [{ id: '10000000-0000-4000-8000-000000000002', name: 'Local text model · Demo' }] },
  [`/api/v1/research-sessions/${researchSessionId}/`]: researchSession,
  '/api/v1/fine-tuning/options/': {
    compute: { available: false, busy: false, device: null, message: 'Storybook preview. Local training is not connected in this demo.' },
    model: { id: 'smollm2-135m-instruct', name: 'SmolLM2-135M Instruct', parameters: 135000000, description: 'Synthetic model choice for the guided-flow preview.', license: 'Apache-2.0', max_examples: 1000, max_tokens: 128,
      source: { repo_id: 'storybook/synthetic-model', revision: '0'.repeat(40) } }, default_epochs: 3, max_steps: 3000,
  },
  '/api/v1/model-imports/': [],
  '/api/v1/build/': typeof __API_BUILD__ === 'undefined' ? { revision: 'storybook-demo', source_digest: 'synthetic-fixture', protocol: 'demo-only', dataset_formats: ['jsonl', 'csv', 'json', 'docx', 'pdf'] } : __API_BUILD__,
  '/api/v1/health/': { status: 'ok' },
  '/api/v1/accounts/access/': { role: 'engineer' },
  '/api/v1/capability-ledger/': { generated_tokens: 32 },
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
  '/api/v1/activation/events/': () => ({ recorded: true, demo_only: true }),
  '/api/v1/tools/discover/': body => ({ target: body.target, tools: [
    { name: 'add', description: 'Add two bounded integers.', input_schema: { type: 'object', properties: { a: { type: 'integer' }, b: { type: 'integer' } }, required: ['a', 'b'] } },
    { name: 'multiply', description: 'Multiply two bounded integers.', input_schema: { type: 'object', properties: { a: { type: 'integer' }, b: { type: 'integer' } }, required: ['a', 'b'] } },
  ], evidence: fixtureEvidence('Schemas are synthetic.') }),
  '/api/v1/audio/jobs/': body => {
    const jobs = workspaceResponses['/api/v1/audio/jobs/'] as Array<Record<string, unknown>>;
    const job = { request_id: `b0000000-0000-4000-8000-${String(100 + jobs.length).padStart(12, '0')}`, job_id: `40000000-0000-4000-8000-${String(100 + jobs.length).padStart(12, '0')}`, status: 'queued', desired_action: 'run', text: body.text, seed: body.seed, max_seconds: body.max_seconds };
    jobs.unshift(job); workspaceResponses[`/api/v1/audio/jobs/${job.request_id}/`] = job; return job;
  },
  '/api/v1/tools/jobs/': body => {
    const runs = workspaceResponses['/api/v1/tools/jobs/'] as Array<Record<string, unknown>>;
    const run = { request_id: `b1000000-0000-4000-8000-${String(100 + runs.length).padStart(12, '0')}`, job_id: `40000000-0000-4000-8000-${String(200 + runs.length).padStart(12, '0')}`, status: 'queued', desired_action: 'run', attempt_count: 0, prompt: body.prompt, targets: body.targets, code_execution: body.code_execution };
    runs.unshift(run); workspaceResponses[`/api/v1/tools/jobs/${run.request_id}/`] = run; return run;
  },
  '/api/v1/research-sessions/': body => {
    const catalog = workspaceResponses['/api/v1/research-sessions/'] as { sessions: Array<{ session_id: string; title: string }> };
    const session = { ...structuredClone(researchSession), session_id: `b2000000-0000-4000-8000-${String(100 + catalog.sessions.length).padStart(12, '0')}`, title: String(body.title || 'Document research'), revision_no: 1, documents: [], turns: [], memory: { retained_turns: 0, retained_tokens: 0, omitted_prefixes: 0, compaction: 'pinned_verbatim' } };
    catalog.sessions.unshift({ session_id: session.session_id, title: session.title }); workspaceResponses[`/api/v1/research-sessions/${session.session_id}/`] = session; return session;
  },
  [`/api/v1/research-sessions/${researchSessionId}/ask/`]: body => {
    const session = workspaceResponses[`/api/v1/research-sessions/${researchSessionId}/`] as typeof researchSession;
    session.turns.push({ question: String(body.question || ''), generation: { status: 'answered', answer: 'The demo answer repeats the saved guidance: validate splits before publishing [1].', citations: researchSession.turns[0].generation.citations, receipt: { generation_executed: false, reason: 'synthetic_fixture', elapsed_ms: 0, usage: { prompt_tokens: 240, completion_tokens: 20 }, evidence: fixtureEvidence('No answer model was executed.') } } });
    session.revision_no += 1; return session;
  },
  [`/api/v1/research-sessions/${researchSessionId}/clear-memory/`]: () => {
    const session = workspaceResponses[`/api/v1/research-sessions/${researchSessionId}/`] as typeof researchSession;
    session.turns = []; session.memory = { retained_turns: 0, retained_tokens: 0, omitted_prefixes: 0, compaction: 'pinned_verbatim', evidence: fixtureEvidence('Memory counts are synthetic.') }; session.revision_no += 1; return session;
  },
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
