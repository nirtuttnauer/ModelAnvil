/**
 * ModelAnvil API client types (WP-02 generated contracts).
 *
 * Provides shared TypeScript interfaces across the React web shell,
 * client libraries, and tests, matching the OpenAPI 3.1 specification.
 */

export interface PaginatedResult<T> {
  count?: number;
  next?: string | null;
  previous?: string | null;
  results: T[];
}

export interface ApiErrorDetail {
  code: string;
  message: string;
  details?: Record<string, unknown>[];
  request_id?: string;
}

export interface ApiErrorEnvelope {
  error: ApiErrorDetail;
}

// ---------------------------------------------------------------------------
// Identity & Tenancy
// ---------------------------------------------------------------------------

export type TenantStatus = 'active' | 'suspended' | 'deleted';

export interface Tenant {
  tenant_id: string;
  slug: string;
  name: string;
  status: TenantStatus;
  created_at: string;
  updated_at: string;
}

export interface TenantCreate {
  slug: string;
  name: string;
}

export interface User {
  id: string;
  email: string;
  name?: string;
  is_active: boolean;
  created_at: string;
}

export interface UserCreate {
  email: string;
  name?: string;
}

export type Role = 'owner' | 'admin' | 'manager' | 'engineer' | 'viewer' | 'worker';

export interface ApiKey {
  id: string;
  name: string;
  role: Role;
  created_at: string;
  last_used_at?: string | null;
  expires_at?: string | null;
  is_active: boolean;
}

export interface ApiKeyCreate {
  name: string;
  role?: Role;
  expires_at?: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

export interface Membership {
  id: string;
  tenant: string;
  user: string;
  role: Role;
  role_rank: number;
  created_at: string;
}

export interface MembershipCreate {
  user: string;
  role: Role;
}

export interface MembershipUpdate {
  role: Role;
}

// ---------------------------------------------------------------------------
// Hierarchy: Teams, Projects, Config Revisions
// ---------------------------------------------------------------------------

export interface Team {
  id: string;
  slug: string;
  name: string;
  description?: string;
}

export interface TeamCreate {
  slug: string;
  name: string;
  description?: string;
}

export interface Project {
  id: string;
  team: string;
  slug: string;
  name: string;
  description?: string;
}

export interface ProjectCreate {
  team: string;
  slug: string;
  name: string;
  description?: string;
}

export interface TeamMembership {
  id: string;
  team: string;
  user: string;
  role: string;
  role_rank?: number;
}

export interface TeamMembershipCreate {
  team: string;
  user: string;
  role: string;
}

export interface ProjectMembership {
  id: string;
  project: string;
  user: string;
  role: string;
  role_rank?: number;
}

export interface ProjectMembershipCreate {
  project: string;
  user: string;
  role: string;
}

export interface ProjectConfig {
  id: string;
  project: string;
  revision_no: number;
  goals: Record<string, unknown>;
  notes?: string;
  created_by?: string | null;
}

export interface ProjectConfigCreate {
  project: string;
  goals?: Record<string, unknown>;
  notes?: string;
}

// ---------------------------------------------------------------------------
// Artifacts & Data
// ---------------------------------------------------------------------------

export type ArtifactState = 'staging' | 'committed' | 'failed' | 'deleted';

export interface Artifact {
  artifact_id: string;
  storage_location_id?: string;
  object_key?: string;
  sha256: string;
  byte_size: number;
  media_type?: string;
  state: ArtifactState;
  created_at: string;
}

export interface ArtifactRegister {
  storage_location_id?: string;
  object_key: string;
  sha256: string;
  byte_size: number;
  media_type?: string;
}

export interface DataSource {
  source_id: string;
  name: string;
  connector_type: string;
  configuration?: Record<string, unknown>;
  status: string;
}

export interface SourceSnapshot {
  snapshot_id: string;
  source: string;
  digest: string;
  byte_size: number;
  record_count?: number;
  status: string;
}

export interface Dataset {
  dataset_id: string;
  name: string;
  description: string | null;
  current_revision: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DatasetCreate {
  name: string;
  description?: string;
  metadata?: Record<string, unknown>;
}

export type DatasetRevisionState = 'draft' | 'published' | 'failed';

export interface DatasetRevision {
  revision_id: string;
  dataset: number;
  revision_no: number;
  schema_version: string;
  manifest_digest: string;
  manifest_artifact: number | null;
  recipe_digest: string;
  source_snapshots: unknown[];
  row_count: number | null;
  state: DatasetRevisionState | string;
  published_at: string | null;
  metadata: Record<string, unknown>;
}

export interface DatasetPrepareOptions {
  input_artifact_id: string;
  split_seed?: string;
  validation_percent?: number;
  test_percent?: number;
  detect_pii?: boolean;
  detect_quality?: boolean;
  detect_duplicates?: boolean;
  detect_protected_eval?: boolean;
  drop_report?: boolean;
}

// ---------------------------------------------------------------------------
// Workflows, Jobs, & Workers
// ---------------------------------------------------------------------------

export type JobStatus =
  | 'validating'
  | 'blocked'
  | 'queued'
  | 'claimed'
  | 'running'
  | 'checkpointing'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export type JobDesiredAction = 'run' | 'cancel' | 'pause';

export interface Job {
  job_id: string;
  name: string;
  stage: string;
  status: JobStatus;
  desired_action: JobDesiredAction;
  input_digest?: string;
  created_at: string;
  updated_at: string;
}

export interface JobCreate {
  name: string;
  stage: string;
  payload?: Record<string, unknown>;
}

export interface JobAttempt {
  attempt_id: string;
  job: string;
  attempt_no: number;
  worker_id?: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
}

// ---------------------------------------------------------------------------
// Budgets & Usage
// ---------------------------------------------------------------------------

export interface BudgetPolicy {
  policy_id: string;
  name: string;
  tenant_id: string;
  max_compute_credits?: number;
  max_storage_bytes?: number;
}

export interface BudgetReservation {
  reservation_id: string;
  policy: string;
  reserved_amount: number;
  status: string;
}

export interface UsageEvent {
  usage_id: string;
  tenant_id: string;
  resource_type: string;
  quantity: number;
  recorded_at: string;
}

export interface AuditEvent {
  event_id: string;
  tenant_id?: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  timestamp: string;
  details?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Runners & Adapters
// ---------------------------------------------------------------------------

export interface RunnerManifest {
  manifest_id: string;
  name: string;
  version: string;
  runtime_type: string;
  capability_tags?: string[];
}

export interface AdapterRegistryEntry {
  entry_id: string;
  name: string;
  version: string;
  adapter_type: string;
  manifest?: Record<string, unknown>;
}
