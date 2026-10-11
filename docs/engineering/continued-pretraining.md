# Bounded continued pretraining

The local transformer runtime supports `continued_pretraining` from the exact pretrained SmolLM2-135M snapshot, using all model parameters and FP32 AdamW on a named GPU. It consumes actual unformatted text from a published versioned corpus. It does not initialize random model weights.

The current envelope is one corpus component at weight 1.0, at most 1000 rows, 2–128 tokenizer tokens per row and 1–1000 updates. Corpus revision, manifest digest, published sample ordering, tokenizer, validation content and pretrained source are pinned. Training follows published manifest order cyclically; dropout is disabled and the sampler consumes no RNG. Saved Adam moments plus the committed step reproduce the next update exactly. This bounded implementation does not yet provide configurable multi-corpus mixtures or streaming shards.

Register the verified local pretrained snapshot and canonical text JSONL:

```sh
python manage.py setup_gpu_training \
  --tenant-id TENANT_UUID --project-id PROJECT_UUID --name domain-pretraining \
  --model-dir /path/to/smollm2-135m --samples /path/to/canonical-text.jsonl \
  --device mps:0 --recipe continued_pretraining --steps 3
```

Select **GPU continued pretraining** and matching resources in Training, then preview and launch. Registration performs no model download or training. Preflight checks the published protected splits, exact base/tokenizer/runner contract, worker, named device admission, budget and projected storage. A nonempty validation split is required. Chat-role data and truncation are refused.

Before and after each update, the worker measures token-weighted negative log likelihood over the protected validation split. Validation runs without gradients; the test split is never consumed by the trainer. Telemetry records training prediction tokens, cumulative prediction tokens, validation token counts, validation elapsed time and training throughput. The reported training throughput includes the post-update training loss pass and excludes the separately timed validation pass.

Checkpoints, expiry recovery, cancellation, accounting and candidate publication use the same fences as full SFT. Completed candidates support verified Safetensors ZIP download and CPU/MPS chat. An independent consumer measures loss on consumed training examples and held-out source groups, and checks inference against the API.

The [Mac evidence](verification/modelanvil-continued-pretraining-mac-2026-10-12.json) records a three-update pilot on the pinned deduplicated engineering-document corpus, training-loss decrease, validation/test regression within five percent, exact final-weight recovery, one-step cancellation settlement, corruption rejection without charging steps, and independent CPU/MPS inference. This is a bounded implementation and quality pilot, not production or broader domain qualification. NVIDIA, AMD and Intel qualification remains pending.

```sh
python scripts/qualify_hf_gpu.py --model-dir /path/to/smollm2-135m \
  --device mps:0 --recipe continued_pretraining --samples /path/to/canonical-text.jsonl \
  --output /path/to/new-qualification-directory
python scripts/qualify_candidate_chat.py --qualification /path/to/new-qualification-directory
```
