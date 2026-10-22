// Storybook-only synthetic records. They never represent a live worker, measured invoice or qualified deployment.
const demoEvidence = {
  level: 'simulation',
  source: 'Synthetic Storybook fixture; no runtime or production execution took place.',
  production_qualified: false,
  hardware_qualified: false,
  documentation: '/docs/engineering/capability-evidence.md',
};
const releaseEvidence = {
  ...demoEvidence,
  level: 'configuration_only',
  source: 'Synthetic release metadata and endpoint pointers; live serving is not verified.',
};
const created = '2026-10-05T08:00:00Z';
const updated = '2026-10-11T10:00:00Z';

// List values stay as arrays; the Storybook API adapter supplies the pagination envelope.
export const operationsResponses: Record<string, unknown> = {
  '/api/v1/workers/setup/': { can_administer: false, profiles: [] },
  '/api/v1/budget-policies/permissions/': { can_administer: false, scope: 'tenant' },
  '/api/v1/compute-plugins/': [],
  '/api/v1/compute-allocations/': [],
  '/api/v1/jobs/': [
    {
      job_id: '40000000-0000-4000-8000-000000000001', name: 'Anvil Assistant · SFT demo', pool: 1,
      status: 'succeeded', desired_action: 'run', priority: 100, attempt_count: 1, max_attempts: 3,
      requirements: { slots: 2, accelerator: 'cpu', memory_gb: 16 },
      payload: { type: 'training', training_run_id: '30000000-0000-4000-8000-000000000001', model_version_id: '10000000-0000-4000-8000-000000000002', dataset_revision_id: '20000000-0000-4000-8000-000000000002', execution_evidence: demoEvidence },
      depends_on: [], created_at: '2026-10-11T09:15:00Z', updated_at: '2026-10-11T09:24:00Z',
    },
    {
      job_id: '40000000-0000-4000-8000-000000000002', name: 'Prepare support corpus', pool: 1,
      status: 'running', desired_action: 'cancel', priority: 75, attempt_count: 1, max_attempts: 2,
      requirements: { slots: 1, accelerator: 'cpu' },
      payload: { type: 'dataset_prepare', dataset_id: 1, revision_id: '20000000-0000-4000-8000-000000000002', execution_evidence: demoEvidence },
      depends_on: [], created_at: '2026-10-11T08:08:00Z', updated_at: '2026-10-11T09:58:00Z',
    },
    {
      job_id: '40000000-0000-4000-8000-000000000003', name: 'Anvil Assistant · evaluation demo', pool: 2,
      status: 'succeeded', desired_action: 'run', priority: 50, attempt_count: 1, max_attempts: 2,
      requirements: { slots: 1, accelerator: 'cpu' },
      payload: { type: 'evaluation', evaluation_run_id: '30000000-0000-4000-8000-000000000002', candidate_model_version: 1, execution_evidence: demoEvidence },
      depends_on: [], created_at: '2026-10-11T09:30:00Z', updated_at: '2026-10-11T09:42:00Z',
    },
    {
      job_id: '40000000-0000-4000-8000-000000000004', name: 'Export candidate metadata', pool: 1,
      status: 'queued', desired_action: 'run', priority: 40, attempt_count: 0, max_attempts: 2,
      requirements: { slots: 1, accelerator: 'cpu' },
      payload: { type: 'metadata_export', release_version_id: '60000000-0000-4000-8000-000000000003', execution_evidence: demoEvidence },
      depends_on: ['40000000-0000-4000-8000-000000000001'], created_at: '2026-10-11T09:15:00Z', updated_at: '2026-10-11T09:15:00Z',
    },
    {
      job_id: '40000000-0000-4000-8000-000000000005', name: 'Index knowledge corpus', pool: 2,
      status: 'failed', desired_action: 'run', priority: 30, attempt_count: 2, max_attempts: 2,
      requirements: { slots: 1, accelerator: 'cpu' },
      payload: { type: 'index', dataset_id: 1, execution_evidence: demoEvidence },
      depends_on: [], created_at: '2026-10-10T13:00:00Z', updated_at: '2026-10-10T13:34:00Z',
    },
    {
      job_id: '40000000-0000-4000-8000-000000000006', name: 'Obsolete annotation export', pool: 1,
      status: 'cancelled', desired_action: 'cancel', priority: 20, attempt_count: 0, max_attempts: 2,
      requirements: { slots: 1, accelerator: 'cpu' },
      payload: { type: 'annotation_export', dataset_id: 1, execution_evidence: demoEvidence },
      depends_on: [], created_at: '2026-10-10T10:00:00Z', updated_at: '2026-10-10T10:12:00Z',
    },
    {
      job_id: '40000000-0000-4000-8000-000000000007', name: 'Anvil Assistant · active SFT demo', pool: 1,
      status: 'running', desired_action: 'run', priority: 90, attempt_count: 2, max_attempts: 3,
      requirements: { slots: 2, accelerator: 'cpu', memory_gb: 16 },
      payload: { type: 'training', training_run_id: '30000000-0000-4000-8000-000000000004', model_version_id: '10000000-0000-4000-8000-000000000002', dataset_revision_id: '20000000-0000-4000-8000-000000000002', execution_evidence: demoEvidence },
      depends_on: [], created_at: '2026-10-11T09:05:00Z', updated_at: '2026-10-11T09:56:00Z',
    },
  ],
  '/api/v1/job-attempts/': [
    {
      attempt_id: '41000000-0000-4000-8000-000000000007', job_id: '40000000-0000-4000-8000-000000000007',
      worker_id: 1, status: 'running', progress: 0.3125, error: '', started_at: '2026-10-11T09:10:00Z',
      completed_at: null, lease_expires_at: '2026-10-11T10:03:00Z', result_envelope: null,
    },
    {
      attempt_id: '41000000-0000-4000-8000-000000000002', job_id: '40000000-0000-4000-8000-000000000001',
      worker_id: 1, status: 'succeeded', progress: 1, error: '', started_at: '2026-10-11T09:15:00Z',
      completed_at: '2026-10-11T09:24:00Z', lease_expires_at: null, result_envelope: { execution_evidence: demoEvidence },
    },
    {
      attempt_id: '41000000-0000-4000-8000-000000000001', job_id: '40000000-0000-4000-8000-000000000007',
      worker_id: 2, status: 'expired', progress: 0.12, error: 'Synthetic fixture: previous lease expired before a result was accepted.',
      started_at: '2026-10-11T09:05:00Z', completed_at: '2026-10-11T09:08:00Z', lease_expires_at: '2026-10-11T09:07:00Z', result_envelope: null,
    },
    {
      attempt_id: '41000000-0000-4000-8000-000000000003', job_id: '40000000-0000-4000-8000-000000000002',
      worker_id: 2, status: 'running', progress: 0.92, error: '', started_at: '2026-10-11T08:12:00Z',
      completed_at: null, lease_expires_at: '2026-10-11T10:02:00Z', result_envelope: null,
    },
    {
      attempt_id: '41000000-0000-4000-8000-000000000004', job_id: '40000000-0000-4000-8000-000000000003',
      worker_id: 3, status: 'succeeded', progress: 1, error: '', started_at: '2026-10-11T09:30:00Z',
      completed_at: '2026-10-11T09:42:00Z', lease_expires_at: null, result_envelope: { execution_evidence: demoEvidence },
    },
    {
      attempt_id: '41000000-0000-4000-8000-000000000005', job_id: '40000000-0000-4000-8000-000000000005',
      worker_id: 3, status: 'failed', progress: 0.31, error: 'Synthetic fixture: source artifact is unavailable.',
      started_at: '2026-10-10T13:18:00Z', completed_at: '2026-10-10T13:34:00Z', lease_expires_at: null, result_envelope: null,
    },
    {
      attempt_id: '41000000-0000-4000-8000-000000000006', job_id: '40000000-0000-4000-8000-000000000005',
      worker_id: 3, status: 'failed', progress: 0.08, error: 'Synthetic fixture: initial artifact lookup failed.',
      started_at: '2026-10-10T13:02:00Z', completed_at: '2026-10-10T13:15:00Z', lease_expires_at: null, result_envelope: null,
    },
  ],
  '/api/v1/budget-policies/': [
    { policy_id: '50000000-0000-4000-8000-000000000001', name: 'Research CPU hours', period: 'monthly', unit: 'cpu_hour', limit_amount: '2400.000000', currency: 'USD', enabled: true, stop_behavior: 'stop', created_at: created, updated_at: updated },
    { policy_id: '50000000-0000-4000-8000-000000000002', name: 'Evaluation input tokens', period: 'monthly', unit: 'input_token', limit_amount: '100000000.000000', currency: 'USD', enabled: true, stop_behavior: 'stop', created_at: created, updated_at: updated },
    { policy_id: '50000000-0000-4000-8000-000000000003', name: 'Archived GPU allowance', period: 'monthly', unit: 'gpu_hour_eu', limit_amount: '100.000000', currency: 'EUR', enabled: false, stop_behavior: 'stop', created_at: created, updated_at: updated },
    { policy_id: '50000000-0000-4000-8000-000000000004', name: 'Dataset acquisition records', period: 'monthly', unit: 'bank_acquisition_records', limit_amount: '100000.000000', currency: '', enabled: true, stop_behavior: 'stop', created_at: created, updated_at: updated },
  ],
  '/api/v1/worker-pools/': [
    { id: 1, name: 'Research CPU pool', status: 'active', queue_name: 'research-cpu', result_egress: 'metadata_only', created_at: created },
    { id: 2, name: 'Evaluation pool', status: 'active', queue_name: 'evaluation-cpu', result_egress: 'metadata_only', created_at: created },
    { id: 3, name: 'Archive GPU pool', status: 'draining', queue_name: 'archive-gpu', result_egress: 'envelope', created_at: created },
  ],
  '/api/v1/worker-inventory/queue-diagnosis/': { rows: [] },
  '/api/v1/worker-inventory/': [
    { id: 1, name: 'research-worker-01', pool: 1, pool_name: 'Research CPU pool', status: 'busy', slots: 4, capabilities: { accelerator: 'cpu', memory_gb: 32, tasks: ['training', 'dataset_prepare'], fixture: 'Storybook synthetic registration' }, last_heartbeat_at: '2026-10-11T09:56:00Z', created_at: created },
    { id: 2, name: 'research-worker-02', pool: 1, pool_name: 'Research CPU pool', status: 'busy', slots: 4, capabilities: { accelerator: 'cpu', memory_gb: 32, tasks: ['training', 'dataset_prepare'], fixture: 'Storybook synthetic registration' }, last_heartbeat_at: '2026-10-11T09:55:00Z', created_at: created },
    { id: 3, name: 'evaluation-worker-01', pool: 2, pool_name: 'Evaluation pool', status: 'available', slots: 2, capabilities: { accelerator: 'cpu', memory_gb: 16, tasks: ['evaluation', 'index'], fixture: 'Storybook synthetic registration' }, last_heartbeat_at: '2026-10-11T09:54:00Z', created_at: created },
    { id: 4, name: 'archive-worker-01', pool: 3, pool_name: 'Archive GPU pool', status: 'draining', slots: 2, capabilities: { accelerator: 'gpu', memory_gb: 48, tasks: ['training'], fixture: 'Storybook synthetic registration' }, last_heartbeat_at: '2026-10-10T18:10:00Z', created_at: created },
    { id: 5, name: 'archive-worker-02', pool: 3, pool_name: 'Archive GPU pool', status: 'offline', slots: 4, capabilities: { accelerator: 'gpu', memory_gb: 48, tasks: ['training'], fixture: 'Storybook synthetic registration' }, last_heartbeat_at: null, created_at: created },
  ],
  '/api/v1/runner-manifests/': [
    { id: 1, manifest_id: '51000000-0000-4000-8000-000000000001', name: 'Character SFT runner', version: '1.3.0', digest: 'a'.repeat(64), manifest: { runtime_id: 'character-sft-demo', execution_evidence: demoEvidence }, enabled: true, compatibility: { accelerator: ['cpu'], tasks: ['training'], tokenizer: 'character', result_format: 'metadata_only', fixture: 'Synthetic manifest; no runtime is started by Storybook' }, created_at: created, updated_at: updated },
    { id: 2, manifest_id: '51000000-0000-4000-8000-000000000002', name: 'Slice evaluation runner', version: '2.1.0', digest: 'b'.repeat(64), manifest: { runtime_id: 'slice-eval-demo', execution_evidence: demoEvidence }, enabled: true, compatibility: { accelerator: ['cpu'], tasks: ['evaluation'], metrics: ['accuracy', 'latency_ms'], fixture: 'Synthetic manifest' }, created_at: created, updated_at: updated },
    { id: 3, manifest_id: '51000000-0000-4000-8000-000000000003', name: 'Legacy indexing runner', version: '0.8.0', digest: 'c'.repeat(64), manifest: { runtime_id: 'legacy-index-demo', execution_evidence: demoEvidence }, enabled: false, compatibility: { accelerator: ['cpu'], tasks: ['index'], fixture: 'Synthetic disabled manifest' }, created_at: created, updated_at: updated },
  ],
  '/api/v1/usage-events/': [],
  '/api/v1/budget-reservations/': [],
  '/api/v1/usage-events/summary/': {
    tenant_id: '90000000-0000-4000-8000-000000000001',
    usage_by_unit: [
      { unit: 'cpu_hour', total_quantity: '1284.375000', total_amount: '421.300000', event_count: 84, currency: 'USD' },
      { unit: 'storage_gb_day', total_quantity: '892.000000', total_amount: '126.400000', event_count: 31, currency: 'USD' },
      { unit: 'input_token', total_quantity: '48200000.000000', total_amount: '294.900000', event_count: 126, currency: 'USD' },
      { unit: 'output_token', total_quantity: '5100000.000000', total_amount: '32.700000', event_count: 72, currency: 'USD' },
      { unit: 'gpu_hour_eu', total_quantity: '24.000000', total_amount: '76.800000', event_count: 8, currency: 'EUR' },
    ],
    total_policies: 4, active_reservations_count: 3, total_reserved_amount: null,
    reserved_by_unit: [
      { unit: 'training_steps', currency: '', reserved_amount: '180.000000', reservation_count: 2 },
      { unit: 'cpu_hour', currency: 'USD', reserved_amount: '35.000000', reservation_count: 1 },
    ],
  },
  '/api/v1/audit/': [
    { event_id: '70000000-0000-4000-8000-000000000016', actor_id: '91000000-0000-4000-8000-000000000001', actor_kind: 'user', action: 'job_lifecycle', resource_type: 'job', resource_id: '40000000-0000-4000-8000-000000000002', result: 'ok', created_at: '2026-10-11T09:58:00Z', input_snapshot: { desired_action: 'cancel', observed_state: 'running', worker_acknowledged: false, fixture: 'Synthetic cancellation request' } },
    { event_id: '70000000-0000-4000-8000-000000000015', actor_id: '91000000-0000-4000-8000-000000000002', actor_kind: 'user', action: 'create', resource_type: 'release_version', resource_id: '60000000-0000-4000-8000-000000000003', result: 'ok', created_at: '2026-10-11T09:30:00Z', input_snapshot: { release: 1, revision_no: 3, candidate_ref: '10000000-0000-4000-8000-000000000002', execution_evidence: demoEvidence } },
    { event_id: '70000000-0000-4000-8000-000000000014', actor_id: '91000000-0000-4000-8000-000000000002', actor_kind: 'user', action: 'update', resource_type: 'dataset_revision', resource_id: '20000000-0000-4000-8000-000000000002', result: 'ok', created_at: '2026-10-11T08:30:00Z', input_snapshot: { status: 'published', revision_no: 1, sample_count: 1200, fixture: 'Synthetic publication metadata' } },
    { event_id: '70000000-0000-4000-8000-000000000013', actor_id: '91000000-0000-4000-8000-000000000001', actor_kind: 'user', action: 'job_lifecycle', resource_type: 'job', resource_id: '40000000-0000-4000-8000-000000000001', result: 'ok', created_at: '2026-10-11T09:15:00Z', input_snapshot: { state: 'running', attempt_count: 1, worker_id: 1, fixture: 'Synthetic worker claim' } },
    { event_id: '70000000-0000-4000-8000-000000000012', actor_id: '91000000-0000-4000-8000-000000000003', actor_kind: 'api_key', action: 'create', resource_type: 'evaluation_run', resource_id: '30000000-0000-4000-8000-000000000002', result: 'ok', created_at: '2026-10-11T09:30:00Z', input_snapshot: { candidate_model_version: 1, metric_keys: ['accuracy', 'latency_ms'], execution_evidence: demoEvidence } },
    { event_id: '70000000-0000-4000-8000-000000000011', actor_id: '91000000-0000-4000-8000-000000000002', actor_kind: 'user', action: 'update', resource_type: 'dataset_revision', resource_id: '20000000-0000-4000-8000-000000000002', result: 'ok', created_at: '2026-10-10T15:20:00Z', input_snapshot: { preparation_recipe: { version: 7, remove_duplicates: true, min_length: 24 }, fixture: 'Synthetic recipe update' } },
    { event_id: '70000000-0000-4000-8000-000000000010', actor_id: '91000000-0000-4000-8000-000000000001', actor_kind: 'user', action: 'create', resource_type: 'dataset_revision', resource_id: '20000000-0000-4000-8000-000000000002', result: 'ok', created_at: '2026-10-10T09:10:00Z', input_snapshot: { dataset: 1, revision_no: 1, status: 'draft', source_name: 'Assistant instruction corpus', fixture: 'Synthetic dataset draft' } },
    { event_id: '70000000-0000-4000-8000-000000000009', actor_id: '91000000-0000-4000-8000-000000000004', actor_kind: 'api_key', action: 'auth', resource_type: 'project', resource_id: '92000000-0000-4000-8000-000000000001', result: 'denied', created_at: '2026-10-09T14:05:00Z', input_snapshot: { requested_role: 'manager', granted_role: 'viewer', fixture: 'Synthetic authorization denial; no credentials included' } },
    { event_id: '70000000-0000-4000-8000-000000000008', actor_id: '91000000-0000-4000-8000-000000000001', actor_kind: 'user', action: 'create', resource_type: 'training_run', resource_id: '30000000-0000-4000-8000-000000000001', result: 'ok', created_at: '2026-10-09T10:30:00Z', input_snapshot: { base_model_version: 1, dataset_revision: '20000000-0000-4000-8000-000000000002', execution_evidence: demoEvidence } },
    { event_id: '70000000-0000-4000-8000-000000000007', actor_id: '91000000-0000-4000-8000-000000000003', actor_kind: 'worker', action: 'job_lifecycle', resource_type: 'job', resource_id: '40000000-0000-4000-8000-000000000005', result: 'error', created_at: '2026-10-09T09:40:00Z', input_snapshot: { state: 'failed', reason: 'source_artifact_unavailable', fixture: 'Synthetic failure; no real storage request' } },
    { event_id: '70000000-0000-4000-8000-000000000006', actor_id: '91000000-0000-4000-8000-000000000002', actor_kind: 'user', action: 'update', resource_type: 'model_version', resource_id: '10000000-0000-4000-8000-000000000002', result: 'ok', created_at: '2026-10-08T15:12:00Z', input_snapshot: { license_evidence: 'apache-2.0', intended_tasks: ['support_response'], fixture: 'Synthetic model card metadata' } },
    { event_id: '70000000-0000-4000-8000-000000000005', actor_id: '91000000-0000-4000-8000-000000000001', actor_kind: 'user', action: 'budget', resource_type: 'budget_policy', resource_id: '50000000-0000-4000-8000-000000000001', result: 'ok', created_at: '2026-10-08T11:00:00Z', input_snapshot: { unit: 'cpu_hour', reserved_quantity: '120.000000', fixture: 'Synthetic reservation record' } },
    { event_id: '70000000-0000-4000-8000-000000000004', actor_id: '91000000-0000-4000-8000-000000000004', actor_kind: 'api_key', action: 'delete', resource_type: 'model_version', resource_id: '10000000-0000-4000-8000-000000000002', result: 'denied', created_at: '2026-10-07T15:40:00Z', input_snapshot: { reason: 'active_release_reference', fixture: 'Synthetic deletion denial' } },
    { event_id: '70000000-0000-4000-8000-000000000003', actor_id: '91000000-0000-4000-8000-000000000002', actor_kind: 'user', action: 'create', resource_type: 'serving_endpoint', resource_id: '61000000-0000-4000-8000-000000000001', result: 'ok', created_at: '2026-10-07T09:20:00Z', input_snapshot: { endpoint_key: 'atlas-staging', name: 'Atlas staging metadata', fixture: 'Synthetic endpoint record; not a running service' } },
    { event_id: '70000000-0000-4000-8000-000000000002', actor_id: '91000000-0000-4000-8000-000000000001', actor_kind: 'user', action: 'create', resource_type: 'model', resource_id: '10000000-0000-4000-8000-000000000001', result: 'ok', created_at: '2026-10-06T13:10:00Z', input_snapshot: { name: 'Atlas Assistant', intended_tasks: ['support_response'], fixture: 'Synthetic registry model' } },
    { event_id: '70000000-0000-4000-8000-000000000001', actor_id: '91000000-0000-4000-8000-000000000001', actor_kind: 'user', action: 'tenancy', resource_type: 'project', resource_id: '92000000-0000-4000-8000-000000000001', result: 'ok', created_at: '2026-10-05T08:00:00Z', input_snapshot: { name: 'Atlas research workspace', fixture: 'Synthetic project initialization' } },
  ],
  '/api/v1/release-versions/': [
    {
      release_version_id: '60000000-0000-4000-8000-000000000003', project: 1, release: 1, revision_no: 3,
      candidate_type: 'model', candidate_ref: '10000000-0000-4000-8000-000000000002', model_version: 1,
      status: 'draft', recorded_status: 'qualified', manifest_digest: 'd'.repeat(64),
      execution_evidence: releaseEvidence, created_at: '2026-10-11T09:30:00Z',
      model_card: { name: 'Atlas Assistant r3', dataset_revision_id: '20000000-0000-4000-8000-000000000002', training_run_id: '30000000-0000-4000-8000-000000000001', evaluation_run_id: '30000000-0000-4000-8000-000000000002', intended_tasks: ['support_response'], limitations: ['Synthetic Storybook data.', 'Metadata-only gates do not certify runtime behavior or production serving.'] },
      quantization_spec: {}, gate_results: [
        { gate_result_id: '62000000-0000-4000-8000-000000000001', criterion_key: 'license_compliance', passed: true, evidence_digest: 'e'.repeat(64), details: { license: 'apache-2.0', fixture: 'Synthetic metadata check; recorded qualification is demoted because production execution is unavailable' }, checked_at: '2026-10-11T09:32:00Z' },
      ],
    },
    {
      release_version_id: '60000000-0000-4000-8000-000000000002', project: 1, release: 1, revision_no: 2,
      candidate_type: 'model', candidate_ref: '10000000-0000-4000-8000-000000000002', model_version: 1,
      status: 'evaluating', recorded_status: 'evaluating', manifest_digest: 'f'.repeat(64),
      execution_evidence: releaseEvidence, created_at: '2026-10-10T13:00:00Z',
      model_card: { name: 'Atlas Assistant r2', intended_tasks: ['support_response'], limitations: ['Synthetic Storybook evaluation record; no live serving.'] },
      quantization_spec: {}, gate_results: [],
    },
    {
      release_version_id: '60000000-0000-4000-8000-000000000001', project: 1, release: 1, revision_no: 1,
      candidate_type: 'model', candidate_ref: '10000000-0000-4000-8000-000000000002', model_version: 1,
      status: 'rejected', recorded_status: 'rejected', manifest_digest: '1'.repeat(64),
      execution_evidence: releaseEvidence, created_at: '2026-10-09T10:30:00Z',
      model_card: { name: 'Atlas Assistant r1', limitations: ['Synthetic Storybook candidate; independent runtime qualification is missing.'] },
      quantization_spec: {}, gate_results: [
        { gate_result_id: '62000000-0000-4000-8000-000000000002', criterion_key: 'accuracy_threshold', passed: false, evidence_digest: '2'.repeat(64), details: { required_accuracy: 0.9, actual_accuracy: null, reason: 'No production-qualified evaluation evidence', fixture: 'Synthetic Storybook gate' }, checked_at: '2026-10-09T10:40:00Z' },
      ],
    },
  ],
  '/api/v1/serving-endpoints/': [
    {
      endpoint_id: '61000000-0000-4000-8000-000000000001', project: 1,
      endpoint_key: 'atlas-staging', name: 'Atlas staging metadata', created_at: '2026-10-07T09:20:00Z', updated_at: '2026-10-11T09:40:00Z',
      active_deployment: { deployment_id: '63000000-0000-4000-8000-000000000001', release_version: 3, release_version_id: '60000000-0000-4000-8000-000000000003', revision_no: 3, readiness_state: 'pending', recorded_readiness_state: 'ready', execution_evidence: demoEvidence, created_at: '2026-10-11T09:40:00Z' },
    },
    {
      endpoint_id: '61000000-0000-4000-8000-000000000002', project: 1,
      endpoint_key: 'atlas-production', name: 'Atlas production metadata', created_at: '2026-10-08T08:10:00Z', updated_at: '2026-10-11T09:30:00Z', active_deployment: null,
    },
  ],
};

