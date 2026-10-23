# TASK-30 embedding inference and indexing foundation — 23 October 2026

This change implements the local inference, authenticated serving and worker-built retrieval foundation of TASK-30. It also supplies the implementation required by the approved RAG follow-up TASK-67. TASK-30 remains unfinished: contrastive fine-tuning, protected training-pair/source-group handling, independently loadable candidate export, and baseline/candidate embedding-model evaluation still need implementation. TASK-67 remains in factory order for its own reconciliation; its claim was not bypassed.

## Actual execution

- Model: `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, Apache 2.0, normalized 384-dimensional float32 CPU output. The nine model files, tokenizer and weights are size/SHA-256 pinned in `rag/embedding-pins.json`. Weight SHA-256: `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db` (90,868,376 bytes).
- Runtime: Python 3.12.15 on this arm64 Mac, Torch 2.13.0, Transformers 5.14.0, Sentence Transformers 6.2.0. All 13 optional runtime package versions, CPU architecture, source build and profile pins enter the build runtime digest. Public model bootstrap was the only model download. Encoding loads local files without remote code or a Hub token.
- Real PostgreSQL/pgvector and RabbitMQ ran in separate owned containers on loopback. Existing unrelated services and original dirty checkouts/databases were retained.
- Required Postgres tests executed a registered credential-bearing worker through actual outbox publication and RabbitMQ consumption. An 18-chunk build published a native partial HNSW expression index and served a real locally encoded query; actual PCA used native vectors. Repeated encoding agreed within `1e-6`; shape/norm and 256-token refusal checks passed.
- Recovery controls used explicitly controlled test vectors, separate from the real inference checks. Cancellation after one verified 16-chunk batch retained it; retry encoded only the remaining two chunks and settled two attempts. Invalid dimensions, altered cache checksums, stale fences and exhausted three-attempt limits could not publish READY. A new space encoded its own 18 vectors without reusing another space's cache. Cross-project access and generic job mutation/cancellation/deletion attempts were refused.

## Browser evidence

A fresh private QA account used the actual app against the PostgreSQL API. Through Retrieval forms it imported a known text fixture, registered the pinned space with explicit Apache 2.0 consent, selected a connected worker and attempt allowance, and queued a build. The actual broker worker encoded all six chunks. The UI selected the ready revision, retrieved semantic results for “A sleeping feline on a couch”, persisted a versioned qrels report, generated measured PCA and reopened the ready build after reload.

One desktop/mobile inspection batch and one confirmation batch passed at 1440 and 390 pixels with no horizontal overflow or browser errors. The confirmation also compared the semantic index with its lexical source baseline using identical qrels and verified the score label is **Cosine similarity**. The semantic fixture is functional evidence; its artificial judgments do not qualify customer relevance or show fine-tuning improvement.

- [Build desktop](build-desktop.png), [build mobile](build-mobile.png)
- [Semantic desktop](semantic-desktop.png), [semantic mobile](semantic-mobile.png)
- [Actual browser IDs and outcomes](browser-report.json)

The owned build `01a166e8-2c05-7fa8-acef-8a957152c668` published index `01a166e8-2c02-72c2-9c57-9ba6a7f2b3e6` from source index `01a166e4-6402-7719-be05-e903a31c317e`. Six verified chunks, one charged attempt. Worker processes were stopped after qualification; no GPU or paid provider job was launched.

## Checks

- Full backend with optional CPU runtime: 1,010 tests, six optional skips, passed. Final additions/paired-baseline behavior were covered by the checks below.
- Final clean base access/retrieval/OpenAPI/broker/executor regression checks: 32 tests, three optional skips, passed. They include the existing knowledge-base grant regression; lexical indexes retain inherited knowledge-base access.
- Final required PostgreSQL suite: 12 tests, no skips, passed with real RabbitMQ and model inference. Its CI job installs CPU embeddings and the fixed public cache, then runs offline inference against Postgres plus RabbitMQ.
- Frontend: 226 tests, production build and Storybook build passed. Actual UI evidence is separate from build success.
- Migration drift/system checks passed. The native-vector migration applied successfully to fresh PostgreSQL; the full backend suite also applied it in SQLite without requiring optional inference packages in the base runtime.
- Dependency audit resolved 39 packages from `requirements.embeddings.txt`; no known vulnerabilities. [Audit receipt](dependency-audit.json). This does not waive the separately tracked optional DiskCache issue in TASK-74.

See [operator and data-integrity details](../../embedding-indexes.md). GPU families, image/video diffusion, model training/export and customer quality remain explicitly outside this foundation's evidence.
