# PostgreSQL retrieval execution

PostgreSQL retrieval ranks native pgvector embeddings in SQL and lexical candidates with `to_tsvector('simple', text)`, `websearch_to_tsquery` and `ts_rank_cd`. The `simple` configuration preserves lexical terms without English stemming. Search text is a bound parameter. SQLite retains the explicitly labeled token-overlap compatibility implementation; its results are not PostgreSQL full-text measurements. Legacy JSON vector arrays cannot serve as PostgreSQL semantic indexes: build a native pinned embedding index first.

## Dense modes and recorded settings

`POST /api/v1/index-versions/{index_id}/query/` accepts `dense_search: "exact"` or `"hnsw"` alongside `mode: "dense"` or `"hybrid"`. The default for current embedding builds is HNSW. Queries still encode their text locally with the selected fixed model/tokenizer/runtime; caller-supplied vectors cannot replace that encoding.

Exact mode orders by cosine distance plus zero to prevent an approximate ordered-index plan. HNSW mode orders directly by `vector::vector(384) <=> query`. New embedding builds explicitly create per-space partial HNSW expression indexes with `vector_cosine_ops`, `m=16` and `ef_construction=64`. The index configuration stores those settings, `ef_search=100`, iterative `strict_order` scans, a 20,000 visited-tuple bound, RRF k=60 and two-times candidate overfetch per channel. Queries require pgvector >=0.8, apply the search settings within their transaction, and restore previous settings before returning. Explicit HNSW mode disables sort-plan preference for its ranking statement; exact mode leaves the planner's sort behavior intact. A real PostgreSQL EXPLAIN test verifies the HNSW index appears in the executed mode's plan without changing planner settings in the test.

If filtered ANN results underfill the requested count, the engine runs the same authorized candidate query using exact ordering. The trace records whether that fallback occurred and the actual pgvector extension version. HNSW can trade recall for speed even when it returns the requested count; exact mode is the recall baseline. No universal performance or ANN recall claim is made.

Hybrid retrieval obtains up to two times top-k (API top-k 1–100) independently from SQL lexical and SQL dense search, then combines only these bounded candidate lists by reciprocal rank fusion: sum of `1/(60+channel_rank)`. Candidate count is recorded **per channel**, not a count of the union or a claim that all candidates survived filtering. No Python vector-distance or document token-overlap loop runs on PostgreSQL.

## Access and deletion

The candidate SQL includes the tenant, frozen chunk membership, current ready index, knowledge-base/index/embedding-space project access and explicit grants. Document revocation/deletion and tombstones for chunk UUID, document UUID, chunk hash or document hash are predicates in the ranking query. A grant revoked after a queryset is constructed is rechecked when that queryset executes. SQL never starts from a Python list of already-authorized rows. Dense result hydration rechecks the same eligibility query before returning text; saved traces also recheck current permissions on read. These are current committed database snapshot checks, not a promise to revoke data already delivered to a client.

## Receipts and compatibility

`retrieval_config` is returned from query calls, persisted on QueryTrace even for empty results, repeated in inspectable result metadata and retained on trace reload. Qrels comparison protocols record the actual backend/lexical profile, vector settings, candidate count and RRF k. New lexical index revisions identify their PostgreSQL or SQLite backend accurately; older immutable revisions are not relabeled in place. The new trace field is added by `rag.0008_retrieval_execution_receipt`; existing traces have an empty receipt rather than invented execution evidence.

See [dated verification](verification/task68-sql-retrieval-2026-10-23/report.md) and [embedding setup](embedding-indexes.md). The SQL plan fixture uses deterministic normalized numerical vectors solely to verify database mechanics; actual model encoding/query integration is verified separately with pinned MiniLM and real RabbitMQ/PostgreSQL.

Primary implementation references: [pgvector filtering and iterative scans](https://github.com/pgvector/pgvector#iterative-index-scans), [HNSW options](https://github.com/pgvector/pgvector#hnsw), [Django full-text search](https://docs.djangoproject.com/en/5.2/ref/contrib/postgres/search/).
