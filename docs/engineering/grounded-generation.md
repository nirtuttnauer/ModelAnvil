# Actual local grounded generation

The RAG workspace can run one local CPU text model against the same question with no evidence, retrieved evidence, or 1–5 human-selected chunks from the current frozen index. This is actual greedy model inference through the shared Safetensors runtime. Retrieval traces and retrieval-only comparisons retain their existing, separate semantics.

## Operator setup

Install the base and optional CPU embedding requirements with the pinned Python 3.12 environment. The same Torch/Transformers packages serve the decoder. Bootstrap is an explicit operator network action; generation requests never download weights.

```sh
python -m pip install -r requirements.txt -r requirements.embeddings.txt
export MODELANVIL_RAG_DECODER_CACHE=/absolute/path/to/rag-decoder-cache
python manage.py cache_rag_decoder
python manage.py migrate
python manage.py setup_rag_decoder --project PROJECT_UUID --accepted-license apache-2.0
```

The fixed qualification model is `HuggingFaceTB/SmolLM2-135M-Instruct` revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`, under Apache-2.0. [The pinned file manifest](../../modelanvil/rag/decoder-pins.json) verifies all seven files, including its upstream model card. `MODELANVIL_RAG_DECODER_DIR` can instead point at an absolute directory containing those exact files. Registration is idempotent for a project/profile and publishes immutable verified runtime artifacts. Registration alone does not certify a successful load.

In RAG, select a ready index and use **Answer with a local model**. The UI supports existing imported Safetensors snapshots whose architecture is supported by the shared runtime. The qualified fixed model fits the existing 300M parameter/1 GiB weight default import bounds. There is no GPU qualification or fallback to the character reference model. Requests execute synchronously on the existing local CPU runtime lease; closing the browser request does not claim to cancel underlying inference.

## API and receipts

`POST /api/v1/index-versions/INDEX_UUID/generations/` accepts `query`, `model_version`, `condition` (`none`, `retrieved`, `human`), `retrieval_mode`, `top_k` (1–5), `max_tokens` (1–128, default64), `overflow_policy`, and human-only `human_chunk_ids`. Generation uses temperature0, seed42, the snapshot's chat template and at most2048 tokens. Exact serialized input and output reserve must fit before inference. The default overflow policy fails; explicit `omit_optional_evidence` removes lowest-ranked evidence while preserving the required question. An empty evidence set produces a policy abstention without a model forward pass.

`GET` returns at most20 saved runs whose current source, index and model authorization/pins remain valid. Viewer access is read-only; generation follows the existing engineer role requirement. Receipts retain model/tokenizer/file hashes, source chunk/document hashes and revisions, index manifest/configuration, retrieval settings, prompt/template hashes, decoding settings, runtime package versions, exact usage and elapsed time. Source and model access are checked again after inference. Withdrawn sources/models withhold saved outputs; this is access withdrawal, not knowledge erasure.

`answered`, `model_abstain`, `policy_abstain` and `validation_refusal` are distinct. Accepted citations map model labels to the exact supplied currently accessible chunk IDs. Unknown references or missing citations with evidence are refused; the server never invents citations for an uncited answer. Membership validation **does not establish factual correctness or entailment**. Raw output is available only within the same authorized run and may contain a rejected answer. Question drafts stay in browser memory.

## Reproduce the qualification

The required PostgreSQL CI job boots the checksum-verified public decoder and MiniLM caches, uses offline inference, runs the actual worker-built vector index and all three generation conditions, then saves the measured JSON as a commit-named artifact. [Measured local report](verification/task70-grounded-generation-2026-10-23/report.md) documents the small authored CC0 fixture and its limitations.

```sh
export MODELANVIL_EMBEDDING_MODEL_DIR=/absolute/path/to/pinned-minilm
export MODELANVIL_RAG_DECODER_DIR=/absolute/path/to/pinned-smollm2
export MODELANVIL_RAG_GENERATION_REPORT=/absolute/new/report.json
# Configure PostgreSQL/pgvector and the local RabbitMQ test broker.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python manage.py test modelanvil.rag.test_generation --noinput
```

Tests assert structure, citation membership, exact token accounting, required-question preservation, abstention categories, unknown-source refusal and revocation during actual generation. They do not assert exact model answer strings. A one-question fixture is software qualification, not a general RAG quality benchmark.
