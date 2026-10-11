// Fictional Storybook fixtures only. These values are not runtime or qualification evidence.
let nextDemoId = 10;
const demoUuid = () => `90000000-0000-4000-8000-${String(nextDemoId++).padStart(12, '0')}`;
const createdAt = '2026-10-11T09:15:00Z';
const registeredCaseSets: Record<string, Array<Record<string, unknown>>> = {};
const digest = (character: string) => character.repeat(64);
const ids = {
  model: '10000000-0000-4000-8000-000000000001',
  version: '10000000-0000-4000-8000-000000000002',
  tokenizer: '10000000-0000-4000-8000-000000000003',
  revision: '20000000-0000-4000-8000-000000000002',
  training: '30000000-0000-4000-8000-000000000001',
  evaluation: '30000000-0000-4000-8000-000000000002',
  alignment: '30000000-0000-4000-8000-000000000003',
  job: '40000000-0000-4000-8000-000000000001',
  policy: '50000000-0000-4000-8000-000000000001',
};
const fixtureEvidence = { level: 'fixture', source: 'Storybook fictional demo data. No model was executed or qualified.' };
const alignmentCapabilities = { can_execute: false, supported_algorithms: ['dpo', 'reward_model', 'ppo_rlhf', 'verifier_rl'], runtime: 'modelanvil.cpu-character-alignment.v1', reason: 'Fictional Storybook record; legacy fixture metrics do not establish performance.' };
const preferenceArtifacts = [
  { artifact_id: '80000000-0000-4000-8000-000000000001', name: 'Training preferences · Demo', sha256: digest('7'), byte_size: 192, row_count: 2, state: 'committed' },
  { artifact_id: '80000000-0000-4000-8000-000000000002', name: 'Held-out preferences · Demo', sha256: digest('8'), byte_size: 168, row_count: 2, state: 'committed' },
];
const models = [
  { id: 1, model_id: ids.model, name: 'Anvil Assistant', description: 'Demo conversational model family for support and grounded question answering.', intended_tasks: ['text_generation', 'reasoning', 'support'], created_at: createdAt },
  { id: 2, model_id: '10000000-0000-4000-8000-000000000004', name: 'Anvil Retriever', description: 'Demo retrieval model family for document search and context ranking.', intended_tasks: ['retrieval', 'ranking'], created_at: createdAt },
  { id: 3, model_id: '10000000-0000-4000-8000-000000000005', name: 'Anvil Verifier', description: 'Demo evaluator model family for answer checking and preference experiments.', intended_tasks: ['reasoning', 'verification'], created_at: createdAt },
];
const tokenizers = [
  { id: 1, tokenizer_id: ids.tokenizer, name: 'Anvil Character', revision_no: 1, vocabulary_size: 128, special_tokens: { bos_token: '<s>', eos_token: '</s>' }, created_at: createdAt },
  { id: 2, tokenizer_id: '10000000-0000-4000-8000-000000000006', name: 'Anvil Character Extended', revision_no: 2, vocabulary_size: 192, special_tokens: { bos_token: '<s>', eos_token: '</s>' }, created_at: createdAt },
];
const versions = [
  { id: 1, model_version_id: ids.version, model: 1, model_name: 'Anvil Assistant', revision_no: 8, architecture_ref: 'demo/anvil-character-16', tokenizer: 1, state: 'candidate', parameters_count: 4096, license_evidence: 'Fictional demo record · MIT', created_at: createdAt },
  { id: 2, model_version_id: '10000000-0000-4000-8000-000000000007', model: 1, model_name: 'Anvil Assistant', revision_no: 7, architecture_ref: 'demo/anvil-character-16', tokenizer: 1, state: 'candidate', parameters_count: 4096, license_evidence: 'Fictional demo record · MIT', created_at: createdAt },
  { id: 3, model_version_id: '10000000-0000-4000-8000-000000000008', model: 3, model_name: 'Anvil Verifier', revision_no: 2, architecture_ref: 'demo/anvil-character-8', tokenizer: 2, state: 'draft', parameters_count: 2048, metadata: { model_role: 'reward_model', fixture_only: true }, license_evidence: 'Fictional demo record · MIT', created_at: createdAt },
];
const revisions = [
  { id: 1, revision_id: ids.revision, dataset: 1, dataset_name: 'Assistant instruction corpus', revision_no: 1, schema_version: '1.0', manifest_digest: digest('a'), manifest_artifact: 11, recipe_digest: digest('b'), row_count: 1200, state: 'published', created_at: createdAt, published_at: '2026-10-11T08:30:00Z', metadata: { preparation_kind: 'bounded_local_jsonl_v1', input_sha256: digest('c'), split_counts: { train: 960, validation: 120, test: 120 } } },
  { id: 2, revision_id: '20000000-0000-4000-8000-000000000004', dataset: 2, dataset_name: 'Lucide SVG instructions', revision_no: 2, schema_version: '1.0', manifest_digest: digest('d'), manifest_artifact: 12, recipe_digest: digest('e'), row_count: 480, state: 'published', created_at: createdAt, published_at: '2026-10-10T14:20:00Z', metadata: { preparation_kind: 'bounded_local_jsonl_v1', input_sha256: digest('f'), split_counts: { train: 384, validation: 48, test: 48 } } },
  { id: 3, revision_id: '20000000-0000-4000-8000-000000000005', dataset: 2, dataset_name: 'Lucide SVG instructions', revision_no: 3, schema_version: '1.0', manifest_digest: '', manifest_artifact: null, recipe_digest: '', row_count: null, state: 'draft', created_at: createdAt, published_at: null, metadata: { notes: 'Awaiting source verification.' } },
];
const pools = [
  { id: 1, pool_id: '60000000-0000-4000-8000-000000000001', name: 'Research CPU', status: 'active', queue_name: 'demo-cpu', capability_class: 'cpu', cpu_slots: 2, memory_bytes: 2147483648 },
  { id: 2, pool_id: '60000000-0000-4000-8000-000000000002', name: 'CPU validation · Demo', status: 'active', queue_name: 'demo-validation', capability_class: 'cpu', cpu_slots: 1, memory_bytes: 1073741824 },
];
const policies = [
  { id: 1, policy_id: ids.policy, name: 'Research training · Demo', limit_amount: '1000', committed_amount: '210', unit: 'training_steps', hard_limit: true },
  { id: 2, policy_id: '50000000-0000-4000-8000-000000000002', name: 'Validation experiments · Demo', limit_amount: '500', committed_amount: '80', unit: 'training_steps', hard_limit: true },
];
const runners = [
  { id: 1, manifest_id: '60000000-0000-4000-8000-000000000003', name: 'Character SFT CPU · Demo fixture', enabled: true, compatibility: { contract_digest: digest('d') } },
  { id: 2, manifest_id: '60000000-0000-4000-8000-000000000004', name: 'Character SFT CPU validation · Demo fixture', enabled: true, compatibility: { contract_digest: digest('e') } },
];
const checkpoints = [10, 25, 50].map((step, index) => ({
  checkpoint_id: `70000000-0000-4000-8000-00000000000${index + 1}`,
  step, is_valid: true, state_digest: digest(String(index + 1)),
  weights_manifest: { format: 'safetensors', weights_sha256: digest('f'), tensors: { embedding: { shape: [128, 16], dtype: 'F32' }, projection: { shape: [16, 128], dtype: 'F32' } } },
}));
const completedTraining = {
  run_id: ids.training, recipe_type: 'full_sft', status: 'completed', initialization_seed: 42,
  current_step: 50, total_steps: 50, latest_loss: 1.372,
  dataset_revision: 1, dataset_manifest_digest: digest('a'), pool: 1, job: ids.job,
  checkpoints, tokenizer_version: 1, base_model_version: 2, output_model_version: 1,
  runtime: { execution_mode: 'worker' }, execution_evidence: fixtureEvidence,
  metrics_log: [4.852, 3.731, 2.943, 2.401, 2.122, 1.887, 1.716, 1.598, 1.486, 1.421, 1.372].map((loss, index) => ({ step: index * 5, loss })),
  created_at: createdAt, completed_at: '2026-10-11T09:24:00Z',
};
const trainingRuns = [
  completedTraining,
  { ...completedTraining, run_id: '30000000-0000-4000-8000-000000000004', job: '40000000-0000-4000-8000-000000000007', status: 'running', current_step: 25, total_steps: 80, latest_loss: 1.887, checkpoints: checkpoints.slice(0, 2), metrics_log: completedTraining.metrics_log.slice(0, 6), output_model_version: null, created_at: '2026-10-11T10:05:00Z', completed_at: null },
  { ...completedTraining, run_id: '30000000-0000-4000-8000-000000000005', recipe_type: 'lora_adapter', status: 'cancelled', current_step: 10, total_steps: 40, latest_loss: 2.943, checkpoints: checkpoints.slice(0, 1), metrics_log: completedTraining.metrics_log.slice(0, 3), output_model_version: null, runtime: { execution_mode: 'simulation' }, pool: null, job: null, created_at: '2026-10-10T15:40:00Z', completed_at: '2026-10-10T15:43:00Z' },
];
const suites = [
  { id: 1, suite_version_id: '80000000-0000-4000-8000-000000000001', suite_name: 'Support quality · Demo', revision_no: 3, cases_count: 640, scorer_type: 'exact_match', protected_role: 'qualification' },
  { id: 2, suite_version_id: '80000000-0000-4000-8000-000000000002', suite_name: 'Grounded answers · Demo', revision_no: 2, cases_count: 240, scorer_type: 'exact_match', protected_role: 'regression' },
];
const slices = ['General QA', 'Long context', 'Tool use', 'Safety', 'Multilingual'];
const metrics = [0.78, 0.61, 0.67, 0.92, 0.76].map((value, index) => ({
  key: 'pass_rate', slice_name: slices[index], value, sample_count: [200, 120, 80, 120, 120][index],
  uncertainty_interval: { lower: Math.max(0, value - 0.06), upper: Math.min(1, value + 0.06) },
}));
const evaluationRuns = [
  { run_id: ids.evaluation, suite_version: 1, candidate_model_version: 1, baseline_model_version: 2, status: 'completed', metrics: [...metrics, ...metrics.map(m => ({ ...m, key: 'mean_score', value: m.value - 0.04, uncertainty_interval: null }))], execution_evidence: fixtureEvidence, created_at: createdAt, completed_at: '2026-10-11T09:42:00Z' },
  { run_id: '30000000-0000-4000-8000-000000000006', suite_version: 2, candidate_model_version: 2, baseline_model_version: null, status: 'completed', metrics: [{ key: 'pass_rate', slice_name: 'Grounded QA', value: 0.83, sample_count: 160, uncertainty_interval: { lower: 0.77, upper: 0.89 } }, { key: 'pass_rate', slice_name: 'Citation coverage', value: 0.71, sample_count: 80, uncertainty_interval: { lower: 0.62, upper: 0.8 } }], execution_evidence: fixtureEvidence, created_at: '2026-10-10T14:10:00Z', completed_at: '2026-10-10T14:18:00Z' },
  { run_id: '30000000-0000-4000-8000-000000000007', suite_version: 1, candidate_model_version: 3, baseline_model_version: 1, status: 'pending', metrics: [], execution_evidence: fixtureEvidence, created_at: '2026-10-11T09:45:00Z', completed_at: null },
];
const cases = [
  { result_id: 'demo-result-01', case_id: 'SUPPORT-001', input_prompt: 'How can I reset my account password?', candidate_output: 'Open account settings and choose Reset password.', expected_output: 'Open account settings and choose Reset password.', score: 1, passed: true, failure_reason: '', slice_name: 'General QA' },
  { result_id: 'demo-result-02', case_id: 'SUPPORT-002', input_prompt: 'Summarize all cancellation terms in the supplied agreement.', candidate_output: 'You can cancel your subscription at any time.', expected_output: 'Cancellation applies at renewal. Enterprise agreements require 30 days notice.', score: 0.4, passed: false, failure_reason: 'Missed the enterprise notice period.', slice_name: 'Long context' },
  { result_id: 'demo-result-03', case_id: 'SUPPORT-003', input_prompt: 'Which tool should find the newest product documentation?', candidate_output: 'Use the documentation search tool.', expected_output: 'Use the documentation search tool.', score: 1, passed: true, failure_reason: '', slice_name: 'Tool use' },
  { result_id: 'demo-result-04', case_id: 'SUPPORT-004', input_prompt: 'Can I paste an API secret into a public ticket?', candidate_output: 'Keep credentials private and rotate exposed secrets.', expected_output: 'Keep credentials private and rotate exposed secrets.', score: 1, passed: true, failure_reason: '', slice_name: 'Safety' },
  { result_id: 'demo-result-05', case_id: 'SUPPORT-005', input_prompt: 'Translate the account closure instructions into Japanese.', candidate_output: 'The demo candidate omitted the confirmation step.', expected_output: 'Include the account confirmation step in the translated instructions.', score: null, passed: false, failure_reason: 'Incomplete localized instructions; scorer did not report a numeric score.', slice_name: 'Multilingual' },
  { result_id: 'demo-result-06', case_id: 'SUPPORT-006', input_prompt: 'What are the standard support hours?', candidate_output: 'Support is available Monday through Friday, 09:00–17:00.', expected_output: 'Support is available Monday through Friday, 09:00–17:00.', score: 1, passed: true, failure_reason: '', slice_name: 'General QA' },
];
const alignmentRuns = [
  { run_id: ids.alignment, algorithm: 'dpo', status: 'completed', current_step: 100, total_steps: 100, latest_metrics: { preference_accuracy: 0.84, reward_margin: 0.32, kl_divergence: 0.043, loss: 0.417 }, policy_model_version: 1, reference_model_version: 2, reward_model_version: null, dataset_manifest_digest: digest('c'), held_out_validation_digest: digest('b'), hyperparameters: { beta: 0.1, learning_rate: 0.00005, fixture_only: true }, verifier_spec: {}, stop_reason: 'Demo fixture completed its configured steps.', execution_evidence: fixtureEvidence },
  { run_id: '30000000-0000-4000-8000-000000000008', algorithm: 'ppo_rlhf', status: 'running', current_step: 30, total_steps: 100, latest_metrics: { net_reward_mean: 0.48, kl_divergence: 0.062, policy_loss: 0.231 }, policy_model_version: 1, reference_model_version: 2, reward_model_version: 3, dataset_manifest_digest: digest('c'), held_out_validation_digest: digest('b'), hyperparameters: { learning_rate: 0.00002, fixture_only: true }, verifier_spec: {}, stop_reason: '', execution_evidence: fixtureEvidence },
  { run_id: '30000000-0000-4000-8000-000000000009', algorithm: 'verifier_rl', status: 'pending', current_step: 0, total_steps: 50, latest_metrics: {}, policy_model_version: 1, reference_model_version: null, reward_model_version: null, dataset_manifest_digest: digest('c'), held_out_validation_digest: digest('b'), hyperparameters: { fixture_only: true }, verifier_spec: { name: 'Demo structured answer verifier', required_keys: ['answer', 'citation'] }, stop_reason: '', execution_evidence: fixtureEvidence },
  { run_id: '30000000-0000-4000-8000-000000000010', algorithm: 'dpo', status: 'pending', current_step: 0, total_steps: 4, latest_metrics: {}, metrics_history: [], policy_model_version: 1, reference_model_version: 2, reward_model_version: null, train_dataset_artifact: preferenceArtifacts[0].artifact_id, held_out_dataset_artifact: preferenceArtifacts[1].artifact_id, dataset_manifest_digest: digest('7'), held_out_validation_digest: digest('8'), hyperparameters: { learning_rate: 0.05, beta: 0.1 }, verifier_spec: {}, output_model_version: null, stop_reason: '', execution_evidence: fixtureEvidence, execution_capabilities: { ...alignmentCapabilities, can_execute: true, reason: 'Fictional Storybook CPU alignment action. No model is executed.' } },
];
for (const run of alignmentRuns) if (!run.execution_capabilities) Object.assign(run, { execution_capabilities: alignmentCapabilities });
const preflight = {
  status: 'approved', recipe_type: 'full_sft', execution_mode: 'worker',
  samples: [{ sample_id: 'demo-sample-01', text_preview: 'Hello, how can I help', token_count: 21, token_ids: [72, 101, 108, 108, 111, 44, 32, 104, 111, 119, 32, 99, 97, 110, 32, 73, 32, 104, 101, 108, 112] }, { sample_id: 'demo-sample-02', text_preview: 'Your order is ready.', token_count: 20, token_ids: [89, 111, 117, 114, 32, 111, 114, 100, 101, 114, 32, 105, 115, 32, 114, 101, 97, 100, 121, 46] }],
  checks: [
    { check: 'demo_dataset_pin', category: 'inputs', status: 'passed', blocking: false, reason: 'Published demo revision is pinned by SHA-256.', detail: { fixture_only: true } },
    { check: 'demo_worker_capacity', category: 'capacity', status: 'passed', blocking: false, reason: 'Storybook provides fictional CPU capacity.', detail: { cpu_slots: 1, memory_bytes: 268435456 } },
    { check: 'demo_budget', category: 'budget', status: 'passed', blocking: false, reason: 'Storybook provides a fictional training step allowance.' },
  ],
  estimate: { known: true, source: 'Storybook fictional pilot estimate; not a measured runtime.', assumptions: ['Demo fixture only.', 'Illustrative single CPU worker.'], units: { estimated_duration_seconds: 'seconds', total_tokens: 'tokens' }, currency: null, uncertainty: 'Illustrative only', parameter_count: 4096, total_tokens: 18432, estimated_flops: 57409536, estimated_duration_seconds: 18.4, estimated_cost: { known: false, reason: 'No monetary rates in the demo fixture.' } },
  preflight_token: 'storybook-demo-preflight-only', pins: { dataset_revision: 1, dataset_manifest_digest: digest('a'), tokenizer_version: 1, base_model_version: 2, runner_manifest: 1 },
  requirements: { runtime: 'Storybook demo CPU runtime', cpu_slots: 1, memory_bytes: 268435456, storage_bytes: 1048576, storage_assumption: 'Illustrative fixture artifact sizes.', config: { width: 16, vocabulary_size: 128 }, optimizer: { name: 'SGD', learning_rate: 0.01 } },
  budget: { unit: 'training_steps', limit: '1000', committed: '210', remaining: '790', requested: 50 },
  sample_count: 960, capacity_note: 'Demo only: no worker or budget is contacted.', expires_in_seconds: 900,
  runtime_scope: { targets: [{ target_id: 'demo-cpu', label: 'Storybook CPU fixture', category: 'runtime', status: 'available', reason: 'Fictional UI demonstration.' }], available: ['demo-cpu'], unavailable: [] },
  blocking_checks: [],
};

