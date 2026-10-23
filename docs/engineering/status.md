# ModelAnvil implementation status

23 October 2026 · Current merged-code baseline `2bf35ec61fa163c98706b9f5b2452d2385b98739`. The [final integration inventory](integration-inventory.md) maps scoped deliveries, every retained local/remote ref and original uncommitted scope. Saved workflow state, executed software, model quality, hardware qualification and production readiness remain separate.

| Path | Current merged execution evidence | Remaining boundary |
| --- | --- | --- |
| Identity, privacy and teams | Actual browser/API onboarding, recovery, revocation, project grants and private-team invitation/removal checks | External identity/providers and representative customer operation remain separate. |
| Jobs, budgets, artifacts and data | Fenced durable jobs, quantity-budget admission, immutable source imports/publication, current artifact/access checks, actual PostgreSQL contention | Live paid provider, distributed recovery and production storage qualification remain separate. |
| Training | Actual CPU character/general reference training; actual bounded MiniLM contrastive fine-tuning and independent export/reload | Current [MPS FP32 full-SFT/LoRA](verification/task40-current-mps-2026-10-23/report.md) passes a bounded three-step correctness/recovery check; QLoRA/MLX, other profiles and broader workloads retain their own qualification. Large scratch/distributed/new model families remain open. |
| Evaluation and alignment | Protected versioned suites, actual candidate/baseline inference; bounded character-model DPO/reward/PPO/verifier-RL | General LLM policy/reward workflows and customer quality gains are not established by reference fixtures. |
| Export and serving | Actual bounded CPU/Safetensors/embedding export bytes and independent consumers, authenticated CPU serving/probes | Generic quantization/GGUF/MLX, GPU placement and production-serving qualification remain held on their own evidence. |
| Annotation | Actual opt-in reviewed-label CPU train/evaluate/advance/rollback cycle with independent protected evaluation | Drafts remain imported; no general automatic labeling-quality claim. |
| Documents and recipes | Actual bounded CSV/JSON/DOCX/embedded-text PDF publication and rasterization; durable recipe/specialist control-plane checks | Mixed scanned-page OCR publication and current MLX specialist/model/language/layout qualification remain unfinished in TASK-62. |
| RAG and embeddings | Actual pinned MiniLM serving/builds/fine-tuning, authorized SQL full-text/exact/HNSW/RRF, source-safe saved traces and qrels comparisons | Closed-subset relevance and reference fixtures do not establish customer or full-benchmark quality. |
| Context and generation | Exact pinned CPU recipe budgets, actual paired reference inference, cited SmolLM2 generation/refusals and repeated real start/middle/end runs | Position EM includes formatting; no measured middle dip or arbitrary saved-recipe/long-context qualification. |
| Deployment and operations | Software CI, production HTTPS/container checks, scoped Runpod/plugin integration and retained local restore evidence | Live customer/provider/worker/hardware and broader operational envelopes remain separate. |

