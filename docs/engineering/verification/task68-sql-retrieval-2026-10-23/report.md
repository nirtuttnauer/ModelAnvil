# TASK-68: SQL retrieval

Date: 2026-10-23. Implementation started on main786cab4; the independent token-budget PR40 merged during implementation.

PostgreSQL lexical ranking uses a real simple-config tsvector, websearch query and ts_rank_cd. Native vector retrieval supports explicit exact and HNSW modes. Both rank only candidates passing SQL tenant, current project/grants, frozen membership, document revocation/deletion and chunk/document UUID/hash tombstone predicates. HNSW settings and per-channel RRF candidate count/k are recorded; actual fallback and extension version are persisted on each query trace. SQLite compatibility remains explicitly labeled. PostgreSQL refuses legacy JSON semantic-vector loops.

## Real database plans and access checks

The PostgreSQL fixture contains 1,000 deterministic unit vectors in 384 dimensions, testing database mechanics without a semantic-model claim. The HNSW plan contains **embedding_space_1_hnsw** with direct cosine ordering. Exact mode excludes that index using distance-plus-zero ordering. The production HNSW transaction-local sort preference is active during EXPLAIN; the test applies no planner override. Search/planner settings are restored afterward, including a preexisting ef_search=41. DDL explicitly uses m=16 and ef_construction=64; query settings use ef_search=100 and strict iterative scans.

The fixture verifies lexical SQL functions, bounded RRF, narrow membership after nearest rows are excluded, all four tombstone identities, deleted/revoked documents, revocation of an already-created queryset's grant, independent knowledge/index/space grants and cross-tenant refusal. Dense text hydration checks current eligibility again. Empty lexical responses retain their execution receipt.

[Actual exact/HNSW EXPLAIN plans](explain.json).

## Verification

- Full backend before PR40 integration: **1,022 tests passed, six optional skips**.
- Final required PostgreSQL suite: **19 tests passed**, including fixed MiniLM encoding, real RabbitMQ delivery/recovery/cancellation, native vectors/PCA, feedback concurrency and five SQL retrieval tests.
- Final actual MiniLM build/query check exercises API-selected exact mode and confirms the persisted receipt matches the response.
- Clean base runtime: **34 RAG/chunking/OpenAPI tests passed**.
- Migration drift: no changes detected; OpenAPI mirrors include dense_search and retrieval_config.
- Backend execution and inspectable API metadata only; no new frontend layout.

The first plan check exposed filter-and-sort selection for the small filtered corpus. Native vectors are now ranked before bounded text hydration, and explicit HNSW mode prefers the ordered index. The final real plan verifies that path. SQLite checks caught UUID cast formatting differences; its UUID comparison normalizes storage formatting while PostgreSQL retains direct indexed tombstone comparisons.

No GPU, customer quality, universal HNSW recall/latency or model training qualification is asserted. ANN underfill has an explicit exact fallback; a full result count alone does not prove ANN recall. Database snapshot checks cannot retract evidence already delivered to a client.
