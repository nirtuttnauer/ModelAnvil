# TASK-64 PostgreSQL/pgvector infrastructure

23 October 2026. Reconciled the existing agent implementation from the retained feature-parity checkout into current main without overwriting updated dependency or privacy protections.

- Development and production compose use `pgvector/pgvector:pg16`; `pgvector==0.5.1` is pinned. Migration `rag.0004_vector_extension` creates the extension on PostgreSQL and leaves SQLite unchanged.
- CI has an unconditional `pgvector` job with a healthy PostgreSQL service and explicit `--tag=pg` selection. No `continue-on-error` or unavailable-database skip is used. The ordinary backend job retains SQLite coverage; the test runner excludes only PostgreSQL-tagged cases unless explicitly selected.
- The embedding snapshot is pinned to `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; CI caches that revision. Local snapshot caching completed and its config was verified. Loading real embeddings into retrieval is TASK-67.
- The deterministic hash vector exists only as `fake_embed_query` in tests. Production dense/hybrid pipeline calls require caller-supplied embeddings. Existing lexical behavior and all prior SQLite assertions remain intact.

Fresh validation: Django check and migration consistency pass. Thirty-eight SQLite RAG/API/privacy/authoring regressions pass. A fresh isolated `pgvector/pgvector:pg16` container applied all migrations and passed the vector extension/distance round trip (distance 1.0). Explicitly selecting the same PostgreSQL test on SQLite failed at the database-vendor assertion, with zero skips. This is infrastructure evidence; no semantic retrieval or GPU quality claim is made.

The first CI run caught the production package still using plain PostgreSQL, which cannot apply the new extension migration. The production database image now also supplies pgvector. Final-head CI, including both pgvector runs and the HTTPS production integration, gates the merge. The original checkout, model cache and other projects' containers remain intact; only this run's isolated PostgreSQL container may be removed after use.
