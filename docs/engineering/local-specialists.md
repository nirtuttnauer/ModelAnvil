# Local OCR and typed decisions

The Specialists screen provides two independently bounded local inference contracts:

- **GLM-OCR** text recognition from PNG/JPEG and scanned PDF on `mlx:0`, using the native `mlx-vlm` implementation with remote code disabled.
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
| `POST /api/v1/specialists/upload-image/` | Multipart `file`; commits original PNG/JPEG/PDF bytes and returns a scoped artifact reference |
| `POST /api/v1/specialists/ocr/` | `model`, `image_artifact`, `device: mlx:0`, per-page `max_tokens`; returns text, measured usage, immutable JSONL artifact and source/model provenance |
| `POST /api/v1/specialists/decisions/` | `model`, explicit `device`, `state`, `questions`; returns typed answers, measured usage and checkpoint provenance |

OCR admits a source of at most 8 MiB. Single images allow 2 million pixels and 28–2048 pixels per edge. PDFium 5.14.0 renders scanned PDFs with 1–5 pages, finite 14–2000-unit page canvases, a maximum scale of 2, at most 2 million pixels per page and 6 million pixels across the document. Encrypted PDFs are refused, including those with an empty opening password. Every page must produce complete nonempty output; one failed page refuses the whole document. Page numbers, rendered pixel hashes, dimensions, renderer version and the original PDF hash are preserved. All pages share one source group so they cannot leak across train/validation/test splits. Uniform or nearly uniform pages are refused before allocating the model: the blank-page probe otherwise produced an invented website address. This conservative pixel check does not establish text correctness on other images. It rejects animation and unsupported formats. EXIF orientation is applied and pixels are converted to RGB, with dimensions and the transformation recorded. Processor admission is at most 4096 input tokens, checked before inference. Output is capped at 32–1024 tokens per page; empty output or reaching the limit refuses the entire result and publishes no partial text. No layout boxes, table schema or confidence scores are invented.

Laya admits 1–8 questions and at most 32,000 JSON bytes. Choice and score support 2–8 textual options. Requests reject unknown fields, nonfinite JSON, literal mask tokens, indistinguishable options and any state, option or instruction truncation. State JSON is canonicalized before prediction. The SDK's ineffective act/escalate score is omitted; ModelAnvil never executes an action from these decisions. Domain calibration is explicitly pending.

Each request stages verified project-scoped files into a private temporary directory, holds the existing device lease (`mlx:0` and `mps:0` share Apple admission), then starts a pinned child interpreter with `-I`, a curated environment, offline Hub/Transformers settings and no ambient credentials. Device availability and recommended process headroom are checked; SDK GPU fallback warnings are fatal. The child inherits the actual lock descriptor, so admission remains held if the API process dies while inference is still running. The child has its own 120-second wall alarm and exits after the request, releasing allocations. Parent timeout is 120 seconds; CPU and output-file limits also apply. macOS does not offer a usable hard address-space limit for Metal. Offline settings are library controls, not an OS network sandbox. Admission coordinates cooperating same-user processes; it does not reserve the GPU against unrelated applications. HTTP disconnect cancellation is not yet implemented.

Every successful/failed inference gets a principal-scoped request record with input/output digests, configuration and measured usage. OCR additionally commits canonical text envelopes with original document identity, model/processor pins, content hash and stable sample/group IDs. Lineage joins image and model manifest to OCR output. Publishing that committed output through the dataset preparation API runs the existing source detection/deduplication/protected-content and chunk checks. The UI requires reviewing the extracted text before publication; this is not a persisted human qualification campaign.

## Verified checkpoint and remaining scope

`verification/modelanvil-specialists-2026-10-12.json` records real authenticated local HTTP execution: exact recovery of a four-line synthetic receipt on Metal, six correct department routes, all three decision primitives on MPS, explicit CPU execution, oversized/mask-token refusals, token-limited OCR refusal and immutable dataset publication. This is a small synthetic smoke suite, not representative OCR/model quality or probability calibration. The temporary qualification API key was deactivated. A second actual HTTP pilot is recorded in `verification/modelanvil-scanned-ocr-2026-10-12.json`: two image-only PDF pages contain no embedded text, both match their authored text exactly, and page-aware output publishes with lineage. Six-page, encrypted and blank PDFs are refused without partial publication.

Larger independent OCR corpora, decision domain calibration, vision fine-tuning and other vendor GPU qualification remain pending. Layout extraction and durable specialist execution are described below. The selected Mac is the only accelerator used for these checks.

## Layout extraction and durable specialist jobs

