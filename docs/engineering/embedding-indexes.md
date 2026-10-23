# Pinned local embedding indexes

Retrieval can now turn an existing frozen MiniLM token index into a separate, worker-built pgvector revision. The source index and old chunk memberships remain available. This bounded CPU profile is inference and indexing; embedding fine-tuning, candidate export and customer quality qualification remain separate work in TASK-30.

## Operator setup

Use PostgreSQL with pgvector and RabbitMQ. Apply migrations. Install base requirements and `requirements.embeddings.txt` in both the API and embedding worker environments. On Linux CPU hosts, install the pinned CPU Torch wheel first:

```sh
python -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt -r requirements.embeddings.txt
python manage.py migrate
python -c "from modelanvil.rag.embedding_model import cache_pinned_model; print(cache_pinned_model())"
```

The bootstrap downloads only nine hash-pinned public model files, without a Hub token. Inference uses local files only and disables remote model code. A dedicated absolute model directory can be configured with `MODELANVIL_EMBEDDING_MODEL_DIR`; otherwise the adapter locates the fixed revision in the local Hub cache. Use `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` after bootstrap. Requests never download a model or send source/query text to a hosted encoder.

In Infrastructure, register **Local CPU embeddings** in an active envelope pool. Supply the one-time worker credential through `MODELANVIL_WORKER_TOKEN` or the interactive prompt. Configure the same database and `RABBITMQ_URL` in the trusted operator process. Run the returned command:

```sh
python manage.py consume_worker --worker-id WORKER_ID --profile cpu-embeddings
python manage.py flush_outbox --loop
```

These are two long-running processes. The broker consumer verifies its worker credential at startup, before deliveries, and every 15 seconds while idle. Per-attempt heartbeats also enforce credential validity and cancellation. Registration alone cannot admit a build: a matching process must have a recent observation. The polling `run_worker --profile cpu-embeddings` remains available for operator diagnostics; the qualified dispatch evidence uses RabbitMQ/outbox delivery.

SQL full-text, exact/HNSW strategies, iterative filtering and execution receipts are described in [SQL retrieval](sql-retrieval.md).

## Retrieval workflow

1. Import documents and build a lexical index with at most 254 MiniLM content tokens per chunk. The encoder adds two special tokens; it refuses overflow instead of truncating. Up to 1,000 frozen accessible chunks are supported.
2. In Local embedding index, register a uniquely named model space after accepting the model's Apache 2.0 license. Its model revision, 384 dimensions, normalization and cosine distance are server-owned immutable pins. This release supports one fixed model profile.
3. Create an `embedding_attempts` allowance in Budgets without a currency. Choose the source revision, space, connected pool and allowance, then queue a build. Three lifetime attempts are reserved for this request; settlement charges one unit per started attempt. These are quantities, not monetary prices.
4. Inspect progress or cancel. Only validated batches enter checkpoint storage. Retry retains verified vectors and encodes the missing chunks, within the original quota period and maximum three attempts. A model/runtime change or corrupted checkpoint is refused; register a fresh space to build under changed runtime pins.
5. Use the new ready index. Choose lexical, semantic cosine or hybrid rank fusion. Semantic queries are encoded by the same pinned local model/runtime; caller vectors are refused for these indexes. Reports and saved traces retain the embedding profile. A lexical baseline uses lexical retrieval on the same versioned qrels; vector baselines use their selected retrieval mode.

The API exposes project-scoped `/embedding-spaces/`, `/embedding-spaces/profile/`, `/embedding-spaces/{space_id}/encode/`, and `/embedding-builds/` with progress, cancel and retry actions. Encode accepts 1–16 nonempty texts, each at most 32 KiB and 256 actual model tokens including special tokens. The runtime requires at least 1 GiB host memory for its worker profile. Package versions, CPU architecture, model/tokenizer hashes and worker build code are frozen in each build's runtime identity.

## Storage and publication

`ChunkEmbedding` stores native variable-dimension pgvector vectors with a unique `(chunk, space)` key and content/runtime/vector checksums. Each space owns a partial cosine HNSW expression index casting vectors to `vector(384)`. New spaces never reuse another space's rows. Different dimensions require a newly supported model profile and index, rather than coercing an existing space.

Worker claims, fenced writes and final publication use the existing durable job protocol. Before READY publication, every frozen source, current access/policy, runtime pin, row count, shape, norm and checksum is rechecked. Cancellation, failed inference, stale leases or a partial cache cannot mark an index ready. A bounded exact pgvector fallback prevents ANN post-filtering from silently underfilling the requested authorized results. Retrieval still applies current document revocation, deletion and project grants. Lexical indexes inherit their knowledge base's access; new embedding spaces, builds and vector indexes additionally carry their build project.

Existing JSON embeddings remain readable for legacy operator-created indexes; this worker never writes JSON vector fields. PCA reads checked native vectors for the selected space without copying them into a legacy global chunk embedding. Generic job creation/update/deletion/cancellation cannot bypass the owned embedding-build API or its accounting.

CPU functional evidence does not qualify CUDA, ROCm, XPU, Metal, customer relevance, fine-tuned weights or independently exported embedding candidates. See the dated [verification report](verification/task30-embedding-foundation-2026-10-23/report.md).

Primary references: [fixed MiniLM model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41), [Sentence Transformers model API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html), [PyTorch CPU installation](https://pytorch.org/get-started/locally/), [pgvector partial expression indexing](https://github.com/pgvector/pgvector#can-i-store-vectors-with-different-dimensions-in-the-same-column).