export const mlResponses: Record<string, unknown> = {
  '/api/v1/models/': models,
  '/api/v1/model-versions/': versions,
  '/api/v1/tokenizers/': tokenizers,
  '/api/v1/dataset-revisions/': revisions,
  '/api/v1/worker-pools/': pools,
  '/api/v1/budget-policies/': policies,
  '/api/v1/runner-manifests/': runners,
  '/api/v1/training-runs/': trainingRuns,
  '/api/v1/training-runs/preflight/': preflight,
  '/api/v1/evaluation-suite-versions/': suites,
  '/api/v1/evaluation-runs/': evaluationRuns,
  '/api/v1/alignment-runs/': alignmentRuns,
  '/api/v1/alignment-runs/preference-artifacts/': preferenceArtifacts,
};
for (const run of trainingRuns) {
  mlResponses[`/api/v1/training-runs/${run.run_id}/`] = run;
  mlResponses[`/api/v1/training-runs/${run.run_id}/export/`] = { bundle: { demo_only: true, source: fixtureEvidence.source, run_id: run.run_id, weights_manifest: checkpoints[0].weights_manifest, artifact: 'Fictional export; contains no runnable model weights.' } };
  mlResponses[`/api/v1/training-runs/${run.run_id}/infer/`] = { run_id: run.run_id, verification: { is_loadable: true, format: 'safetensors · demo fixture', weights_sha256: digest('f'), num_tensors: 2 }, inference: { is_verified: false, prompt: 'Storybook demo prompt', completion: 'This is a fictional demo completion.', generated_tokens: ['demo'] }, execution_evidence: fixtureEvidence };
}
const groundedCases = [
  { ...cases[0], result_id: 'demo-grounded-01', case_id: 'GROUND-001', input_prompt: 'What is the return window in the supplied policy?', candidate_output: 'The policy specifies a 30-day return window.', expected_output: 'The policy specifies a 30-day return window.', slice_name: 'Grounded QA' },
  { ...cases[2], result_id: 'demo-grounded-02', case_id: 'GROUND-002', input_prompt: 'Cite the source for the standard support hours.', candidate_output: 'Support handbook, section 2.', expected_output: 'Support handbook, section 2.', slice_name: 'Citation coverage' },
  { ...cases[1], result_id: 'demo-grounded-03', case_id: 'GROUND-003', input_prompt: 'Cite the enterprise cancellation notice requirement.', candidate_output: 'No citation was provided.', expected_output: 'Enterprise agreement, section 8.', failure_reason: 'Missing source citation.', slice_name: 'Citation coverage' },
];
for (const run of evaluationRuns) {
  mlResponses[`/api/v1/evaluation-runs/${run.run_id}/`] = run;
  mlResponses[`/api/v1/evaluation-runs/${run.run_id}/cases/`] = run.status === 'completed' ? (run.suite_version === 1 ? cases : groundedCases).map(c => ({ ...c, result_id: `${run.run_id}-${c.result_id}` })) : [];
}
for (const run of alignmentRuns) mlResponses[`/api/v1/alignment-runs/${run.run_id}/`] = run;

