# ModelAnvil implementation status

Current delivery addendum (23 October 2026): see the [integration inventory](integration-inventory.md), [operation-specific capability baseline](supported-capabilities.md), and dated verification reports. The original review below is historical; current dependency pins still require fresh GPU qualification. Customer discovery remains blocked on customer input.

Current operation-specific support and the later local evidence are indexed in the [21 October capability baseline](supported-capabilities.md). The entries below preserve the 11 October review history and are not a current cross-operation support matrix.

11 October 2026 · TASK-1 evidence audit

The former ledger used DONE for domain fixtures and described all 17 scenarios as delivered. Those completion/qualification claims are withdrawn. The [capability evidence audit](capability-evidence.md) is the current capability matrix, including evidence environment, artifacts and gaps for each scenario. Passing a fixture is not hardware, external-loader, operational or product-journey qualification.

| Path | Current evidence | Remaining work |
| --- | --- | --- |
| Identity, project boundaries, registries | Local HTTP/SQLite integration checks; TASK-2 under review | Human acceptance and broader operational qualification |
| Jobs, budgets, artifacts, datasets | Control-plane implementations and local tests | Real training integration, storage/provider and distributed recovery evidence |
| Fine-tuning | TASK-4 CPU character SFT: pinned text/base/tokenizer, durable budgeted job, fenced recovery and independent reference consumer; ready for review | Developer acceptance; GPU/distributed/general LLM runtimes remain unsupported |
| Scratch/other recipes | Explicit synthetic numerical fixtures | Real scratch and other training runtimes |
| Candidate export | TASK-4 actual CPU weights and character decoding; standalone reference consumer verified | Production inference and third-party runtime qualification |
| Evaluation | Configuration, expected-answer fallback simulation or caller-supplied callback integration | Real independent held-out model execution; TASK-6 |
| Alignment/RLHF | Fixture metrics and registry candidates | Real policy/reward weights, rollout and independent evaluation |
| Release/quantization/serving | Metadata export, fixed simulated quantization values, fixture pointer/rollback tests | Weight conversion, real serving readiness, reviewed qualification; TASK-7 |
| Annotation/campaign | Manual review and snapshot helpers; metadata candidate/fixed score fixtures | Actual retraining and qualification loop; TASK-10 |
| RAG/cluster/context | Actual pinned MiniLM CPU serving/builds/fine-tuning, SQL pgvector retrieval, public controls, local cited generation and repeated evidence-position runs | Closed-subset/toy-fixture software evidence; current hardware/customer/production qualification remains separate. [Combined reproducible report](verification/task73-end-to-end-2026-10-23/report.md) |
| SDK/deployment/ops | Local helpers/configuration and fixture checks | Process isolation, real installs, restore drills and platform qualification |

API `execution_evidence` is read-only and separate from saved workflow state. Legacy qualified labels do not authorize production. Production model/release qualification and serving promotion fail closed while the trusted runtime evidence path is unavailable. See [frontend coverage](frontend-workspace.md) for browser interactions.

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
