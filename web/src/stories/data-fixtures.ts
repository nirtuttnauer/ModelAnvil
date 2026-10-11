// Storybook-only demo evidence. These fixtures are never used by the application API client.
const stamp = '2026-10-11T08:30:00Z';
const id = (n: number) => `60000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const digest = (letter: string) => letter.repeat(64);
const datasetId = '20000000-0000-4000-8000-000000000001';
const revisionId = '20000000-0000-4000-8000-000000000002';
const secondDatasetId = '20000000-0000-4000-8000-000000000003';
const secondRevisionId = '20000000-0000-4000-8000-000000000004';
const modelVersionId = '10000000-0000-4000-8000-000000000002';
const policyId = '50000000-0000-4000-8000-000000000001';
const campaignId = id(1), secondCampaignId = id(2), batchId = id(10);
const rows = [
  { dataset_id: datasetId, name: 'Assistant instruction corpus', description: 'A versioned collection of grounded instruction conversations.', current_revision: 1, metadata: { source: 'demo-text', purpose: 'instruction_finetuning' }, created_at: '2026-10-08T09:00:00Z', updated_at: stamp },
  { dataset_id: secondDatasetId, name: 'Lucide SVG instructions', description: 'Vector generation prompts paired with canonical SVG responses.', current_revision: 2, metadata: { source: 'demo-lucide', modality: 'svg' }, created_at: '2026-10-06T09:00:00Z', updated_at: stamp },
];
const revisions = [
  { revision_id: revisionId, dataset: 1, revision_no: 1, schema_version: '1.0', manifest_digest: digest('a'), manifest_artifact: 11, recipe_digest: digest('b'), source_snapshots: [id(40)], row_count: 1200, state: 'published', published_at: stamp, metadata: { preparation_kind: 'bounded_local_jsonl_v1', input_artifact_id: id(70), input_sha256: digest('c'), recipe: { algorithm: 'source_group_sha256_v1', seed: '42', validation_percent: 10, test_percent: 10 }, source_group_count: 400, split_counts: { train: 960, validation: 120, test: 120 }, drop_report: { input_rows: 1256, kept: 1200, dropped: 56, drop_reason_counts: { 'duplicate.exact': 32, 'quality.short': 16, 'pii.email': 8 } } } },
  { revision_id: secondRevisionId, dataset: 2, revision_no: 2, schema_version: '1.0', manifest_digest: digest('d'), manifest_artifact: 12, recipe_digest: digest('e'), source_snapshots: [id(41)], row_count: 480, state: 'published', published_at: '2026-10-10T14:20:00Z', metadata: { preparation_kind: 'bounded_local_jsonl_v1', input_artifact_id: id(71), input_sha256: digest('f'), recipe: { algorithm: 'source_group_sha256_v1', seed: 'svg-42', validation_percent: 10, test_percent: 10 }, source_group_count: 240, split_counts: { train: 384, validation: 48, test: 48 } } },
  { revision_id: '20000000-0000-4000-8000-000000000005', dataset: 2, revision_no: 3, schema_version: '1.0', manifest_digest: '', manifest_artifact: null, recipe_digest: '', source_snapshots: [], row_count: null, state: 'draft', published_at: null, metadata: { notes: 'Awaiting source verification.' } },
];
const sources = [
  { id: 'demo-lucide', name: 'Lucide vector instructions', category: 'vector_graphics', source_kind: 'repository', description: 'Clean SVG icons paired with instruction prompts and verified source attribution.', source_url: 'https://example.org/demo/lucide', modalities: ['svg', 'code'], use_cases: ['instruction_finetuning', 'vector_generation'], license: 'ISC AND MIT', eligibility: 'eligible', download_enabled: true, size_bytes: 1854000, is_size_measured: true, acquisition_status: 'qualified', acquisition_available: true, acquisition_blocked_reason: '', pinned_revision: 'a'.repeat(40) },
  { id: 'demo-text', name: 'Grounded assistant conversations', category: 'conversations', source_kind: 'repository', description: 'Source-grounded question and answer pairs for a concise, helpful research assistant.', source_url: 'https://example.org/demo/assistant-corpus', modalities: ['text'], use_cases: ['instruction_finetuning', 'annotation_review'], license: 'Apache-2.0', eligibility: 'eligible', download_enabled: true, size_bytes: 4250000, is_size_measured: true, acquisition_status: 'qualified', acquisition_available: true, acquisition_blocked_reason: '', pinned_revision: 'b'.repeat(40) },
  { id: 'demo-audio', name: 'Speech transcript archive', category: 'speech', source_kind: 'archive', description: 'Candidate transcript collection awaiting connector and digest qualification.', source_url: 'https://example.org/demo/speech', modalities: ['audio', 'text'], use_cases: ['speech_transcription'], license: 'CC-BY-4.0', eligibility: 'eligible', download_enabled: true, size_bytes: null, is_size_measured: false, acquisition_status: 'unqualified', acquisition_available: false, acquisition_blocked_reason: 'No acquisition connector has been qualified for this source.', pinned_revision: '' },
];
function transfer(sourceId: string, state = 'ready') {
  const svg = sourceId === 'demo-lucide';
  return { snapshot_id: svg ? id(41) : id(40), source_id: sourceId, source_revision: (svg ? 'a' : 'b').repeat(40), state, connector: 'demo_repository', record_selection: 'bounded_records', planned_records: svg ? 480 : 1200, verified_records: state === 'ready' ? (svg ? 480 : 1200) : 120, remaining_records: state === 'ready' ? 0 : (svg ? 360 : 1080), planned_bytes: svg ? 1854000 : 4250000, transferred_bytes: state === 'ready' ? (svg ? 1854000 : 4250000) : 425000, progress: state === 'ready' ? 1 : 0.1, manifest_digest: state === 'ready' ? digest(svg ? 'd' : 'a') : '', failures: [], job: { job_id: '40000000-0000-4000-8000-000000000001', status: state === 'ready' ? 'succeeded' : state === 'cancelled' ? 'cancelled' : 'running', desired_action: state === 'cancelled' ? 'cancel' : 'run', attempt_count: 1, pool: 'dataset-acquisition' }, budget_reservation: { reservation_id: id(72), state: state === 'ready' ? 'settled' : 'reserved', unit: 'bank_acquisition_records', estimated_amount: '1200', settled_amount: state === 'ready' ? (svg ? '480' : '1200') : null }, dataset_id: svg ? secondDatasetId : datasetId, revision_id: state === 'ready' ? (svg ? secondRevisionId : revisionId) : null, revision_no: state === 'ready' ? (svg ? 2 : 1) : null, manifest_artifact_id: state === 'ready' ? id(svg ? 71 : 70) : null, row_count: state === 'ready' ? (svg ? 480 : 1200) : null, recipe_digest: state === 'ready' ? digest(svg ? 'e' : 'b') : null, rejection_report: null, updated_at: stamp };
}
const snapshots = [
  { snapshot_id: id(20), cycle_no: 1, item_count: 162, manifest_digest: digest('a'), created_at: '2026-10-08T09:00:00Z' },
  { snapshot_id: id(21), cycle_no: 2, item_count: 373, manifest_digest: digest('b'), created_at: '2026-10-10T09:00:00Z' },
];
const batches = [
  { batch_id: id(11), cycle_no: 1, status: 'closed', sample_count: 180, reviewed_count: 180, approved_count: 162, snapshot_manifest_digest: digest('a'), drafting_model_id: modelVersionId, created_at: '2026-10-08T08:00:00Z' },
  { batch_id: id(12), cycle_no: 2, status: 'closed', sample_count: 240, reviewed_count: 240, approved_count: 211, snapshot_manifest_digest: digest('b'), drafting_model_id: modelVersionId, created_at: '2026-10-09T08:00:00Z' },
  { batch_id: batchId, cycle_no: 3, status: 'reviewing', sample_count: 3, reviewed_count: 2, approved_count: 2, snapshot_manifest_digest: '', drafting_model_id: modelVersionId, created_at: stamp },
];
const campaign = { campaign_id: campaignId, name: 'Assistant helpfulness review', status: 'active', seed_mode: 'existing_model', current_cycle: 2, max_cycles: 6, budget_limit_dollars: 250, accumulated_cost_dollars: 0, held_out_audit_digest: digest('c'), active_model_id: modelVersionId, label_schema: { schema_id: id(30), name: 'Response helpfulness', kind: 'classification', classes: ['Helpful', 'Needs correction', 'Off topic'], specification: {} }, rubric: { rubric_id: id(31), name: 'Grounded assistant rubric', revision_no: 2, guidelines_text: 'Helpful: answers the question directly with clear, source-grounded guidance.\nNeeds correction: contains an unsupported claim, an incomplete step, or unclear wording.\nOff topic: does not address the user’s request.\nEvaluate the source before accepting the imported model draft.', criteria: {} }, configuration: { audit_sample_refs: ['held-out-001'] }, batches, snapshots, created_at: '2026-10-08T08:00:00Z' };
const campaigns = [campaign, { ...campaign, campaign_id: secondCampaignId, name: 'SVG instruction consistency', status: 'paused', seed_mode: 'manual', active_model_id: null, current_cycle: 0, label_schema: { ...campaign.label_schema, schema_id: id(32), name: 'SVG validity', classes: ['Valid', 'Invalid'] }, batches: [], snapshots: [], rubric: { ...campaign.rubric, rubric_id: id(33), guidelines_text: 'Check that the response is valid SVG and matches the requested shape.' } }];
const previousReview = (n: number, decision: string, label: string) => ({ record_id: id(n), revision_no: 1, reviewer_id: 'demo-reviewer', original_prediction: { predicted_label: 'Helpful', model_version_id: modelVersionId }, human_label: { label }, decision, preference_choice: '', created_at: stamp });
const tasks = [
  { task_id: id(101), sample_ref: 'assistant-0421', status: 'pending', content: { user: 'How do I choose a validation split without leaking related examples?', assistant: 'Keep examples from the same source group together, then assign groups deterministically. Inspect the recorded split counts before training.', source: 'Dataset preparation guide · section 3.2', draft_prediction: { predicted_label: 'Helpful', model_version_id: modelVersionId } }, latest_review: null as ReturnType<typeof previousReview> | null },
  { task_id: id(102), sample_ref: 'assistant-0422', status: 'reviewed', content: { user: 'Can I compare two model revisions using training loss alone?', assistant: 'Training loss is enough to choose the better production model.', source: 'Evaluation guide · held-out qualification', draft_prediction: { predicted_label: 'Helpful', model_version_id: modelVersionId } }, latest_review: previousReview(112, 'corrected', 'Needs correction') },
  { task_id: id(103), sample_ref: 'assistant-0423', status: 'reviewed', content: { user: 'What happens when a run is cancelled?', assistant: 'Cancellation is a requested action. Wait for the worker to acknowledge it and finalize its resources before treating the run as terminal.', source: 'Worker lifecycle guide · cancellation', draft_prediction: { predicted_label: 'Helpful', model_version_id: modelVersionId } }, latest_review: previousReview(113, 'accepted_without_edit', 'Helpful') },
];
const knowledgeBases = [
  { knowledge_base_id: id(51), kb_id: id(51), name: 'Platform documentation', description: 'Dataset, training, and worker lifecycle reference material.', created_at: stamp, updated_at: stamp },
  { knowledge_base_id: id(52), kb_id: id(52), name: 'Research playbook', description: 'Evaluation protocols and annotation review guidelines.', created_at: stamp, updated_at: stamp },
];
const indexes = [
  { index_id: id(61), knowledge_base: 1, embedding_space: 1, revision_no: 6, status: 'ready', chunk_count: 384, created_at: stamp },
  { index_id: id(62), knowledge_base: 2, embedding_space: 1, revision_no: 2, status: 'ready', chunk_count: 128, created_at: stamp },
];
const chunks = [
  { chunk_id: id(201), text: 'Cancellation sets the job desired action to cancel. The running worker receives the request, stops execution, records terminal evidence, and releases its allocated slots. A request acknowledgement is distinct from terminal completion.', score: 0.86, metadata: { document_title: 'Worker cancellation lifecycle', span: '120:367', source_uri: 'docs/workers/cancellation.md', category: 'workers', revision: 6 } },
  { chunk_id: id(202), text: 'When preparing a dataset, source-group assignment prevents related examples from crossing train, validation, and test boundaries. Published metadata records actual split counts, source references, and manifest digests.', score: 0.74, metadata: { document_title: 'Dataset split integrity', span: '0:214', source_uri: 'docs/data/preparation.md', category: 'datasets', revision: 6 } },
  { chunk_id: id(203), text: 'Model qualification uses held-out evaluation metrics, sample counts, and uncertainty intervals. Review quality across slices before promoting a candidate. Training loss alone is not a release criterion.', score: 0.62, metadata: { document_title: 'Held-out model qualification', span: '45:237', source_uri: 'docs/evaluation/qualification.md', category: 'evaluation', revision: 6 } },
];

export const dataResponses: Record<string, unknown> = {
  '/api/v1/dataset-bank/sources/': { sources, count: sources.length, catalog_status: 'demo_qualified', catalog_checked_on: '2026-10-11', qualified_count: 2 },
  '/api/v1/datasets/': rows,
  '/api/v1/dataset-revisions/': revisions,
  [`/api/v1/datasets/${datasetId}/`]: rows[0],
  [`/api/v1/datasets/${secondDatasetId}/`]: rows[1],
  [`/api/v1/dataset-revisions/${revisionId}/`]: revisions[0],
  [`/api/v1/dataset-revisions/${secondRevisionId}/`]: revisions[1],
  [`/api/v1/dataset-bank/acquisitions/${id(40)}/`]: transfer('demo-text'),
  [`/api/v1/dataset-bank/acquisitions/${id(41)}/`]: transfer('demo-lucide'),
  '/api/v1/labeling-campaigns/': campaigns,
  [`/api/v1/labeling-campaigns/${campaignId}/`]: campaign,
  [`/api/v1/labeling-batches/${batchId}/tasks/`]: tasks,
  [`/api/v1/labeling-batches/${id(11)}/tasks/`]: [],
  [`/api/v1/labeling-batches/${id(12)}/tasks/`]: tasks.filter(task => task.latest_review),
  '/api/v1/knowledge-bases/': knowledgeBases,
  '/api/v1/index-versions/': indexes,
};

export const dataActions: Record<string, (body: Record<string, unknown>) => unknown> = {};
for (const source of sources) {
  dataResponses[`/api/v1/dataset-bank/sources/${source.id}/`] = source;
  if (!source.acquisition_available) continue;
  dataActions[`/api/v1/dataset-bank/sources/${source.id}/preflight/`] = () => ({ status: 'approved', source_id: source.id, source_name: source.name, tenant_id: 'demo-tenant', license: source.license, source_revision: source.pinned_revision, scope: { record_limit: source.id === 'demo-lucide' ? 480 : 1200 } });
  dataActions[`/api/v1/dataset-bank/sources/${source.id}/acquisitions/`] = body => ({ ...transfer(source.id, 'ingesting'), budget_reservation: { reservation_id: id(72), state: 'reserved', unit: 'bank_acquisition_records', policy_id: body.budget_policy_id || policyId, estimated_amount: String(body.estimated_amount || '1200'), settled_amount: null } });
  const snapshot = source.id === 'demo-lucide' ? id(41) : id(40);
  dataActions[`/api/v1/dataset-bank/acquisitions/${snapshot}/cancel/`] = () => {
    const value = transfer(source.id, 'cancelled'); dataResponses[`/api/v1/dataset-bank/acquisitions/${snapshot}/`] = value; return value;
  };
  dataActions[`/api/v1/dataset-bank/acquisitions/${snapshot}/resume/`] = body => {
    dataResponses[`/api/v1/dataset-bank/acquisitions/${snapshot}/`] = transfer(source.id);
    return { ...transfer(source.id, 'ingesting'), budget_reservation: { reservation_id: id(72), state: 'reserved', unit: 'bank_acquisition_records', policy_id: body.budget_policy_id || policyId, estimated_amount: String(body.estimated_amount || '1200'), settled_amount: null } };
  };
}
for (const task of tasks) {
  const historyPath = `/api/v1/annotation-tasks/${task.task_id}/history/`;
  dataResponses[historyPath] = task.latest_review ? [task.latest_review] : [];
  dataActions[`/api/v1/annotation-tasks/${task.task_id}/review/`] = body => {
    const review = { record_id: id(300 + tasks.indexOf(task) * 100 + Number(String(body.expected_revision || 1))), revision_no: Number(body.expected_revision || 1), reviewer_id: 'demo-reviewer', original_prediction: task.content.draft_prediction, human_label: (body.human_label || {}) as { label: string }, decision: String(body.decision || 'corrected'), preference_choice: '', created_at: stamp };
    const firstReview = !task.latest_review; task.latest_review = review; task.status = 'reviewed';
    if (firstReview) batches[2].reviewed_count += 1;
    dataResponses[historyPath] = [review, ...(dataResponses[historyPath] as unknown[])];
    return { ...task };
  };
}
for (const item of campaigns) dataActions[`/api/v1/labeling-campaigns/${item.campaign_id}/lifecycle/`] = body => {
  item.status = body.transition === 'pause' ? 'paused' : 'active'; return { ...item };
};
dataActions[`/api/v1/labeling-batches/${batchId}/close/`] = () => {
  const approved = tasks.filter(task => task.latest_review && ['corrected', 'accepted_without_edit'].includes(task.latest_review.decision)).length;
  const snapshot = { snapshot_id: id(22), cycle_no: 3, item_count: 373 + approved, manifest_digest: digest('c'), created_at: stamp };
  batches[2].status = 'closed'; batches[2].approved_count = approved; campaign.current_cycle = 3;
  if (!snapshots.some(item => item.snapshot_id === snapshot.snapshot_id)) snapshots.push(snapshot);
  dataResponses[`/api/v1/annotation-snapshots/${snapshot.snapshot_id}/export/`] = { ...snapshot, items: tasks.filter(task => task.latest_review).map(task => ({ sample_ref: task.sample_ref, human_label: task.latest_review?.human_label })) };
  return snapshot;
};
for (const snapshot of snapshots) dataResponses[`/api/v1/annotation-snapshots/${snapshot.snapshot_id}/export/`] = { ...snapshot, items: [{ sample_ref: 'demo-approved-sample', human_label: { label: 'Helpful' } }] };
for (const index of indexes) dataActions[`/api/v1/index-versions/${index.index_id}/query/`] = body => {
  const query = String(body.query || '').trim().toLowerCase();
  if (!query || query.includes('no matches') || query.includes('zzzz')) return { results: [] };
  const ordered = query.includes('split') || query.includes('dataset') ? [chunks[1], chunks[0], chunks[2]] : query.includes('evaluation') || query.includes('model') ? [chunks[2], chunks[1], chunks[0]] : chunks;
  return { results: ordered.slice(0, Math.max(1, Math.min(20, Number(body.top_k) || 5))).map((chunk, rank) => ({ ...chunk, score: [0.86, 0.74, 0.62][rank] })) };
};
dataActions['/api/v1/knowledge-bases/'] = body => {
  const value = { knowledge_base_id: id(53), kb_id: id(53), name: String(body.name || 'Demo knowledge base'), description: String(body.description || ''), created_at: stamp, updated_at: stamp };
  if (!knowledgeBases.some(item => item.knowledge_base_id === value.knowledge_base_id)) knowledgeBases.push(value);
  dataActions[`/api/v1/knowledge-bases/${value.knowledge_base_id}/index/`] = dataActions[`/api/v1/knowledge-bases/${id(51)}/index/`];
  return value;
};

for (const base of knowledgeBases) dataActions[`/api/v1/knowledge-bases/${base.knowledge_base_id}/index/`] = body => {
  const documents = body.documents as Array<{ title: string; content: string }>;
  const created = { index_id: id(63), knowledge_base: base.knowledge_base_id === id(51) ? 1 : 2, embedding_space: 1, revision_no: 7, status: 'ready', chunk_count: documents.length, adapter_type: 'lexical', manifest_digest: digest('e'), created_at: stamp };
  indexes.push(created);
  dataActions[`/api/v1/index-versions/${created.index_id}/query/`] = () => ({ mode: 'lexical', results: documents.map((document, index) => ({ chunk_id: id(210 + index), text: document.content, score: 1, metadata: { document_title: document.title, span: `0:${document.content.length}`, fixture: true } })) });
  return created;
};

const initialData = structuredClone(dataResponses);
const initialDataActions = new Set(Object.keys(dataActions));
function restoreFixture(current: unknown, initial: unknown): unknown {
  if (Array.isArray(initial)) {
    const target = Array.isArray(current) ? current : [];
    target.length = initial.length;
    initial.forEach((value, index) => { target[index] = restoreFixture(target[index], value); });
    return target;
  }
  if (initial && typeof initial === 'object') {
    const target = current && typeof current === 'object' && !Array.isArray(current) ? current as Record<string, unknown> : {};
    const original = initial as Record<string, unknown>;
    for (const key of Object.keys(target)) if (!(key in original)) delete target[key];
    for (const [key, value] of Object.entries(original)) target[key] = restoreFixture(target[key], value);
    return target;
  }
  return initial;
}

// Preserve the array/object identities captured by story action handlers.
export function resetDataFixtures(): void {
  restoreFixture(dataResponses, initialData);
  for (const key of Object.keys(dataActions)) if (!initialDataActions.has(key)) delete dataActions[key];
}