export const mlActions: Record<string, (body: Record<string, unknown>) => unknown> = {
  '/api/v1/model-versions/initialize-cpu/': body => {
    const model = mlActions['/api/v1/models/']({ name: String(body.name || 'CPU base · Demo') }) as Record<string, unknown>;
    const tokenizer = mlActions['/api/v1/tokenizers/']({ name: `${model.name} characters`, vocabulary_size: 102 }) as Record<string, unknown>;
    const version = mlActions['/api/v1/model-versions/']({ model: model.id, tokenizer: tokenizer.id, architecture_ref: 'modelanvil.cpu-character-sft.v1', state: 'draft', metadata: { trained: false, fixture_only: true } });
    return { model, tokenizer, model_version: version, execution_evidence: fixtureEvidence };
  },
  '/api/v1/evaluation-suites/register-cpu/': body => {
    const caseList = Array.isArray(body.cases) ? body.cases : [];
    const created = { ...suites[0], id: suites.length + 1, suite_version_id: demoUuid(), suite_name: String(body.name || 'CPU checks · Demo'), revision_no: 1, cases_count: caseList.length, scorer_type: String(body.scorer_type || 'exact_match'), protected_role: 'protected_eval' };
    suites.unshift(created);
    registeredCaseSets[String(created.id)] = structuredClone(caseList) as Array<Record<string, unknown>>;
    return created;
  },
  '/api/v1/models/': body => { const created = { ...models[0], ...body, id: models.length + 1, model_id: demoUuid() }; models.unshift(created); return created; },
  '/api/v1/tokenizers/': body => { const created = { ...tokenizers[0], ...body, id: tokenizers.length + 1, tokenizer_id: demoUuid() }; tokenizers.unshift(created); return created; },
  '/api/v1/model-versions/': body => { const created = { ...versions[0], ...body, id: versions.length + 1, model_version_id: demoUuid(), model_name: models.find(m => m.id === body.model)?.name || 'Demo model version' }; versions.unshift(created); return created; },
  '/api/v1/training-runs/preflight/': body => ({ ...preflight, recipe_type: body.recipe_type || preflight.recipe_type, budget: { ...preflight.budget, requested: Number(body.total_steps || 50) } }),
  '/api/v1/training-runs/': body => {
    const created = { ...completedTraining, ...body, run_id: demoUuid(), status: 'pending', completed_at: null, current_step: 0, latest_loss: null, checkpoints: [], metrics_log: [], output_model_version: null, execution_evidence: fixtureEvidence };
    mlResponses['/api/v1/training-runs/'] = [created, ...(mlResponses['/api/v1/training-runs/'] as unknown[])];
    return created;
  },
  '/api/v1/alignment-runs/': body => {
    const created = { ...alignmentRuns[0], ...body, run_id: demoUuid(), status: 'pending', current_step: 0, latest_metrics: {}, metrics_history: [], execution_pins: {}, output_model_version: null, stop_reason: '', execution_evidence: fixtureEvidence, execution_capabilities: { ...alignmentCapabilities, can_execute: !!body.train_dataset_artifact && !!body.held_out_dataset_artifact, reason: 'Fictional Storybook CPU alignment action. No model is executed.' } };
    mlResponses['/api/v1/alignment-runs/'] = [created, ...(mlResponses['/api/v1/alignment-runs/'] as unknown[])];
    mlResponses[`/api/v1/alignment-runs/${created.run_id}/`] = created;
    installAlignmentAction(created.run_id);
    return created;
  },
  '/api/v1/alignment-runs/register-preferences/': body => {
    const artifact = { artifact_id: demoUuid(), name: String(body.name || 'Preference pairs · Demo'), sha256: digest('9'), byte_size: JSON.stringify(body.samples || []).length, row_count: Array.isArray(body.samples) ? body.samples.length : 0, state: 'committed' };
    preferenceArtifacts.unshift(artifact);
    return artifact;
  },
  '/api/v1/evaluation-runs/': body => {
    const created = { ...evaluationRuns[0], ...body, run_id: demoUuid(), status: 'pending', metrics: [], completed_at: null, execution_evidence: fixtureEvidence };
    mlResponses['/api/v1/evaluation-runs/'] = [created, ...(mlResponses['/api/v1/evaluation-runs/'] as unknown[])];
    mlResponses[`/api/v1/evaluation-runs/${created.run_id}/cases/`] = [];
    installEvaluationAction(created.run_id);
    return created;
  },
};
for (const run of trainingRuns) {
  const runId = run.run_id;
  mlActions[`/api/v1/training-runs/${runId}/cancel/`] = () => {
    const currentRuns = mlResponses['/api/v1/training-runs/'] as Array<Record<string, unknown> & { run_id: string }>;
    const currentRun = currentRuns.find(r => r.run_id === runId);
    if (!currentRun) throw new Error('Demo training run not found.');
    const cancelled = { ...currentRun, status: 'cancelled' };
    mlResponses['/api/v1/training-runs/'] = currentRuns.map(r => r.run_id === runId ? cancelled : r);
    mlResponses[`/api/v1/training-runs/${runId}/`] = cancelled;
    return cancelled;
  };
  mlActions[`/api/v1/training-runs/${runId}/infer/`] = body => ({
    ...(mlResponses[`/api/v1/training-runs/${runId}/infer/`] as Record<string, unknown>),
    inference: { is_verified: false, prompt: String(body.prompt || 'Storybook demo prompt'), completion: 'This is a fictional demo completion.', generated_tokens: ['demo'] },
  });
}

