# ModelAnvil Technical Requirements

Version 0.1 | 8 October 2026 | PRD baseline 0.7 | Status proposed

We will build a multi-organization model development platform with versioned data and model workflows, durable compute orchestration, and independent release evidence. This document specifies the engineering behavior needed to implement the PRD. Requirements use MUST for release obligations and SHOULD for recommended implementation choices. Proposed numeric targets remain subject to qualification under the PRD.

## 1 Architecture and implementation boundaries

Start with a modular Django control plane. Modules own organizations, sources, datasets, annotation, models, workflows, evaluations, RAG, context, releases, infrastructure, and usage. Use explicit service functions and transaction boundaries between modules. Avoid an initial microservice per feature.

Run the API, outbox publisher, scheduler/reconciler, CPU/GPU workers, and query/inference runtime as separately deployable processes. The browser and Mac app use the same versioned API. Training, scraping, decoding, code evaluation, indexing, and projection MUST NOT execute in web request handlers. Interactive query execution has its own timeout, concurrency, and compute budget so training queues cannot monopolize it.

| Boundary | Authoritative responsibility | Interface |
| --- | --- | --- |
| Browser and Mac | Presentation, local drafts, transfer progress | HTTPS API and authenticated events |
| Django control plane | Authorization, validated domain changes, jobs, lineage, release gates | Versioned REST API; internal service contracts |
| PostgreSQL | Durable records, transactions, claims, leases, outbox, audit metadata | Application-owned migrations |
| RabbitMQ | Short dispatch notifications | Persistent notifications and publisher confirmation |
| S3 storage | Raw assets, shards, manifests, checkpoints, exports | Authorized scoped object operations |
| Worker runtime | Execute a pinned stage within granted resources | Claim, heartbeat, checkpoint, commit, stop protocol |
| Query runtime | Authorized retrieval, context assembly, inference, traces | Internal scoped request and authenticated public query endpoint |
| Integration adapters | Translate declared platform contracts to engines/providers | Versioned capability manifests and conformance fixtures |

Infrastructure details belong in operator views. Product users choose outcomes, datasets, recipes, and authorized compute; they do not need to configure brokers to run experiments.

## 2 Platform contracts

