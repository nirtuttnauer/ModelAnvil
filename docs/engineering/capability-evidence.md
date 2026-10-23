# Capability evidence audit

Current delivery addendum (23 October 2026): see the [integration inventory](integration-inventory.md), [operation-specific capability baseline](supported-capabilities.md), and dated verification reports. The original review below is historical; current dependency pins still require fresh GPU qualification. Customer discovery remains blocked on customer input.

For current operation-specific support, artifact references and remaining qualification, see the [21 October capability baseline](supported-capabilities.md). This audit retains its original scenario-by-scenario review scope.

## Current document capability evidence — 23 October 2026 (TASK-62)

Evidence is operation-specific. A working parser or worker does not qualify OCR recognition. [Fresh software checks and remaining mixed-document gap](verification/task62-documents-2026-10-23/report.md) include 46 passing tests and authored source/raster receipts. No document model path currently has hardware-qualified evidence for the current dependency/build pins.

| Capability | Current evidence level | Verification files | Bounds and pending work |
| --- | --- | --- | --- |
| CSV / JSON source extraction and immutable dataset publication | Integrated execution: actual standard-library parsing and frontend-client HTTP publication | `data/test_source_import.py`, `api/test_dataset_preparation_http.py`, `api/test_dataset_preparation.py` (all under `modelanvil/`) | 16 MiB source, 10,000 rows; explicit string text field and optional source-group mapping; not image/audio extraction |
| DOCX main-body paragraphs and immutable publication | Integrated execution: actual ZIP/XML extraction and frontend-client HTTP publication | `modelanvil/data/test_source_import.py`, `modelanvil/api/test_dataset_preparation_http.py` | 16 MiB compressed input and expanded archive, 1,000 entries; no external relationships, headers/footers, visual reading-order or typed table/layout guarantee |
| Embedded-text PDF page extraction and publication | Integrated execution: actual pinned isolated parser and frontend-client HTTP publication | `modelanvil/data/test_pdf_import.py`, `modelanvil/api/test_dataset_preparation_http.py` | `pypdf==6.21.2`; 100 pages, 1 MiB decoded/page, 8 MiB aggregate/output, 15s parent timeout; POSIX only; any blank/scanned page refuses the whole document |
| Image / scanned-PDF page rasterization | Integrated execution: actual Pillow/PDFium pixels and page digests, without recognition | `modelanvil/runners/test_specialist_runtime.py`; [fresh mixed-page receipt](verification/task62-documents-2026-10-23/fixtures.json) | 8 MiB; PNG/JPEG or 1–5 PDF pages; bounded dimensions, <2M pixels/page and 6M/document; blank/encrypted sources refused |
| OCR text recognition and page-aware dataset publication | Current model execution: configuration only. Controlled model output: simulation. Archived older Mac pilot: historical integrated execution | `modelanvil/api/test_specialists.py`, `scripts/specialist_runtime.py`; historical `verification/modelanvil-scanned-ocr-2026-10-12.json` | Matching isolated MLX runtime/device/model needed. Current recognition and language coverage unqualified; historical authored English smoke is not multilingual/document-quality evidence |
| Layout detector order, geometry and region OCR | Current model execution: configuration only. Controlled model output: simulation. Archived older Mac pilot: historical integrated execution | `modelanvil/api/test_specialists.py`, `modelanvil/api/test_specialist_jobs.py`; historical `verification/modelanvil-layout-jobs-2026-10-12.json` | Pinned detector CPU + OCR MLX; threshold 0.5, 1–24 regions/document; raw table/formula text, no qualified typed reconstruction or arbitrary reading-order accuracy |
| Durable specialist job admission, resume, cancel, retry and publication fencing | Integrated control-plane execution with simulated model outputs | `modelanvil/api/test_specialist_jobs.py`, `modelanvil/runners/specialist_jobs.py` | Three reserved attempt units/max claims, matching runtime/worker required; 120s child supervision. Retry/accounting tests do not qualify recognition or actual hardware cancellation |

TASK-62's end-to-end mixed PDF/DOCX/CSV publication **including recognized scanned-page content remains blocked** on the current specialist runtime/device path. The user directed the factory to skip this blocker and continue independent work. TASK-21 and TASK-33 retain their approved scopes; overlap notes are recorded in Aftur. See [source import](source-import.md), [specialist bounds](local-specialists.md) and the dated report.

TASK-1 · 11 October 2026 · Local source and automated-test audit

Levels describe evidence, independently of a saved workflow status:

- **Configuration only:** metadata or a saved pointer exists; execution is unverified.
- **Simulation:** fixtures, synthetic inputs, fixed metrics or caller-supplied scores exercise domain behavior.
- **Integrated execution:** a real callback executes within an integration test; its model, independence and hardware remain unverified.
- **Hardware qualified:** pinned input/output artifacts, runtime versions, hardware, independent inference and operational checks have been verified within a documented envelope. No current path has this level.
- **Unknown:** old records lack execution provenance. A completed/ready/qualified label alone is insufficient.