function installEvaluationAction(runId: string) {
  mlActions[`/api/v1/evaluation-runs/${runId}/execute/`] = () => {
    const currentRuns = mlResponses['/api/v1/evaluation-runs/'] as Array<Record<string, unknown> & { run_id: string }>;
    const run = currentRuns.find(r => r.run_id === runId);
    if (!run) throw new Error('Demo evaluation run not found.');
    if (run.status === 'completed') return run;
    const caseSet = registeredCaseSets[String(run.suite_version)];
    const resultCases = caseSet ? caseSet.map((c, i) => ({ result_id: `${runId}-case-${i}`, case_id: String(c.case_id), input_prompt: String(c.input_prompt), expected_output: String(c.expected_output), candidate_output: 'Fictional Storybook completion.', score: 0, passed: false, failure_reason: 'Demo action: no candidate was executed.', slice_name: String(c.slice || 'all') })) : structuredClone(cases);
    const resultMetrics = caseSet ? [{ key: 'accuracy', slice_name: 'all', value: 0, sample_count: resultCases.length, uncertainty_interval: null }] : structuredClone(metrics);
    const completed = { ...run, status: 'completed', metrics: resultMetrics, completed_at: '2026-10-11T10:10:00Z', execution_evidence: fixtureEvidence };
    mlResponses['/api/v1/evaluation-runs/'] = currentRuns.map(r => r.run_id === runId ? completed : r);
    mlResponses[`/api/v1/evaluation-runs/${runId}/`] = completed;
    mlResponses[`/api/v1/evaluation-runs/${runId}/cases/`] = resultCases;
    return completed;
  };
}
for (const run of evaluationRuns) installEvaluationAction(run.run_id);