// SPDX documents are fixture metadata only. example.invalid is never fetched.
for (const revision of [1, 2, 3]) {
  const versionId = `60000000-0000-4000-8000-${String(revision).padStart(12, '0')}`;
  operationsResponses[`/api/v1/release-versions/${versionId}/sbom/`] = {
    verified: false, warnings: ['Synthetic demo metadata inventory. No committed weights were generated or verified.'],
    spdx_id: 'SPDXRef-ModelAnvil-Model-10000000-0000-4000-8000-000000000002', sbom_digest: '3'.repeat(64),
    spdx_document: {
      spdxVersion: 'SPDX-2.3', dataLicense: 'CC0-1.0', SPDXID: 'SPDXRef-DOCUMENT', name: `Synthetic Atlas release r${revision}`,
      documentNamespace: `https://example.invalid/storybook/releases/${versionId}`,
      creationInfo: { created: '2026-10-11T09:45:00Z', creators: ['Tool: ModelAnvil-Storybook-Fixture'], comment: 'Synthetic demo document; no artifacts were generated, downloaded or qualified.' },
      packages: [
        { SPDXID: 'SPDXRef-ModelAnvil-Model-10000000-0000-4000-8000-000000000002', name: 'Atlas Assistant demo model', versionInfo: `r${revision}`, downloadLocation: 'NOASSERTION', filesAnalyzed: false, licenseDeclared: 'Apache-2.0', licenseConcluded: 'NOASSERTION', copyrightText: 'NOASSERTION' },
        { SPDXID: 'SPDXRef-Tokenizer-Demo', name: 'Synthetic character tokenizer', versionInfo: '1.0.0', downloadLocation: 'NOASSERTION', filesAnalyzed: false, licenseDeclared: 'Apache-2.0', licenseConcluded: 'NOASSERTION', copyrightText: 'NOASSERTION' },
      ],
      relationships: [
        { spdxElementId: 'SPDXRef-DOCUMENT', relationshipType: 'DESCRIBES', relatedSpdxElement: 'SPDXRef-ModelAnvil-Model-10000000-0000-4000-8000-000000000002' },
        { spdxElementId: 'SPDXRef-ModelAnvil-Model-10000000-0000-4000-8000-000000000002', relationshipType: 'DEPENDS_ON', relatedSpdxElement: 'SPDXRef-Tokenizer-Demo' },
      ],
    },
  };
  operationsResponses[`/api/v1/release-versions/${versionId}/export-bundle/`] = {
    release_version_id: versionId, revision_no: revision, status: 'draft', execution_evidence: demoEvidence,
    model_card: { name: 'Synthetic demo release', intended_use: 'Storybook metadata preview only' },
    independent_loading_evidence: { load_tested: false, runtime_format: null, verified_at: null, reason: 'Synthetic metadata only; no executable weights.' },
  };
}