The curated layout recipe uses [PaddlePaddle/PP-DocLayoutV3_safetensors](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) at `e4f489dc536556fc1be02b973ba06756e0d4a2ac` (Apache-2.0). Its 133,270,468-byte weights and both configuration files are pinned in `specialist_pins.json`. The [Transformers implementation](https://huggingface.co/docs/transformers/model_doc/pp_doclayout_v3) provides model reading order; the application preserves that order instead of sorting boxes by their coordinates. The optional environment adds exact `torchvision==0.24.0`; the core API environment is unchanged.

Acquire the layout recipe through `POST /api/v1/specialists/acquire/` with `kind=layout` and accept its displayed license. Supply its registered UUID as `layout_model` on OCR requests. The detector runs on CPU; region OCR runs on Metal with both cooperating device leases held through child lifetime. Coordinates refer to the normalized RGB page raster, in `[xmin, ymin, xmax, ymax]` pixels, after PDF rendering or EXIF normalization. The threshold is fixed at 0.5; up to 24 regions across the entire bounded document are accepted. Nonfinite/empty geometry, no detections, excess regions, empty recognition or token exhaustion refuses the whole result. Image, chart and seal regions retain geometry without inferred text. Text, table and formula crops use the corresponding recognition prompt. Table/formula output remains raw model text with its detected label; typed table/formula parsing is not qualified.

Output includes each region's label, confidence, detector order, box, actual padded crop box, RGB crop digest and recognized text. Canonical dataset blocks retain region coordinates/order and original source groups, with model/layout/source/runtime hashes and layout-model lineage. Publication remains subject to source checks and human review. The page shows a spatial region map and the ordered text list; it does not pretend the map is the source image.

### Run a durable worker

Create an enabled, currency-free budget policy with unit `specialist_attempts` and an active envelope worker pool. Start an operator-controlled local worker with the same artifact storage/database and isolated runtime as the API:

```sh
MODELANVIL_SPECIALIST_PYTHON=/absolute/path/to/specialist-env/bin/python \
  python manage.py run_specialists --pool-id POOL_ID --name local-ocr --device mlx:0
```

Use separate names/workers for `cpu` (layout-only/Laya CPU) and `mps:0` (Laya MPS). The command probes exact runtime dependencies/device availability before registration and advertises the exact execution-code digest. It refuses to repurpose an existing worker with different identity/capabilities. Queueing requires a matching registered worker; registration/probe is not a model-quality qualification.

`POST /api/v1/specialists/jobs/` takes `kind`, a nested specialist `request`, `pool`, `budget_policy`, and `idempotency_key`. Inputs, model manifest, source bytes, optional layout manifest and runtime digest are frozen. Replays under the same principal/project/key return the original request; changed inputs conflict. Three attempt units are reserved before job creation in the same transaction. Each execution start writes an idempotent usage event keyed by the durable attempt UUID; successes and failures settle the started units and free unused quota. These units measure execution attempts, not monetary cost or tokens. Actual model token counters remain separate inference evidence. A retry reclaims the unused reservation only within the original budget period and available quota, with a maximum of three claims.

`GET /api/v1/specialists/jobs/` lists the 20 latest accessible requests. `GET /api/v1/specialists/jobs/{request_id}/` returns status/attempt/error and restores a completed result. Dedicated `/cancel/` and `/retry/` actions preserve ownership and accounting. Generic job writes/deletion/cancellation are refused for specialist-owned jobs, and job/attempt APIs inherit the request's project restrictions.

The child is supervised with renewable leases every 0.5 seconds, cancellation/fence checks and a 120-second deadline. Cancellation kills/reaps the child before admission is released. An API/worker crash leaves a durable job for reconciliation; an orphan child retains its device descriptor until it exits or its own deadline fires. A verified complete result checkpoint can be reused after a worker crashes between computation and commit. Publication and final accounting happen in the successful attempt's fence transaction; stale workers cannot publish, and cancellation wins over a staged success. Pool egress policy is checked again at checkpoint and publication.

Recovery verifies and reuses completed page checkpoints, then processes missing pages. A complete result checkpoint also survives process loss. See [resumable pages and data recipes](resumable-pages-and-data-recipes.md). The worker runs independently of the API. Schedule the existing lease reconciler in the operator environment to recover dead workers.

Qualification is a small authored Mac pilot. Representative multilingual documents, tables/formulas and Laya domain calibration remain pending, as do other GPU families.

Trusted local specialist workers refresh their observed connection while idle and mark themselves offline when they stop. `--once` polls and executes at most one job, then exits offline; keep the normal command running while queueing work from the browser.