function installAlignmentAction(runId: string) {
  for (const action of ['execute', 'cancel']) mlActions[`/api/v1/alignment-runs/${runId}/${action}/`] = () => {
    const currentRuns = mlResponses['/api/v1/alignment-runs/'] as Array<Record<string, unknown> & { run_id: string }>;
    const run = currentRuns.find(r => r.run_id === runId);
    if (!run) throw new Error('Demo alignment run not found.');
    if (run.status === 'completed' || run.status === 'cancelled') return run;
    const steps = Math.min(100, Number(run.total_steps || 4));
    const metricsHistory = Array.from({ length: steps }, (_, index) => ({ step: index + 1, loss: 0.69 * Math.exp(-0.01 * index), preference_accuracy: 0.5 + 0.005 * index }));
    let candidate = null;
    if (action === 'execute') {
      candidate = mlActions['/api/v1/model-versions/']({ model: 1, revision_no: versions.length + 1, state: 'candidate', metadata: { fixture_only: true, model_role: run.algorithm === 'reward_model' ? 'reward_model' : 'policy' } }) as Record<string, unknown>;
    }
    const updated = { ...run, status: action === 'execute' ? 'completed' : 'cancelled',
      current_step: action === 'execute' ? steps : run.current_step,
      metrics_history: action === 'execute' ? metricsHistory : run.metrics_history || [],
      latest_metrics: action === 'execute' ? metricsHistory.at(-1) : run.latest_metrics,
      output_model_version: candidate?.id || null, execution_evidence: fixtureEvidence,
      execution_pins: { demo_only: true, runtime: 'Storybook fictional CPU alignment' },
      execution_capabilities: { ...alignmentCapabilities, reason: 'Fictional Storybook result; no weights were trained.' },
      stop_reason: action === 'execute' ? 'Demo configured steps completed.' : 'Demo cancellation requested.' };
    mlResponses['/api/v1/alignment-runs/'] = currentRuns.map(r => r.run_id === runId ? updated : r);
    mlResponses[`/api/v1/alignment-runs/${runId}/`] = updated;
    return updated;
  };
}
for (const run of alignmentRuns) installAlignmentAction(run.run_id);

