export const MAX_DATASET_BYTES = 16 * 1024 * 1024;
export const DATASET_SOURCE_TYPES = {
  jsonl: 'application/x-ndjson', csv: 'text/csv', json: 'application/json',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pdf: 'application/pdf',
};
export type DatasetSourceFormat = keyof typeof DATASET_SOURCE_TYPES;

export interface UploadedArtifact {
  artifact_id: string;
  state: 'committed';
  sha256: string;
  byte_size: number;
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
  state: string;
  published_at: string | null;
  metadata: Record<string, unknown>;
}

export interface PreparedDataset {
  artifact: UploadedArtifact;
  dataset: Dataset;
  revision: DatasetRevision;
}

export interface PrepareUploadedDatasetOptions {
  file: File;
  name: string;
  token: string;
  splitSeed?: string;
  validationPercent?: number;
  testPercent?: number;
  sourceFormat?: DatasetSourceFormat;
  textField?: string;
  groupField?: string;
  chunkCharacters?: number;
  fetchImpl?: typeof fetch;
}

export interface PaginatedResult<T> {
  count?: number;
  next?: string | null;
  previous?: string | null;
  results: T[];
}

export interface DatasetFirstPages {
  datasets: PaginatedResult<Dataset>;
  revisions: PaginatedResult<DatasetRevision>;
}

export type DatasetWorkspace = DatasetFirstPages;

export interface LoadDatasetFirstPagesOptions {
  token: string;
  fetchImpl?: typeof fetch;
}

export class DatasetClientError extends Error {
  readonly step: string;
  readonly status?: number;

  constructor(step: string, message: string, status?: number) {
    super(`${step}: ${message}`);
    this.name = 'DatasetClientError';
    this.step = step;
    this.status = status;
  }
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SHA256_RE = /^[0-9a-f]{64}$/i;

function validDataset(v: unknown): v is Dataset {
  if (!v || typeof v !== 'object') return false;
  const d = v as Record<string, unknown>;
  return typeof d.dataset_id === 'string' && UUID_RE.test(d.dataset_id)
    && typeof d.name === 'string' && d.name.trim().length > 0
    && (d.description === null || typeof d.description === 'string')
    && (d.current_revision === null || (typeof d.current_revision === 'number' && Number.isInteger(d.current_revision) && d.current_revision >= 0))
    && !!d.metadata && typeof d.metadata === 'object' && !Array.isArray(d.metadata)
    && typeof d.created_at === 'string' && typeof d.updated_at === 'string';
}

function validRevision(v: unknown): v is DatasetRevision {
  if (!v || typeof v !== 'object') return false;
  const r = v as Record<string, unknown>;
  return typeof r.revision_id === 'string' && UUID_RE.test(r.revision_id)
    && typeof r.dataset === 'number' && Number.isInteger(r.dataset) && r.dataset >= 0
    && typeof r.revision_no === 'number' && Number.isInteger(r.revision_no) && r.revision_no >= 0
    && typeof r.schema_version === 'string'
    && typeof r.manifest_digest === 'string'
    && (r.manifest_artifact === null || (typeof r.manifest_artifact === 'number' && Number.isInteger(r.manifest_artifact) && r.manifest_artifact >= 0))
    && (typeof r.recipe_digest === 'string')
    && Array.isArray(r.source_snapshots)
    && (r.row_count === null || (typeof r.row_count === 'number' && Number.isInteger(r.row_count) && r.row_count >= 0))
    && typeof r.state === 'string'
    && (r.published_at === null || typeof r.published_at === 'string')
    && !!r.metadata && typeof r.metadata === 'object' && !Array.isArray(r.metadata);
}

function validateToken(token: string): void {
  if (typeof token !== 'string' || !token.trim()) {
    throw new DatasetClientError('Input validation', 'A bearer token is required.');
  }
  if (/[\r\n\x00-\x1f\x7f]/.test(token)) {
    throw new DatasetClientError('Input validation', 'Token contains invalid header characters.');
  }
}

function sanitizeUrl(path: string): string {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\')) {
    throw new DatasetClientError('Network safety', 'Refusing unapproved URL target.');
  }
  return path;
}