| ID | Engineering requirement | Verification |
| --- | --- | --- |
| TECH-001 | MUST apply organization and project authorization to every object, list, search, event, storage grant, worker operation, and export. Roles grant separate label, compute, extension, export, and publish actions. | Cross-organization and assigned-batch access fixtures, including guessed IDs and event reconnection |
| TECH-002 | MUST freeze run inputs to exact dataset, model, tokenizer, schema, rubric, recipe, code, environment, and adapter revisions. Reuse requires matching canonical input digest and current authorization. | Modify a source/recipe after launch; prior run inputs and comparison diff remain stable |
| TECH-003 | MUST persist a workflow DAG and step dependencies. Nodes become eligible only after committed prerequisites. Cycles and incompatible ports fail validation. | Dependency failure, resume, selective retry, duplicate completion, and immutable-output fixtures |
| TECH-004 | MUST provide versioned API, CLI, service identities, consistent pagination/filtering, structured errors, optimistic concurrency, and idempotent chargeable mutations. | Complete import → train → evaluate → export using API/CLI only |
| TECH-005 | MUST provide resumable uploads/imports with immutable source snapshots, checksums, counts, failures, and progress. Partially transferred data cannot be published ready. | Interrupt multipart transfer, reconnect, corrupt a shard, and cancel |
| TECH-006 | MUST isolate acquisition/rendering/decoding; enforce crawl domain, path, request, time, byte, concurrency, and egress limits. Scrapling sits behind a connector contract. | Controlled crawler fixtures, denied destinations, restart and cancellation |
| TECH-007 | MUST represent supported text, chat, media, code, tables, and custom records through versioned schemas and ordered asset references. Each capability has its own support status. | Round-trip fixtures preserve source pages, spans, timestamps, coordinate systems, and mixed content order |
| TECH-008 | MUST record cleaning previews, keep/drop reasons, detector confidence, exact/near-duplicate groups, and group-aware split checks. Corpus-scale execution is sharded/streaming. | Seeded privacy/duplicate/overlap cases; million-record manifest qualification |
| TECH-009 | MUST publish dataset versions, mixtures, tokenized shards, and exports as immutable manifests with lineage and schema. | Repeated preparation and cancellation never publish mixed or partial versions |
| TECH-010 | MUST validate catalog manifests, license evidence, immutable revision, access conditions, and connector readiness before enabling preset downloads. Share-alike and gated access require explicit applicable choices. | SVG starter journey; unknown/restricted license blocked; catalog update suspends affected downloads |
| TECH-011 | MUST support assigned annotation tasks, rubric revisions, save/review/adjudication, blind preferences, ties/abstention, independent authorship, and model/rule provenance. | Original draft and correction remain separately inspectable; concurrent review conflict surfaced |
| TECH-012 | MUST support manual and existing-model labeling seeds, approved cumulative snapshots, task-model training, independent qualification, fixed next-batch assignment, and repeated review. Manual/random selection is R1. | Two train-and-next-batch cycles per seed mode on one named text task |
| TECH-013 | MUST enforce campaign budgets, pause/resume, model rollback, inadequate-data handling, and independent audits; acceptance/confidence alone cannot qualify a model. | Failed candidate preserves prior model and all reviewed labels; held-out groups excluded |
| TECH-014 | MUST generate permitted synthetic examples/candidates with prompts, model/prompt revisions, decoding, cost, validators, and provenance. Evaluation failures selected for training require leakage checks. | Origin preserved through review and export; protected cases denied as seeds |
| TECH-015 | MUST register exact model/tokenizer/processor artifacts and support tokenizer training/inspection with compatibility validation. | Vocabulary/special-token mismatch blocked before resource allocation |
| TECH-016 | MUST qualify scratch pretraining, continued pretraining, full SFT, and supported adapter recipes. Preflight validates hardware, template, precision, schema, storage, limits, and estimates. | PRD scenarios 1 and 2; external loading; unsupported combinations blocked |
| TECH-017 | MUST reserve the full distributed resource group, checkpoint declared state, recover with explicit limits, expose training metrics/usage, and support early stopping and bounded parameter searches within project limits. | Two-node interruption, partial checkpoint rejection, no duplicate active allocation, stop/search budget fixtures |
| TECH-018 | MUST implement DPO and reward-model training as distinct recipes with validated human preferences and held-out evidence. | Pair/tie construction, ancestry, reference settings, score-distribution inspection |
| TECH-019 | MUST qualify one learned-reward RLHF recipe and one verifier-based RL recipe. Record policy/reference/reward/verifier versions, rollout/update limits, divergence controls, objective components, and recovery state. | PRD scenarios 4 and 13, reward exploitation fixture, held-out human comparison, budget stop |
| TECH-020 | MUST version evaluation datasets, scorers, judges, calibration, protocol, slices, failures, and uncertainty. Candidate comparisons identify noncomparable settings. | Hand-scored metric cases, calibrated judge sample, missing-result handling |
| TECH-021 | MUST enforce release criteria using a frozen evidence set; authorized exceptions are policy-bound and audited. Exports include hashes, dependencies, model card, and independent loading evidence. | Failing/missing check blocks promotion; adapter identifies base revision; endpoint rollback |
| TECH-022 | MUST version corpus, chunks, embeddings, and indexes; support lexical/dense/hybrid retrieval, fusion, reranking, citations, abstention, and authenticated query serving. | Same suite runs all modes; incompatible dimensions blocked; complete query trace |
| TECH-023 | MUST implement PRD Section 17 metric definitions, relevant-unit mappings, judgment coverage, N/A rules, and separate retrieval/answer/operational scores. | Hand-scored Recall/Precision/Hit/MRR/nDCG fixtures and answer checks |
| TECH-024 | MUST enforce current permissions and tombstones through retrieval, supplied context, trace reads, caches, plots, and exports, including index rollback. | Revoke/delete evidence while old indexes and caches exist; no unauthorized use or disclosure |
| TECH-025 | MUST save projection coordinates/settings and optional cluster assignments with stable evidence IDs. Neighbors use the declared original embedding space; sampled plots disclose coverage and provide a table equivalent. | Reopen without recomputation; lasso resolves IDs; revoked points suppressed |
| TECH-026 | MUST compile typed context blocks into exact serialized model input with provenance, token budgets, output reserve, and omission/truncation/compression records. | Role/limit failures, input-plus-output budget, before/after evidence mappings |
| TECH-027 | MUST run paired context ablations and multi-turn stress suites with pinned model, recipe, tools, memory snapshots, decoding, and evaluation. Support frozen replay and bounded live tests separately. | Position/length/injection/overflow/stale-memory/tool-error cases and recipe rollback |
| TECH-028 | MUST operate a versioned extension SDK with capability, dependency, resource, and permission declarations; executable extensions run outside platform services. | Custom format import → inspect → convert → train → export; denied storage/network probes |
| TECH-029 | MUST qualify managed, self-hosted, and hybrid core workflows. Hybrid workers use scoped revocable credentials and configured metadata/artifact egress boundaries. | Offline provisioned self-hosted journey and disconnected/reconnected private worker |
| TECH-030 | MUST maintain durable jobs, capacity claims, leases, fencing, cancellation, retries, quarantine, and recovery reconciliation independently of broker acknowledgements. | Duplicate dispatch, broker loss, stale commit, worker loss, drain, and starvation fixtures |
| TECH-031 | MUST meter owned CPU/GPU, storage, prediction, training, and provider usage with idempotent records and enforce budgets at admission and during work. | Duplicate meter callback, concurrent reservation, delayed billing, and stop-limit fixtures |
| TECH-032 | MUST provide audit records, correlated logs, metrics, backup/restore, migrations, retention, and deletion impact reporting for supported deployment profiles. | Restore drill, failed migration recovery, expired trace access, and dependency-aware deletion |