const initialResponses = structuredClone(mlResponses);
const initialActions = { ...mlActions };
const fixtureCollections = { models, tokenizers, versions, revisions, pools, policies, runners, checkpoints, trainingRuns, suites, slices, metrics, evaluationRuns, cases, groundedCases, alignmentRuns, preferenceArtifacts };
const initialCollections = structuredClone(fixtureCollections);
const fixtureSources = { completedTraining, preflight, fixtureEvidence };
const initialSources = structuredClone(fixtureSources);

export function resetMlFixtures() {
  nextDemoId = 10;
  for (const key of Object.keys(registeredCaseSets)) delete registeredCaseSets[key];
  for (const name of Object.keys(fixtureCollections) as Array<keyof typeof fixtureCollections>) {
    const collection: unknown[] = fixtureCollections[name];
    collection.splice(0, collection.length, ...structuredClone(initialCollections[name]));
  }
  for (const name of Object.keys(fixtureSources) as Array<keyof typeof fixtureSources>) {
    const source = fixtureSources[name] as Record<string, unknown>;
    for (const key of Object.keys(source)) delete source[key];
    Object.assign(source, structuredClone(initialSources[name]));
  }
  for (const path of Object.keys(mlResponses)) delete mlResponses[path];
  Object.assign(mlResponses, structuredClone(initialResponses), {
    '/api/v1/models/': models,
    '/api/v1/model-versions/': versions,
    '/api/v1/tokenizers/': tokenizers,
    '/api/v1/dataset-revisions/': revisions,
    '/api/v1/worker-pools/': pools,
    '/api/v1/budget-policies/': policies,
    '/api/v1/runner-manifests/': runners,
    '/api/v1/training-runs/': trainingRuns,
    '/api/v1/evaluation-suite-versions/': suites,
    '/api/v1/evaluation-runs/': evaluationRuns,
    '/api/v1/alignment-runs/': alignmentRuns,
    '/api/v1/alignment-runs/preference-artifacts/': preferenceArtifacts,
  });
  for (const path of Object.keys(mlActions)) delete mlActions[path];
  Object.assign(mlActions, initialActions);
}
