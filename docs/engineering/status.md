# ModelAnvil implementation status

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
| RAG/cluster/context | Local helpers, inline vectors and context prompt inspection; evidence-position recall is explicitly not run | End-to-end retrieval/model execution and browser pilots; TASK-11/12 |
| SDK/deployment/ops | Local helpers/configuration and fixture checks | Process isolation, real installs, restore drills and platform qualification |

API `execution_evidence` is read-only and separate from saved workflow state. Legacy qualified labels do not authorize production. Production model/release qualification and serving promotion fail closed while the trusted runtime evidence path is unavailable. See [frontend coverage](frontend-workspace.md) for browser interactions.

## Current verification

- Full Django regression suite: **464 tests, OK, 3 skipped**. Local HTTP fixtures required loopback server access; this is not external provider/hardware qualification.
- Web suite: **91 tests passed**; TypeScript/Vite production build passed.
- Django system check: no issues. Migration check: no changes detected.

Environment: macOS arm64, CPython 3.12.15, Django 5.2.18, DRF 3.15.2, SQLite test database, CPU only; Node 26.11.1. See the [review evidence](verification/task1-task2-2026-10-11.md) for commands, changed paths and remaining dependency gates. Historical suite counts and unsupported hardware/provider claims are not retained as current evidence.

TASK-4 verification on 11 October 2026: full backend **476 tests OK, 3 skipped**; final CPU/evidence regressions **20 tests OK**; web **91 tests OK**, build and Django schema checks passed. Browser launch, completion, downloaded candidate and queued cancellation passed against an isolated temporary database. [Review package](verification/task4-2026-10-11.md). These are review evidence, not developer acceptance.

TASK-5 is ready for developer review (11 October 2026): qualified training preflight now shows actual encoded text/token IDs, pinned inputs, itemized compatibility/capacity/storage/budget checks and matching measured worker-pilot CPU estimates, with monetary cost explicitly unknown. Browser launch uses a signed preview and server launch repeats admission checks. Final targeted checks: **39 OK, 1 skipped**; web **100 passed**, build/schema checks passed. Full backend regression exposed one TASK-13-owned missing `os` import; it is recorded in Aftur. [TASK-5 review and limitations](verification/task5-2026-10-11.md). TASK-4 is now accepted in Aftur; TASK-5 acceptance remains with the developer.

TASK-36 is accepted in Aftur. TASK-13 adds a real pinned SmolLM2-135M FP32 GPU worker runtime, with an Apple MPS three-step pilot, exact checkpoint recovery, cancellation/corruption step accounting and independent Hugging Face inference. CUDA/ROCm/XPU placement paths remain unqualified on their hardware; shared-device admission belongs to TASK-42. [GPU review package and regression limitations](verification/task13-gpu-2026-10-11.md). TASK-13 is in Aftur review with ten evidence artifacts. Scoped tests: 57 passed. Final broad backend run: 626 tests, one TASK-9 publication-recovery failure, zero errors, three skipped; affected earlier shared regressions were repaired (12 rechecks passed). Acceptance remains with the developer.