The [combined CPU RAG report](verification/task73-end-to-end-2026-10-23/report.md) records source/model/tokenizer/corpus/qrels/index/hardware pins. Its exact merged-main SHA passed all required CI jobs in [run 39925859135](https://github.com/nirtuttnauer/ModelAnvil/actions/runs/39925859135), with the [corresponding artifact](https://github.com/nirtuttnauer/ModelAnvil/actions/runs/39925859135/artifacts/12489890930) independently downloaded, checksum-verified and durably attached to TASK-73. CV evidence is scoped to those bounded CPU software/reference operations. Production release qualification and serving promotion remain gated.

Latest integrated code verification: local backend **1,041 tests, five optional skips**; actual PostgreSQL/model/broker suite **23 passed**; frontend **226 passed**, production and Storybook builds passed. These are the scoped source report's observations; the final documentation PR reruns its required CI rather than treating old counts as new tests. No test fixture or old qualified label certifies an unsupported operation.

## Historical reviews

The dated entries below preserve their original observations, counts and acceptance state. They are not current support claims; use the matrix above and operation-specific reports for the merged baseline.

## Historical verification snapshot (11 October 2026)

- Full Django regression suite: **464 tests, OK, 3 skipped**. Local HTTP fixtures required loopback server access; this is not external provider/hardware qualification.
- Web suite: **91 tests passed**; TypeScript/Vite production build passed.
- Django system check: no issues. Migration check: no changes detected.

Environment: macOS arm64, CPython 3.12.15, Django 5.2.18, DRF 3.15.2, SQLite test database, CPU only; Node 26.11.1. See the [review evidence](verification/task1-task2-2026-10-11.md) for commands, changed paths and remaining dependency gates. Historical suite counts and unsupported hardware/provider claims are not retained as current evidence.

TASK-4 verification on 11 October 2026: full backend **476 tests OK, 3 skipped**; final CPU/evidence regressions **20 tests OK**; web **91 tests OK**, build and Django schema checks passed. Browser launch, completion, downloaded candidate and queued cancellation passed against an isolated temporary database. [Review package](verification/task4-2026-10-11.md). These are review evidence, not developer acceptance.

TASK-5 is ready for developer review (11 October 2026): qualified training preflight now shows actual encoded text/token IDs, pinned inputs, itemized compatibility/capacity/storage/budget checks and matching measured worker-pilot CPU estimates, with monetary cost explicitly unknown. Browser launch uses a signed preview and server launch repeats admission checks. Final targeted checks: **39 OK, 1 skipped**; web **100 passed**, build/schema checks passed. Full backend regression exposed one TASK-13-owned missing `os` import; it is recorded in Aftur. [TASK-5 review and limitations](verification/task5-2026-10-11.md). TASK-4 is now accepted in Aftur; TASK-5 acceptance remains with the developer.

TASK-36 is accepted in Aftur. TASK-13 adds a real pinned SmolLM2-135M FP32 GPU worker runtime, with an Apple MPS three-step pilot, exact checkpoint recovery, cancellation/corruption step accounting and independent Hugging Face inference. CUDA/ROCm/XPU placement paths remain unqualified on their hardware; shared-device admission belongs to TASK-42. [GPU review package and regression limitations](verification/task13-gpu-2026-10-11.md). TASK-13 is in Aftur review with ten evidence artifacts. Scoped tests: 57 passed. Final broad backend run: 626 tests, one TASK-9 publication-recovery failure, zero errors, three skipped; affected earlier shared regressions were repaired (12 rechecks passed). Acceptance remains with the developer.


23 October 2026 — TASK-10 adds the opt-in bounded reviewed-label CPU training/evaluation cycle. [Fresh software and negative-control evidence](verification/task10-labeling-2026-10-23/report.md) records two actual executions and correct candidate rejection; it makes no customer quality or GPU claim. Draft predictions remain imported; advancement is an explicit user action.

23 October 2026 — TASK-11 adds frozen text-index receipts, source-safe saved traces, versioned paired relevance reports and measured PCA with an equivalent table. [Fresh retrieval and revocation evidence](verification/task11-rag-2026-10-23/report.md) qualifies bounded software behavior; model generation, semantic encoder quality and hardware qualification are not inferred.

23 October 2026 — TASK-12 adds ordered immutable recipe authoring, pinned CPU runtime tokenization and actual paired inference with saved case outputs, usage, latency, failure and retention evidence. [Fresh Context Lab verification](verification/task12-context-2026-10-23/report.md) covers bounded local software behavior and negative controls, without a general quality, GPU or prompt-injection safety claim.

23 October 2026 — TASK-14 revalidates browser model discovery, pinned public download/resume and local tensor import, while refusing incomplete tensor/GGUF payloads and exposing current runtime eligibility. [Fresh acquisition evidence](verification/task14-model-import-2026-10-23/report.md) includes a verified public snapshot and restored disposable-project privacy policy; import remains separate from GPU or production qualification.

TASK-49 adds a bounded private-team flow with expiring/revocable reviewer invitations, current membership checks for browser/personal API keys, and owner removal controls. Actual fresh two-user UI, keyboard review, 1440/390 layouts and immediate revocation verified; see [dated evidence](verification/task49-team-access-2026-10-23/report.md).
23 October 2026 — TASK-42 adds attempt-bound local physical-device claims, fresh GPU placement/runtime/budget admission and separately displayed live headroom. [Fresh software coordination evidence](verification/task42-device-admission-2026-10-23/report.md) includes actual PostgreSQL contention and POSIX exclusion; hardware qualification remains with the skipped named-device tickets.


23 October 2026 — TASK-64/66–73 ship actual token-aware chunking, pinned CPU embedding/build/candidate workflows, SQL full-text/exact/HNSW/RRF retrieval, independent public controls, token-budgeted local generation and real repeated position sweeps. [The combined report](verification/task73-end-to-end-2026-10-23/report.md) records one exact implementation SHA, model/file/corpus/qrels pins, index parameters and actual CPU hardware. README results are generated only from its saved JSON. Required CI reruns the complete protocol within frozen tolerances. A report alone cannot certify CV evidence: that requires a merged main SHA, green CI on that same SHA and the corresponding attached artifact. Strict position EM is0 because correct-code sentences fail the frozen output format; no middle dip or general quality gain is inferred.


23 October 2026 — TASK-15 adds a separate bounded pretrained CPU full-SFT/LoRA profile, retaining GPU/QLoRA requirements in TASK-77. [Actual CPU training, independent held-out scoring and recovery evidence](verification/task15-cpu-pretrained-2026-10-23/report.md) covers the exact 135M base, three measured updates per recipe and immutable export; no customer quality or production qualification is inferred.