TRN08 remains a Target: the shared schema supports media from the outset, while each multimodal trainer, annotator, generator, and exporter requires separate qualification. Advanced automated uncertainty/disagreement/diversity sampling remains a Target under SYN02. No broad-format statement can override these boundaries.

## 3 API conventions and endpoint inventory

Use `/api/v1/orgs/{org_id}/projects/{project_id}/...` for project-scoped resources. Organization settings and global catalog discovery have separate scopes. Every nested identifier is reauthorized and must belong to its declared parent. Do not treat path scoping as permission enforcement.

UUID identifiers are opaque. Timestamps use RFC 3339 UTC. APIs use bounded cursor pagination and explicit sort/filter allowlists. Responses include `request_id`; errors include `code`, `message`, `field_errors`, and `retryable`. Use 401 for missing authentication, 403 for disallowed actions where disclosure is permitted, 404 for concealed/unavailable resources, 409 for state/idempotency conflicts, 412 for stale revision conditions, 422 for domain preflight failure, and 429 for rate limits. Existence disclosure is policy-consistent across surfaces.

Chargeable create/command endpoints require `Idempotency-Key`. Scope the key to organization, principal, and operation. Store a request digest and original result; reuse with a different body returns 409. Proposed retention is at least 7 days, published by the API. Durable domain uniqueness prevents duplicate cycle triggers or attempt commits even after key expiry. Updates require a revision/ETag precondition; label drafts use client mutation IDs and conflict resolution.

Long operations return 202 with `job_id`, `status_url`, and event cursor. The resource is not ready until the committed completion record exists. Events are an observation channel; GET state is authoritative. Use server-sent events with resumable event IDs where available and bounded polling fallback. Connection credentials must not appear in logged URLs.

| Resource group | Representative operations |
| --- | --- |
| Access and settings | Organization/team/project CRUD; memberships; grants; credentials; policies; audit reads |
| Transfers and sources | Create upload session, authorize part, complete/abort; create source/import/crawl; preview mapping; inspect failures |
| Dataset Bank | Search qualified sources/presets; inspect pinned revision/license; validate scope; launch download/preparation |
| Datasets | Create preparation recipe/version; preview; compare; split/mix; publish; export |
| Annotation | Create campaign, assign batch, submit review revision, adjudicate, close batch, create cumulative snapshot |
| Labeling cycle | Train candidate, inspect quality, promote/keep prior, draft next, pause/resume, rollback future assignment |
| Models and training | Register model/tokenizer; validate recipe; preflight; create run; checkpoint; inspect metrics |
| Alignment | Create candidate generation/preferences; DPO/reward/RLHF/verifier run; inspect reward and independent evidence |
| Evaluation and release | Create suite/run; compare; create frozen gate result; export/promote/rollback release |
| RAG | Build knowledge base/index; version pipeline; validate; query; inspect/redact trace; evaluate; save projection/selection |
| Context | Create recipe/block revisions; compile preview; create replay/stress/ablation experiment; compare; promote recipe |
| Infrastructure | Enroll/drain worker; claim/heartbeat/commit attempt; inspect pool; quotas; budgets; usage |

Commands such as batch closure and promotion MUST be explicit actions with state guards. A generic PATCH cannot bypass lifecycle validation. Generate the OpenAPI contract during WP-02; representative endpoint names here are a design inventory, not a published API.

## 4 Job and worker protocol

Persist desired action separately from observed execution state. Proposed states are `validating`, `blocked`, `queued`, `claimed`, `running`, `checkpointing`, `retry_wait`, `interrupted`, `succeeded`, `failed`, and `cancelled`. Cancellation requests set `desired_action=cancel`; cancellation becomes observed only after backend stop and resource release. A run may contain multiple jobs; job and run states are related but not interchangeable.