export const operationsActions: Record<string, (body: Record<string, unknown>) => unknown> = {
  '/api/v1/jobs/': body => {
    const jobs = operationsResponses['/api/v1/jobs/'] as Record<string, unknown>[];
    const job = {
      job_id: crypto.randomUUID(), name: String(body.name || 'Synthetic demo job'), pool: Number(body.pool || 1),
      status: 'queued', desired_action: 'run', priority: Number(body.priority ?? 50), attempt_count: 0, max_attempts: 2,
      requirements: body.requirements || { slots: 1 }, payload: body.payload || {}, depends_on: [], created_at: updated, updated_at: updated,
    };
    jobs.unshift(job);
    refreshJobProjection(job);
    operationsActions[`/api/v1/jobs/${job.job_id}/cancel/`] = () => cancelJobFixture(job.job_id);
    return job;
  },
  '/api/v1/serving-endpoints/': body => {
    const endpoints = operationsResponses['/api/v1/serving-endpoints/'] as Record<string, unknown>[];
    const endpoint = { endpoint_id: crypto.randomUUID(), project: 1, endpoint_key: String(body.endpoint_key || 'demo-endpoint'), name: String(body.name || body.endpoint_key || 'Synthetic endpoint'), active_deployment: null, created_at: updated, updated_at: updated };
    endpoints.push(endpoint);
    return endpoint;
  },
};