TASK-21 adds verified local CSV/JSON/DOCX extraction and immutable publication, with original-source hashes, locations and protected split groups. Actual frontend-client HTTP and browser evidence is recorded in [source import](source-import.md). This bounded increment does not qualify synthetic inference, PDF parsing or durable recipe execution.

TASK-4 adds a separate worker path for `modelanvil.cpu-character-sft.v1`: it reads verified published text, encodes a pinned character vocabulary, loads pinned base tensors, executes online SGD, and publishes checkpointed progress through live worker fences. A 20-step browser run and an independent standard-library consumer are archived in the [CPU reference report](qualification-reports/text-finetuning-runtime.md). Evidence remains scoped to this small local CPU model and awaits developer review; it does not qualify a production release, GPU runtime or general language model. Other recipes and the interactive training endpoint remain synthetic numerical fixtures.

Evaluation without a runner echoes expected answers and is simulation. A supplied callback is integrated execution with unverified hardware. The server records this origin in the evaluation protocol. API serializers expose read-only `execution_evidence` on training, alignment, model versions, evaluations and release versions. Older evaluations are unknown. Client-supplied metadata cannot qualify a model. Production release qualification and live promotion fail closed while a trusted runtime qualification path is unavailable; exceptions cannot waive that requirement. An explicit domain-test simulation can move endpoint pointers, always with pending readiness and simulation provenance. It is unavailable as a production API bypass.

Metadata-only release candidates export an explicitly unverified preview. Candidates backed by committed compatible CPU bundles export actual weight bytes, exact checksums and bounded local loading evidence; this is not independent or production qualification. Quantization retains deterministic fixture numbers but reports simulated origin and `evaluation_passed: false`. Alignment fixtures cannot qualify a production model. Browser training, evaluation, models and release screens describe these limits and evaluation rows display origin.

TASK-13 adds `modelanvil.smollm2-gpu-sft.v1`: one immutable published SmolLM2-135M snapshot, its actual tokenizer, published protected train split, FP32 AdamW and streamed Safetensors checkpoints. The [MPS pilot and recovery report](verification/task13-gpu-2026-10-11.md) verifies three real GPU updates, exact resumed weights, fenced cancellation/accounting and independent Hugging Face CPU inference. It is integrated execution for that local envelope; production and hardware qualification flags remain false. CUDA, ROCm and XPU selection paths require separate named-device qualification. GPU timing and monetary estimates remain explicitly unknown in preflight.

The [native Apple adapter profile](native-apple-adapter-training.md) adds actual four-bit affine frozen-base MLX training, exact Adam recovery and safe standard MLX exports. It records measured implementation evidence and an explicit overall quality failure for the bounded three-step candidate: quantized validation loss slightly exceeds five percent over its unquantized baseline. Production and broader hardware qualification remain false.

The backend/frontend support implementation adds initialized untrained CPU bases, validated immutable evaluation suites and an explicit actual CPU character inference action. The action verifies committed artifact bytes and tokenizer compatibility, records candidate/baseline outputs and Wilson intervals, and refuses unsupported/corrupt bundles without scores. RAG imports actual text into source revisions and pinned lexical indexes. Context authoring saves ordered blocks atomically and estimates the exact serialized prompt including wrappers. Durable job access, Dataset Bank admission/accounting and SPDX persistence are checked by HTTP and regression tests. See the [support report](backend-frontend-support.md) for checked scope and limits.

The [bounded CPU alignment path](cpu-character-alignment.md) consumes committed training/held-out preference bytes and actual character-model bundles. It performs DPO, real frozen-encoder Bradley–Terry head training, sampled learned-reward PPO and verifier RL. Checkpoints and candidate publication use claim tokens, input pins and byte digests; usage settles committed steps. Fourteen integration tests with actual API journeys cover changed candidate tensors or reward head, a separate standard-library Safetensors consumer, corruption, input separation, bounds, cancellation and tenant/project/role control. This new path is integrated execution with hardware/production qualification false. It does not turn the older domain alignment fixtures below into qualified results.

## Audit of all 17 R1 scenarios

The `modelanvil.acceptance.test_r1_scenarios` suite is a **domain fixture suite**, not R1 delivery certification. Test names/docstrings describe intended journeys more broadly than their assertions. All rows below refer to that file and its corresponding `test_scenario_NN_*` method. Environment: macOS arm64, CPython 3.12 virtual environment, Django test database on SQLite, CPU only. No GPU, external model runtime, provider storage, Kubernetes, broker cluster or browser pilot was exercised by these scenarios. Database rows and in-memory dictionaries are test artifacts, destroyed at teardown; they are not archived production qualification artifacts.