1. In one database transaction, authorize and validate immutable inputs, reserve budget, create job/dependencies, and write outbox notification. Record a blocked reason if prerequisites or capacity policy prevent eligibility.
2. Publish a small notification containing schema version, event ID, job ID, routing capability, and trace ID. No secrets, samples, or large configuration enter messages. Confirmation marks publication, not execution success.
3. An available authorized worker/gateway requests an atomic claim. Lock job/allocation records; verify eligibility and free capacity; create a monotonically fenced attempt and reserve the complete resource group. Only then acknowledge dispatch.
4. Launch the pinned container/adapter with short-lived scoped artifact access. Heartbeats renew the application lease using server time and the current fencing token. Job progress is monotonic only where the adapter can define it; stage progress and unknown estimates remain distinct.
5. Write checkpoints/results to attempt-scoped staging objects. Verify manifest sizes/hashes, input digest, lease/fence, actual execution identity, and authorization before the final metadata commit. A stale attempt cannot publish a ready result.
6. Reconcile lease loss and backend state. Confirm the previous allocation has stopped or revoke it before chargeable retry. Unknown execution remains interrupted for operator resolution. Retry transient errors with bounded backoff; deterministic invalid inputs fail without a retry loop.
7. Release resources and settle usage once actual stop is confirmed. Make dependent nodes eligible in the completion transaction; idempotent outbox events initiate them.

Proposed pilot defaults are 15-second heartbeats and a 90-second lease, with a recovery grace period and backend reconciliation. Qualify these under congestion and disconnection. Worker loss cannot be inferred solely from a delayed heartbeat. Saturated or draining workers do not take another assignment. Acquisition, CPU preparation, GPU training, and evaluation can use distinct queues; all share admission and isolation rules.

