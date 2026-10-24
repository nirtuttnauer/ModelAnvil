# Continued pretraining on versioned text corpora

Continued pretraining updates the pinned pretrained SmolLM2-135M transformer using causal next-token loss on plain text. Initialization uses the verified pretrained weights, not random weights. This bounded CPU implementation adds reproducible source mixtures, inherited protected splits, actual loss/token/throughput measurements, durable optimizer and data-cursor recovery, and independently loadable candidate exports. Hardware and customer-quality qualification remain separate.

## Build and launch

Prepare and publish each original plain-text source through the existing dataset preparation flow. In Training, open **Advanced settings**, choose **CPU/GPU continued pretraining**, then **Build a weighted text corpus**. Select one to four original source revisions, relative weights, a training-row count, a selection seed and a new corpus name. **Publish and select corpus** saves a new immutable revision and selects it for training. It defaults the training plan to three explicit updates. Choose the matching pinned base, tokenizer, dedicated worker, runtime manifest and step budget; review preflight before launching.

An Engineer can also `POST /api/v1/pretraining-corpora/` with the active project header:

```json
{
  "name": "Astronomy with protected general text",
  "components": [
    {"revision_id": "<published-domain-revision-uuid>", "weight": "3"},
    {"revision_id": "<published-general-revision-uuid>", "weight": "1"}
  ],
  "train_samples": 12,
  "seed": "reviewed-selection-v1"
}
```

The response includes the corpus revision's database ID and UUID, manifest/recipe digests, component pins, exact quotas and split counts. Supply the numeric corpus ID as `dataset_revision` to the existing training preflight and launch endpoints with `recipe_type: "continued_pretraining"`. An authenticated Viewer can list accessible, currently valid corpora with `GET` on the same endpoint; raw source text is not returned. Responses are not cached. A single original published plain-text revision remains an explicit one-source corpus without the mixture builder.

Register the exact local snapshot and one dedicated CPU worker with `setup_gpu_training --device cpu --recipe continued_pretraining`, supplying the existing tenant/project, a unique name, verified local model directory and canonical text JSONL. Despite its historical command name, the explicit CPU selector registers the separate CPU contract. Registration does not launch a job or download models. The setup command validates its initial source's protected splits; select the compiled mixture in the launch request afterward. Worker hosts must use the same execution source and exact package pins. Restart/re-register changed workers rather than forcing an old checkpoint through a new contract.

## Corpus and recovery contract

The source is `HuggingFaceTB/SmolLM2-135M` at `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`; the base Safetensors SHA-256 is `80521b40281d6ce74e35c9282c22539e75aa0ac8578892b2a59955ef78d55da1`. The CPU profile uses FP32, one thread, a dedicated device lease, at least 16 GiB observed host memory, 1–20 updates, at most 1,000 total rows and 2–128 actual tokens per consumed sample. Torch 2.13.0, Transformers 5.14.0, Safetensors 0.8.0 and Tokenizers 0.22.2 are required. No input is silently truncated, no GPU fallback is selected and no quantized/mixed-precision recipe is substituted.

Each original prepared manifest and the complete frozen corpus are bounded to 2 MiB. Sources must be committed local artifacts, accessible published revisions and original shards rather than nested mixtures. Finite positive weights have at most three decimal places. Exact integer largest-remainder quotas select training rows without replacement using a seeded local generator; the selected rows are interleaved once and frozen. A zero quota or insufficient source rows is refused, without weight redistribution. Runtime updates cycle that recorded order. Original validation and test rows retain their splits; they are never borrowed to fill training quotas. Duplicate identifiers, normalized duplicate text, and source groups crossing splits are refused across all shards. This normalized-content guard does not prove absence of semantic contamination.

This first slice materializes bounded shards and a frozen manifest; it does not claim streaming an unbounded corpus, distributed sharding or resuming an external stream. The complete manifest hash, recipe hash, normalized weights/quotas, original source manifest pins and lineage edges identify the actual mixture. Training records the exact corpus, source revision and logical cursor for every committed update. Validation loss uses validation rows only; the training engine never consumes the test split.

Checkpoint state includes weights, Adam moments/update count, exact runtime/build/tokenizer/data pins, completed update count, next frozen sample offset and completed epochs. Dropout is disabled and no runtime stochastic sampler is used; the recovery envelope therefore needs no mutable sampler RNG. Checksum verification alone cannot authorize a changed logical cursor. Recovery is scoped to the same deterministic CPU build, packages, source bytes and host contract, rather than claiming cross-device bitwise equivalence. Validation renews/checks the attempt lease cooperatively between samples; each native forward remains an indivisible operation.

Preflight accounts for checkpoint cadence, FP32 weights and optimizer state, candidate/staging headroom, device capacity and the step budget. On the measured three-update run it reserved 8,077,059,440 bytes of storage and three steps. Host memory observation is not a global free-memory reservation. Attempt-bound leases fence expired workers; cancellation settles only committed updates. Source access, tombstones and bytes are checked at launch, each update and checkpoint, recovery, candidate publication and subsequent candidate download. Withdrawal prevents new publication and withholds an earlier corpus-derived candidate. It does not erase already downloaded independent copies.

## Independent evaluation and available-Mac evidence

Run the opt-in qualification in a new private directory using the verified local snapshot:

```sh
python scripts/qualify_continued_pretraining.py \
  --model-dir /verified/smollm2-base --device cpu \
  --output /private/new-continued-pretraining-proof
```

It uses authored CC0 astronomy and general-text sources, the actual preparation/publication API, original protected splits and a fixed 3:1 mixture. Its bounded pilot must actually update on both source shards. The immutable ZIP is reopened and every file verified. An independent consumer imports neither Django nor ModelAnvil, reloads the selected candidate on CPU and scores **every original test row**, with train/validation IDs and source groups forbidden. `score_continued_pretraining.py` reports separate token-weighted domain and protected test losses, a domain-loss decrease check and a protected-loss regression ceiling of 5%. These authored loss proxies do not establish general protected capabilities, customer quality or production readiness. A failed proxy is retained rather than changing test rows or promoting the candidate.

The candidate is selected by best measured validation loss; recovery equivalence compares final committed checkpoint weights even when the selected candidate is earlier. Actual expired-lease recovery, stale-attempt refusal, cancellation, corrupt input, a rehashed invalid cursor and source withdrawal are separately exercised. Fixture credentials are revoked, synthetic tenants suspended, workers offline/drained, budgets disabled and jobs/attempts/reservations/device claims settled on completion. Keep model archives, databases, credentials and raw logs private.

The [dated evidence directory](verification/task26-continued-pretraining-2026-10-24/) contains actual measurements, source/file hashes, independent consumer receipts, adverse-case results and desktop/mobile UI proof. CPU mechanics and bounded authored test losses are the scope of this implementation. Unbounded streaming, other architectures, random-initialization scratch training, unavailable vendor/multi-GPU execution, customer-selected domains and production capacity/quality retain their own gates.

## Historical GPU pilot

The [12 October Mac receipt](verification/modelanvil-continued-pretraining-mac-2026-10-12.json) records the earlier one-source MPS pilot on the pinned engineering-document corpus, independent CPU/MPS inference, protected-loss comparisons and recovery. It is historical evidence for that source/build/device. The current weighted-corpus change requires refreshed runtime manifests and does not promote that older receipt to the new build or unavailable vendors. Existing `qualify_hf_gpu.py --device mps:0 --recipe continued_pretraining --samples /canonical/text.jsonl` remains the single-source GPU pilot entry point; the new command above supplies the distinct bounded CPU mixture and original-test evaluation.