| Scenario | Evidence exercised by fixture | Level | Remaining qualification gap |
| --- | --- | --- | --- |
| 01 Scratch | Seed, CPU synthetic training loss, checkpoint bytes, fallback eval, local model load/inference | Simulation | Real dataset encoding, declared architecture, independent evaluation and GPU/worker execution |
| 02 Fine-tuning | CPU numerical update and local candidate bundle | Simulation | Load pinned base weights/tokenizer, consume published dataset, qualify worker journey |
| 03 Preference/reward | Preference splitting and DPO/reward fixture metrics/registry rows | Simulation | Real policy/reward weights, held-out predictions and independent runtime |
| 04 Verifier RL | Math task fixture trajectory and exploit flag | Simulation | Real policy updates and independent task evaluation |
| 05 Data diversity | Format reports and dictionary round-trip | Simulation | Real media parsing/rendering/encoding and evidence for each supported format |
| 06 Custom format | Mapper and permission-check calls | Integrated execution (local helper) | Isolated process execution and end-to-end custom training/eval journey |
| 07 Isolation/quotas | Tenant-filtered model query | Integrated execution (SQLite query) | HTTP relationship/action matrix, project grants, quotas/concurrency; separate TASK-2 suite covers selected API boundaries |
| 08 Failure/recovery | Local checkpoint restoration and CPU continuation | Simulation | Worker interruption, stale fence rejection, cancellation and no duplicate commits |
| 09 Portability | Local CPU bundle verification | Simulation | Independent loader and managed/self-hosted/hybrid deployment |
| 10 Release/rollback | Rejected fixture gates, non-qualifying waiver, simulated pointer changes | Simulation | Actual weight export/conversion, serving health and operational rollout/rollback |
| 11 Dataset presets | Local catalog and two inline SVG samples | Integrated execution (local helpers) | Source acquisition, real remote resume/checksums/licensing and private cache boundary |
| 12 Capacity/broker | Three CPU training steps | Simulation | This scenario has **no broker/capacity/recovery assertions**; distributed allocation and duplicate delivery qualification remain open |
| 13 Complete RLHF | Fixture RLHF metrics and negative release invariant | Simulation | Learned reward weights, fresh policy rollout, independent held-out evaluation |
| 14 RAG | Hand-scored retrieval metrics and tombstone row | Integrated execution (local helpers) | Index retrieval/answer execution, HTTP queries and deletion propagation |
| 15 Cluster | Three inline embedding vectors, stored projection, neighbors and table | Integrated execution (local helpers) | True projection algorithm validation, large datasets and keyboard/browser investigation |
| 16 Context | Recipe compilation, deterministic stress fixtures and evidence-position prompt inspection; recall status is `not_run` | Simulation; no measured recall or middle dip | Actual paired model inference, token accounting, isolation and user review |
| 17 Labeling | One manual batch, snapshot, metadata candidate and fixed score callback | Simulation | Both seed modes, two cycles, actual retraining, independent qualification and executor recovery |

## Verification and limits

Run `python manage.py test modelanvil.runners.test_evidence modelanvil.api.test_project_boundaries modelanvil.releases modelanvil.runners.training modelanvil.runners.alignment modelanvil.acceptance` with the repository's `.venv/bin/python`. The trust regressions assert that metadata/incomplete/corrupt weights fail verification; actual inference is invoked; unknown/fallback/callback results never authorize production; and exceptions or legacy qualified labels cannot bypass the runtime gate. Selected HTTP boundary tests cover project/tenant relations and role denials.

Exact results for this audit are recorded in [status](status.md) and [TASK-2 authorization matrix](action-resource-authorization-matrix.md). Passing these tests establishes only their asserted local behavior. A future runtime qualification writer must bind immutable resources, environment and measured artifacts; adding a JSON `hardware_qualified` label must never unlock production.


23 October 2026 — TASK-10 adds the opt-in bounded reviewed-label CPU training/evaluation cycle. [Fresh software and negative-control evidence](verification/task10-labeling-2026-10-23/report.md) records two actual executions and correct candidate rejection; it makes no customer quality or GPU claim. Draft predictions remain imported; advancement is an explicit user action.

23 October 2026 — TASK-11 adds frozen text-index receipts, source-safe saved traces, versioned paired relevance reports and measured PCA with an equivalent table. [Fresh retrieval and revocation evidence](verification/task11-rag-2026-10-23/report.md) qualifies bounded software behavior; model generation, semantic encoder quality and hardware qualification are not inferred.

23 October 2026 — TASK-12 adds ordered immutable recipe authoring, pinned CPU runtime tokenization and actual paired inference with saved case outputs, usage, latency, failure and retention evidence. [Fresh Context Lab verification](verification/task12-context-2026-10-23/report.md) covers bounded local software behavior and negative controls, without a general quality, GPU or prompt-injection safety claim.

23 October 2026 — TASK-14 revalidates browser model discovery, pinned public download/resume and local tensor import, while refusing incomplete tensor/GGUF payloads and exposing current runtime eligibility. [Fresh acquisition evidence](verification/task14-model-import-2026-10-23/report.md) includes a verified public snapshot and restored disposable-project privacy policy; import remains separate from GPU or production qualification.

23 October 2026 — TASK-42 adds attempt-bound local physical-device claims, fresh GPU placement/runtime/budget admission and separately displayed live headroom. [Fresh software coordination evidence](verification/task42-device-admission-2026-10-23/report.md) includes actual PostgreSQL contention and POSIX exclusion; hardware qualification remains with the skipped named-device tickets.