RabbitMQ distinguishes consumer acknowledgements from publisher confirms; neither is the platform completion record. See the [official acknowledgement contract](https://www.rabbitmq.com/docs/confirms). The database/outbox and worker protocol above are ModelAnvil design obligations.

## 5 Storage and integrity

Store large payloads in S3 and metadata/manifests in PostgreSQL. Publish immutable object keys after staging verification; do not depend on object rename semantics. Keep tenant-scoped digest reuse; cross-organization content hashes must not create an existence side channel. Every committed artifact has hash algorithm, digest, byte size, content type, schema revision, ownership, and lineage.

Grant short-lived scoped access after current authorization. Sensitive source downloads requiring immediate revocation use an authorization proxy or equivalent revocable gateway; direct presigned URLs have an explicit bounded expiry and cannot silently claim immediate revocation. Retention rules cover logs, query inputs, checkpoints, exports, and multipart remnants. Logical immutability does not prevent authorized deletion or policy tombstones.

Use PostgreSQL full-text and pgvector as initial retrieval candidates. Keep incompatible dimensions/encoder revisions in distinct embedding spaces. Verify exact reference search and approximate search under real permissions and metadata filters. pgvector documents exact and approximate search and filtering behavior; ModelAnvil must qualify its own topology and recall targets. [pgvector reference](https://github.com/pgvector/pgvector).

## 6 Nonfunctional qualification

| Measure | Proposed PRD qualification target | Evidence and limits |
| --- | --- | --- |
| Team load | 10 organizations, 50 teams, 100 active sessions | Mixed workload, isolated data and quotas |
| Job load | 10 running GPU jobs and 20 data jobs on adequately provisioned pools | Admission/fairness test; not a promise for any cluster size |
| Distributed run | At least one tested 2-node configuration | Topology and checkpoint recovery published |
| Data scale | 1 TB source corpus and 1 million-record manifest | Streaming preparation and bounded pagination |
| Metadata API | p95 below 2 seconds for defined operations | Excludes bulk transfer and generation; specified load |
| Dispatch | p95 below 60 seconds when full eligible capacity is free | Submission to worker start; image pulls reported separately |
| Hosted control plane | 99.5% monthly proposed availability | Definition and monitoring agreed before launch |
| Metadata recovery | RPO at most 15 minutes, RTO at most 4 hours | Restore drill; artifact recovery separately declared |

RAG qualification publishes corpus/chunk/embedding size, concurrency, filter selectivity, stage/end-to-end latency, answer quality, index build time, and tested point counts. Context qualification publishes tested lengths and task performance, not advertised capacity alone. Visualization must use bounded sampling/aggregation for larger datasets. No fixed RAG throughput or training speed is invented before hardware measurement.

## 7 Access, operations, and deployment

Prefer organization-scoped RBAC plus explicit project/resource grants; operator access does not automatically grant application-level content access. Treat compute-host administration as a separate trust boundary with disclosed privileged access. Authentication provider, SSO protocols, credential rotation, and audit retention are WP-01 decisions. Self-hosted must not require hosted telemetry or a hosted identity service after provisioning.

Keep audit records for permission changes, exports, recipe publication, label approval, model promotion, release exceptions, and credential use. Structured logs correlate request, workflow, job, attempt, and trace IDs. Metrics cover queue age, eligible work, allocated capacity, stale leases, retries, failed commits, gate failures, usage delay, query latency, and source/index freshness. Alerts link to an operator recovery action.

Container images, lock files, database migrations, configuration schema, dependency inventory, backup/restore, upgrades, and rollback procedures are release deliverables. Compose is the single-server reference with stated host-failure limits. Multi-node production requires separately qualified Kubernetes/Helm, stateful recovery, and GPU group allocation. Credentials and executables are excluded from portable project exports unless explicitly permitted; extension installation is privileged.

## 8 Traceability to all PRD functional requirements

Ranges are inclusive. Every functional PRD requirement appears once below; technical contracts may also support several domains.

| PRD IDs | Primary technical contracts | Work packages | PRD acceptance scenarios |
| --- | --- | --- | --- |
| PRJ01–PRJ03 | TECH-002–004 | WP-02, WP-05 | 1, 2, 8 |
| DAT01–DAT06 | TECH-005–009 | WP-04, WP-05 | 1, 5, 8, 11 |
| BANK01–BANK07 | TECH-010 | WP-06 | 11 |
| ANN01–ANN03 | TECH-011 | WP-09 | 3, 5, 13, 17 |
| ANN04–ANN07 | TECH-012–013 | WP-10 | 17 |
| SYN01–SYN02 | TECH-014 | WP-09, WP-10 | 3, 13, 17 |
| TRN01–TRN02 | TECH-015 | WP-07 | 1, 2 |
| TRN03–TRN05 | TECH-016 | WP-07, WP-08 | 1, 2 |
| TRN06–TRN07 | TECH-017 | WP-03, WP-08 | 1, 8, 12, 13 |
| TRN08 | TECH-007, TECH-016; Target qualification | WP-01, WP-14 | Separate multimodal report; scenario 5 covers data |
| ALN01–ALN02 | TECH-018 | WP-11 | 3, 13 |
| ALN03–ALN05 | TECH-019–020 | WP-11 | 4, 13 |
| EVA01–EVA03 | TECH-020 | WP-07 | 1–4, 13–17 |
| EVA04 | TECH-021 | WP-15 | 10, 13, 14, 16 |
| REL01–REL02 | TECH-021 | WP-15 | 1, 2, 10 |
| OPS01 | TECH-001 | WP-02, WP-17 | 7, 9, 14, 15 |
| OPS02 | TECH-017, TECH-030 | WP-03, WP-17 | 7, 12 |
| OPS03 | TECH-031 | WP-03, WP-17 | 7, 13 |
| OPS04 | TECH-030 | WP-03 | 8, 12, 17 |
| OPS05–OPS06 | TECH-029 | WP-16, WP-17 | 9 |
| OPS07 | TECH-030 | WP-03, WP-17 | 12 |
| EXT01–EXT02 | TECH-028 | WP-14 | 6 |
| API01 | TECH-004 | WP-02, WP-16 | API-only journey evidence |
| RAG01–RAG03 | TECH-022 | WP-12 | 14 |
| RAG04–RAG06 | TECH-023, TECH-020–021 | WP-12, WP-15 | 14 |
| RAG07 | TECH-025 | WP-12 | 15 |
| RAG08 | TECH-024 | WP-12, WP-17 | 14, 15 |
| CTX01–CTX02 | TECH-026–027 | WP-13 | 16 |
| CTX03–CTX04 | TECH-027 | WP-13, WP-15 | 16 |

## 9 Qualification evidence format

Each supported combination publishes platform/adapter/image versions, schema/model/license revisions, hardware/topology, workload size, permission profile, test report, observed metrics, recovery guarantees, known limits, and review date. States are proposed, experimental, supported, requires extension, or unsupported. A candidate library or import parser cannot grant a training capability by implication.

Official API details are checked again when pinning dependencies. This pack proposes platform behavior; it does not establish vendor performance or integration readiness.
