# Local OCR and typed decisions

The Specialists screen provides two independently bounded local inference contracts:

- **GLM-OCR** text recognition from PNG/JPEG on `mlx:0`, using the native `mlx-vlm` implementation with remote code disabled.
- **Laya** choice, ordinal score and yes/no probability over English text or JSON on explicit `cpu` or `mps:0`. The root English checkpoint is a typed decision model, not a chat or video model.

Model acquisition uses the existing fenced, resumable import worker. The catalog is fixed to the revisions, byte sizes and SHA-256 values in `modelanvil/runners/specialist_pins.json`; every file, tokenizer and processor asset is verified. License acceptance is explicit. These specialists are excluded from the causal chat catalog. Model versions stay draft, immutable and unqualified for production.

## Install on Apple Silicon

Keep the API/training environment intact. This optional Mac profile was exercised with Python 3.12:

```sh
python3.12 -m venv .venv-specialists
.venv-specialists/bin/python -m pip install -r requirements.specialists.txt
export MODELANVIL_SPECIALIST_PYTHON="$PWD/.venv-specialists/bin/python"
```

Restart the API with this absolute interpreter path. Select a pool with a live `model_import` worker, accept the displayed license and acquire the desired checkpoint in Specialists. Follow the acquisition in Workflows and Refresh after completion. Exact transitive package versions are pinned separately; this does not upgrade the existing training Transformers runtime.

Primary model/runtime sources: [Laya checkpoint](https://huggingface.co/convaiinnovations/laya), [Laya SDK](https://github.com/NandhaKishorM/laya), [GLM-OCR](https://github.com/zai-org/GLM-OCR), [converted native MLX snapshot](https://huggingface.co/mlx-community/GLM-OCR-bf16).

## API and execution limits

All endpoints require an active tenant/project. Viewing the catalog requires viewer access; acquisition, upload and inference require engineer access. Worker credentials cannot call them.

| Endpoint | Input / result |
| --- | --- |
| `GET /api/v1/specialists/` | Accessible models and immutable acquisition plans |
| `POST /api/v1/specialists/acquire/` | `kind`, `name`, `pool`, exact `accepted_license`, `idempotency_key`; returns the import job |
| `POST /api/v1/specialists/upload-image/` | Multipart `file`; commits original PNG/JPEG bytes and returns a scoped artifact reference |
| `POST /api/v1/specialists/ocr/` | `model`, `image_artifact`, `device: mlx:0`, `max_tokens`; returns text, measured usage, immutable JSONL artifact and source/model provenance |
| `POST /api/v1/specialists/decisions/` | `model`, explicit `device`, `state`, `questions`; returns typed answers, measured usage and checkpoint provenance |

OCR admits one image of at most 8 MiB, 2 million pixels and 28–2048 pixels per edge. It rejects animation and unsupported formats. EXIF orientation is applied and pixels are converted to RGB, with dimensions and the transformation recorded. Processor admission is at most 4096 input tokens, checked before inference. Output is capped at 32–1024 tokens; empty output or reaching the limit refuses the entire result and publishes no partial text. No layout boxes, table schema or confidence scores are invented.

Laya admits 1–8 questions and at most 32,000 JSON bytes. Choice and score support 2–8 textual options. Requests reject unknown fields, nonfinite JSON, literal mask tokens, indistinguishable options and any state, option or instruction truncation. State JSON is canonicalized before prediction. The SDK's ineffective act/escalate score is omitted; ModelAnvil never executes an action from these decisions. Domain calibration is explicitly pending.

Each request stages verified project-scoped files into a private temporary directory, holds the existing device lease (`mlx:0` and `mps:0` share Apple admission), then starts a pinned child interpreter with `-I`, a curated environment, offline Hub/Transformers settings and no ambient credentials. Device availability and recommended process headroom are checked; SDK GPU fallback warnings are fatal. The child exits after the request, releasing allocations. Parent timeout is 120 seconds; CPU and output-file limits also apply. macOS does not offer a usable hard address-space limit for Metal. Offline settings are library controls, not an OS network sandbox. Admission coordinates cooperating same-user processes; it does not reserve the GPU against unrelated applications. HTTP disconnect cancellation is not yet implemented.

Every successful/failed inference gets a principal-scoped request record with input/output digests, configuration and measured usage. OCR additionally commits canonical text envelopes with original image identity, model/processor pins, content hash and stable sample/group IDs. Lineage joins image and model manifest to OCR output. Publishing that committed output through the dataset preparation API runs the existing source detection/deduplication/protected-content and chunk checks. The UI requires reviewing the extracted text before publication; this is not a persisted human qualification campaign.

## Verified checkpoint and remaining scope

`verification/modelanvil-specialists-2026-10-12.json` records real authenticated local HTTP execution: exact recovery of a four-line synthetic receipt on Metal, six correct department routes, all three decision primitives on MPS, explicit CPU execution, oversized/mask-token refusals, token-limited OCR refusal and immutable dataset publication. This is a small synthetic smoke suite, not representative OCR/model quality or probability calibration. The temporary qualification API key was deactivated.

Scanned PDF rendering, layout extraction, larger independent OCR corpora, decision domain calibration, durable/cancellable budgeted specialist jobs, vision fine-tuning and other vendor GPU qualification remain pending. The selected Mac is the only accelerator used for these checks.