async function request(
  url: string,
  step: string,
  token: string,
  fetchImpl: typeof fetch,
  expectedStatus: number,
  body?: unknown,
): Promise<any> {
  const safeUrl = sanitizeUrl(url);
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token.trim()}`,
    Accept: 'application/json',
  };
  const init: RequestInit = {
    method: body ? 'POST' : 'GET',
    headers,
    redirect: 'error',
  };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetchImpl(safeUrl, init);
  } catch {
    throw new DatasetClientError(step, 'Network request failed or a redirect was blocked. No automatic retry.');
  }
  if (res.status !== expectedStatus) {
    if (res.status === 400) {
      throw new DatasetClientError(step, `HTTP 400: Request validation failed; no revision was published.`, 400);
    }
    if (res.status === 404 || res.status === 405 || res.status === 501) {
      throw new DatasetClientError(step, `HTTP ${res.status}: Backend capability is unavailable or not implemented.`, res.status);
    }
    throw new DatasetClientError(step, `HTTP ${res.status}: Request failed with status ${res.status}; expected ${expectedStatus}.`, res.status);
  }
  try {
    return await res.json();
  } catch {
    throw new DatasetClientError(step, 'Invalid JSON response from server.', res.status);
  }
}

function verifyArtifact(
  artifact: any,
  expectedState: 'staging' | 'committed',
  expectedSha256: string,
  expectedSize: number,
  step: string,
  expectedId?: string,
): void {
  if (!artifact || typeof artifact !== 'object') {
    throw new DatasetClientError(step, 'Invalid artifact response payload.');
  }
  if (typeof artifact.artifact_id !== 'string' || !UUID_RE.test(artifact.artifact_id)) {
    throw new DatasetClientError(step, 'Invalid or missing artifact ID.');
  }
  if (expectedId && artifact.artifact_id !== expectedId) {
    throw new DatasetClientError(step, 'Artifact ID mismatch.');
  }
  if (artifact.state !== expectedState) {
    throw new DatasetClientError(step, `Artifact state mismatch: expected ${expectedState}, got ${artifact.state}.`);
  }
  if (typeof artifact.sha256 !== 'string' || !SHA256_RE.test(artifact.sha256) || artifact.sha256 !== expectedSha256) {
    throw new DatasetClientError(step, 'Artifact SHA-256 mismatch or invalid format.');
  }
  if (typeof artifact.byte_size !== 'number' || artifact.byte_size !== expectedSize) {
    throw new DatasetClientError(step, 'Artifact byte size mismatch.');
  }
}

function verifyPage<T>(page: any, guard: (v: unknown) => v is T, step: string): PaginatedResult<T> {
  if (!page || typeof page !== 'object' || !Array.isArray(page.results)) {
    throw new DatasetClientError(step, 'Invalid page response payload.');
  }
  if (page.count !== undefined) {
    if (typeof page.count !== 'number' || !Number.isInteger(page.count) || page.count < 0 || page.count < page.results.length) {
      throw new DatasetClientError(step, 'Invalid page count.');
    }
  }
  if (page.next !== undefined && page.next !== null && typeof page.next !== 'string') {
    throw new DatasetClientError(step, 'Invalid page next pointer.');
  }
  for (const item of page.results) {
    if (!guard(item)) {
      throw new DatasetClientError(step, 'Invalid page item: failed schema validation.');
    }
  }
  return page as PaginatedResult<T>;
}

export async function loadDatasetFirstPages({
  token,
  fetchImpl = fetch,
}: LoadDatasetFirstPagesOptions): Promise<DatasetFirstPages> {
  validateToken(token);
  const datasets = verifyPage(
    await request('/api/v1/datasets/', 'Dataset listing', token, fetchImpl, 200),
    validDataset, 'Dataset listing',
  );
  const revisions = verifyPage(
    await request('/api/v1/dataset-revisions/', 'Revision listing', token, fetchImpl, 200),
    validRevision, 'Revision listing',
  );
  return { datasets, revisions };
}

export async function fetchDatasetWorkspace(
  token: string,
  fetchImpl: typeof fetch = fetch,
): Promise<DatasetWorkspace> {
  return loadDatasetFirstPages({ token, fetchImpl });
}

export async function prepareUploadedDataset({
  file, name, token, splitSeed = '0', validationPercent = 10, testPercent = 10,
  sourceFormat = 'jsonl', textField = 'text', groupField = '',
  chunkCharacters,
  fetchImpl = fetch,
}: PrepareUploadedDatasetOptions): Promise<PreparedDataset> {
  if (typeof name !== 'string' || !name.trim()) {
    throw new DatasetClientError('Input validation', 'Dataset name is required.');
  }
  if (name.trim().length > 200) {
    throw new DatasetClientError('Input validation', 'Dataset name cannot exceed 200 characters.');
  }
  validateToken(token);
  if (chunkCharacters !== undefined && (!Number.isInteger(chunkCharacters) || chunkCharacters < 32 || chunkCharacters > 4096)) {
    throw new DatasetClientError('Input validation', 'Chunk character limit must be an integer from 32 to 4096.');
  }
  if (!(file instanceof File) || file.size === 0) {
    throw new DatasetClientError('Input validation', 'A nonempty file is required.');
  }
  if (file.size > MAX_DATASET_BYTES) {
    throw new DatasetClientError('Input validation', 'File exceeds the 16 MiB limit.');
  }
  if (!Object.hasOwn(DATASET_SOURCE_TYPES, sourceFormat) || typeof textField !== 'string' || !textField || textField.length > 128
    || typeof groupField !== 'string' || groupField.length > 128
    || ((sourceFormat === 'jsonl' || sourceFormat === 'docx' || sourceFormat === 'pdf') && (textField !== 'text' || groupField))) {
    throw new DatasetClientError('Input validation', 'Choose a supported source format and valid field mappings.');
  }
  if (!Number.isInteger(validationPercent) || !Number.isInteger(testPercent)
    || validationPercent < 0 || testPercent < 0 || validationPercent + testPercent >= 100) {
    throw new DatasetClientError('Input validation', 'Split percentages must be nonnegative integers with a sum below 100.');
  }
  if (typeof splitSeed !== 'string') {
    throw new DatasetClientError('Input validation', 'The split seed must be a string.');
  }
  if (splitSeed.length > 1024) {
    throw new DatasetClientError('Input validation', 'The split seed cannot exceed 1024 characters.');
  }
  let bytes: ArrayBuffer;
  try { bytes = await file.arrayBuffer(); }
  catch { throw new DatasetClientError('Input validation', 'The selected file could not be read.'); }
  if (sourceFormat !== 'docx' && sourceFormat !== 'pdf') {
    try { new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
    catch { throw new DatasetClientError('Input validation', 'The file must be valid UTF-8 text.'); }
  }
  let digest: ArrayBuffer;
  let objectId: string;
  try {
    digest = await crypto.subtle.digest('SHA-256', bytes);
    objectId = crypto.randomUUID();
  } catch {
    throw new DatasetClientError('Input validation', 'WebCrypto is unavailable; use localhost or a secure browser context.');
  }
  const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  const registered = await request('/api/v1/artifacts/', 'Artifact registration', token, fetchImpl, 201, {
    storage_location_id: 'local', object_key: `inputs/${objectId}.${sourceFormat}`,
    sha256, byte_size: file.size, media_type: DATASET_SOURCE_TYPES[sourceFormat],
  });
  verifyArtifact(registered, 'staging', sha256, file.size, 'Artifact registration');
  const form = new FormData();
  form.append('file', file);
  const artifact = await request(`/api/v1/artifacts/${registered.artifact_id}/upload/`, 'File upload', token, fetchImpl, 200, form);
  verifyArtifact(artifact, 'committed', sha256, file.size, 'File upload', registered.artifact_id);
  const dataset = await request('/api/v1/datasets/', 'Dataset creation', token, fetchImpl, 201, { name });
  if (!validDataset(dataset)) throw new DatasetClientError('Dataset creation', 'Invalid dataset response.');
  const revision = await request(`/api/v1/datasets/${dataset.dataset_id}/prepare/`, 'Dataset preparation', token, fetchImpl, 201, {
    input_artifact_id: artifact.artifact_id, split_seed: splitSeed,
    validation_percent: validationPercent, test_percent: testPercent,
    ...(sourceFormat !== 'jsonl' ? { source_format: sourceFormat, text_field: textField, group_field: groupField || null } : {}),
    ...(chunkCharacters !== undefined ? { chunk_characters: chunkCharacters } : {}),
  });
  if (!validRevision(revision) || revision.state !== 'published' || !revision.published_at
    || revision.row_count === null || revision.manifest_artifact === null || !revision.recipe_digest) {
    throw new DatasetClientError('Dataset preparation', 'Invalid response: a published revision was not confirmed.');
  }
  return { artifact, dataset, revision };
}
