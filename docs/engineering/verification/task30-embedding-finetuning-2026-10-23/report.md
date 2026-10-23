# TASK-30: actual CPU embedding fine-tuning and export

Date: 2026-10-23. Base main8f0b7b1 includes merged SQL retrieval PR41. Completes the fine-tuning/export portion left explicit after foundation PR38; TASK67 and TASK68 separately completed the fixed encoder and SQL retrieval.

## Actual training and independent loading

A fresh copy of the fixed Apache-2.0 MiniLM model was trained on one authored CC0 triplet with two training documents, an independently grouped dev document/query, and a held-out document/query. Seed7, two SGD steps, learning rate0.001, normalized cosine softplus triplet loss with margin0.2 and norm clipping1 were frozen before evaluation. Actual losses changed from approximately0.68766 to0.68648. The original serving baseline vectors remain unchanged.

The updated model.safetensors SHA256 is **e65210a9369593262fb40cc1074744ae6daadc6b2c649585a203896652345dbb**, different from baseline **53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db**. The fixed-layout export SHA256 is **cf4720050fb359d9465aee1cb2bc7593406cc0c8087cc098cec5e61b29c74f8b**. A separate Python process, without Django/registry/database access, reloaded the exported model and encoded a public fixed probe into finite normalized384-dimensional vectors. Exact measured output: [actual-runtime.json](actual-runtime.json).

The fixture has **one dev and one held-out query**, cutoff3. Both baseline and candidate have held-out recall1, precision0.3333, MRR1 and nDCG1. These equal results make **no quality-improvement claim**. This is a small software qualification, not a retrieval benchmark or customer held-out quality result.

## Real service/index path

The authenticated HTTP encode endpoint served the actual candidate and returned its export pins. A read-only project-scoped candidate detail endpoint returned the same public space UUID; HTTP candidate creation was refused405. A real worker built separate native vector rows/indexes for baseline and candidate: four corpus rows per space, with distinct space IDs. Actual paired dense retrieval used one versioned held-out query/qrels digest and explicit cutoff3. Changed dimensions, inaccessible project scope, source tombstones, corrupted archives and overlong actual tokenizer input were refused. Repeated candidate encoding matched within1e-6 and baseline encoding remained unchanged.

## Split and provenance checks

Strict manifest tests reject cross-split source groups and normalized text/query duplicates, held-out negatives, invalid negative IDs and falsified negative pool provenance. Protected registered suite groups/prompts cannot train. Minimal persistent inspection fingerprints block future clean-suite relabeling under new IDs and prevent prior held-out groups entering training; raw source text is not stored in these receipts. Tenant row locking matches the existing protected-suite registration lock. Manual negative review remains a declaration; its actual training-only similarity rank is measured. Baseline-mined declarations must identify the actual top eligible training-only nonpositive document.

## Validation and limits

- Required PostgreSQL suite: **20 passed**, including actual fine-tuning/export, independent reload, real candidate/baseline worker indexes/comparison, MiniLM, RabbitMQ recovery and SQL plans.
- Final candidate HTTP/private/version/corruption integration: **one actual-runtime test passed**.
- Clean base feedback/privacy/OpenAPI/split guards: **26 passed, two optional skips**.
- Full integrated backend: **1,031 passed, six optional skips**. Final OpenAPI guard: **four passed**. Migration drift: **no changes detected**. Both schema mirrors include paginated candidate evidence and UUID references.
- No frontend layout or new browser flow was added. Training is the bounded trusted-operator CLI; existing authenticated encode/index/comparison UI/API contracts are reused.

Training limits are 1–20 steps, 1–32 triplets, 3–100 documents,2–64 qrels and256 actual tokens per text. This is a single CPU process, without a durable training queue or optimizer resume. The index build remains durable and quota-metered. Candidate weights/exports are private artifacts and retain input/lineage provenance; withdrawn source/export access refuses cached serving. Previously exported copies and information in trained weights have a separate lifecycle. No GPU, arbitrary architecture/dimension, automatic promotion, privacy erasure of learned information or customer quality claim is made.