for (const revision of [1, 2, 3]) {
  const versionId = `60000000-0000-4000-8000-${String(revision).padStart(12, '0')}`;
  const path = `/api/v1/release-versions/${versionId}/sbom/`;
  operationsActions[path] = () => ({
    ...(operationsResponses[path] as Record<string, unknown>),
    sbom_artifact: { artifact_id: `64000000-0000-4000-8000-${String(revision).padStart(12, '0')}`, sha256: '3'.repeat(64),
      download_endpoint: `/api/v1/artifacts/64000000-0000-4000-8000-${String(revision).padStart(12, '0')}/download/` },
  });
}

function cancelJobFixture(jobId: string) {
  const rows = operationsResponses['/api/v1/jobs/'] as Record<string, unknown>[];
  const current = rows.find(row => row.job_id === jobId);
  if (!current) throw new Error('Synthetic fixture job was not found.');
  if (['succeeded', 'failed', 'cancelled'].includes(String(current.status))) return current;
  const response = { ...current, desired_action: 'cancel', status: current.status === 'queued' ? 'cancelled' : current.status, updated_at: updated };
  rows[rows.indexOf(current)] = response;
  refreshJobProjection(response);
  return response;
}

// Match the read-only job projection; attempts carry progress while the job summary keeps it unknown.
function refreshJobProjection(job: Record<string, unknown>) {
  const payload = job.payload as Record<string, unknown>;
  const pools = operationsResponses['/api/v1/worker-pools/'] as Record<string, unknown>[];
  const pool = pools.find(row => row.id === job.pool);
  const workers = operationsResponses['/api/v1/worker-inventory/'] as Record<string, unknown>[];
  const attempts = (operationsResponses['/api/v1/job-attempts/'] as Record<string, unknown>[]).filter(row => row.job_id === job.job_id);
  const activeAttempt = attempts.find(row => row.status === 'running');
  const worker = workers.find(row => row.id === activeAttempt?.worker_id);
  const active = ['queued', 'running'].includes(String(job.status));
  const requested = job.desired_action === 'cancel' && job.status !== 'cancelled';
  const acknowledged = job.status === 'cancelled';
  operationsResponses[`/api/v1/jobs/${job.job_id}/`] = job;
  operationsResponses[`/api/v1/run-details/job/${job.job_id}/`] = {
    kind: 'job', id: job.job_id, name: job.name, project: null, execution_mode: 'worker',
    observed: { state: job.status, job_state: job.status, current_step: null, total_steps: null, progress: null, latest_loss: null, attempts: `${job.attempt_count}/${job.max_attempts || 3}`, created_at: job.created_at, started_at: null, completed_at: null, updated_at: job.updated_at },
    desired: { action: job.desired_action, acknowledged, note: 'Desired action is recorded separately from observed state. Synthetic fixtures do not execute a worker.' },
    ownership: job.status === 'running' ? {
      state: worker ? 'held' : 'unknown', worker: worker?.name || null, worker_status: worker?.status || null,
      lease_expires_at: activeAttempt?.lease_expires_at || null,
      reason: worker ? 'Synthetic demo claim and lease only; no worker is running in Storybook.' : 'Synthetic running state without a recorded worker claim.',
    } : { state: 'released', worker: null, worker_status: null, lease_expires_at: null, reason: `The demo job is '${job.status}' and has no worker claim.` },
    inputs: { payload, requirements: job.requirements, priority: job.priority, pool: pool?.name || null, pool_status: pool?.status || null, depends_on: job.depends_on, training_run: payload.training_run_id || null },
    metrics: { total: 0, truncated: false, rows: [], latest_loss: null }, checkpoints: null,
    usage: { reservations: [], events: [], events_truncated: false },
    links: { job: job.job_id, training_run: payload.training_run_id || null, evaluation_runs: [], dataset_revision: null, model_version: null },
    evidence: demoEvidence,
    actions: {
      cancel: { available: active && !requested, requested, acknowledged, endpoint: `/api/v1/jobs/${job.job_id}/cancel/`, blocked_by: requested ? ['Cancellation is already requested; no worker acknowledgement is inferred.'] : active ? [] : [`The job is '${job.status}' and no longer accepts cancellation.`] },
      resume: { available: false, permission: { role: 'engineer', required: 'engineer', satisfied: true }, blocked_by: ['This read-only projection exposes no re-queue action. Resubmit through the jobs API when appropriate.'], operator_path: 'Job attempts are append-only; re-queuing does not remove failed attempts.', preserves_history: 'Prior job attempts remain immutable.' },
    },
    generated_at: updated,
  };
  operationsResponses[`/api/v1/run-details/job/${job.job_id}/attempts/`] = attempts.map(attempt => {
    const recordedWorker = workers.find(row => row.id === attempt.worker_id);
    return { attempt_id: attempt.attempt_id, job_id: attempt.job_id, worker: recordedWorker?.name || null, worker_status: recordedWorker?.status || null, status: attempt.status, progress: attempt.progress, error: attempt.error, lease_expires_at: attempt.lease_expires_at, started_at: attempt.started_at, completed_at: attempt.completed_at, has_result: !!attempt.result_envelope };
  });
}

for (const job of operationsResponses['/api/v1/jobs/'] as Record<string, unknown>[]) {
  refreshJobProjection(job);
  operationsActions[`/api/v1/jobs/${job.job_id}/cancel/`] = () => cancelJobFixture(String(job.job_id));
}

const initialResponses = structuredClone(operationsResponses);
const initialActionPaths = new Set(Object.keys(operationsActions));

// The story's beforeEach resets mutations made by create/cancel interactions.
export function resetOperationsFixtures() {
  for (const path of Object.keys(operationsResponses)) delete operationsResponses[path];
  Object.assign(operationsResponses, structuredClone(initialResponses));
  for (const path of Object.keys(operationsActions)) {
    if (!initialActionPaths.has(path)) delete operationsActions[path];
  }
}
