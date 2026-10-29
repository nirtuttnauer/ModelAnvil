# ModelAnvil capability ledger

28 October 2026. This is the current support surface. Historical plans and dated reviews stay in place, but they are not support claims. `production_qualified: false` for every operation below.

Evidence levels:

| Level | Meaning |
| --- | --- |
| Configuration only | A saved record exists and no execution has been verified. |
| Simulation | A fixture or numerical stand-in produced the result. |
| Integrated execution | The named code path ran on the named inputs. Model quality and hardware qualification are separate. |
| Hardware qualified | Pinned inputs, outputs, runtime, hardware, independent inference, and operational checks passed for that envelope. No current path has this level. |

Browser training, evaluation, export, and serving labels use these names. A Storybook `fixture` label is shown as simulation. The synthetic trainer in `modelanvil/runners/training/engine.py` stays simulation and cannot be accepted, exported as a real model, or promoted.

## Published limits

Guided sequence tokens: 128

CPU sequence tokens: 256

Generated tokens: 48

Guided and GPU SmolLM2 training still refuse anything outside 2–128 tokens. The CPU profile admits 256 tokens because [the measured report](verification/sequence-envelope-2026-10-28/report.json) completed one FP32 AdamW step on random token ids, using the pinned SmolLM2-135M-Instruct weights, then generated 48 tokens. The probe reloaded the updated parameter bytes and recorded `production_qualified: false`. It is not a customer dataset, not Apple MPS, and not a raise of the 1,000-row cap. The CPU host-memory gate is that run’s peak RSS plus 25 percent. CUDA, ROCm, and XPU stay unqualified.

QLoRA stays unsupported until a candidate passes the existing unquantized comparison. The native four-bit candidate already failed that gate.

## What runs

| Operation | Recipe and device | Limits | Level | Report |
| --- | --- | --- | --- | --- |
| Guided fine-tune and accept/reject | SmolLM2-135M full SFT, or Apple 1.7B rank-16 LoRA on MPS | 1,000 examples, 128 tokens, 3,000 updates | Integrated execution for the pinned profiles. MPS evidence is a three-step correctness check. | [Guided fine-tuning](guided-fine-tuning.md), [MPS check](verification/task40-current-mps-2026-10-23/report.md) |
| CPU pretrained SmolLM2 | `modelanvil.smollm2-cpu-sft.v1` | 20 updates, 1,000 examples, 256 tokens, measured memory gate | Integrated execution for the 256-token probe. Earlier 128-token runs remain in the task 15 report. | [Sequence probe](verification/sequence-envelope-2026-10-28/report.json), [CPU profile](verification/task15-cpu-pretrained-2026-10-23/report.md) |
| Evaluation | CPU reference bundles and Safetensors snapshots, native template for guided chat | 1–64 cases, 1–48 generated tokens | Integrated execution. 48 tokens matches the CPU probe, not a GPU answer-quality claim. | [Sequence probe](verification/sequence-envelope-2026-10-28/report.json) |
| Decision report | Same comparison, Wilson intervals | A call of improved or regressed needs at least 30 cases and non-overlapping intervals | Integrated execution of the report math. A small sample stays inconclusive. | This ledger |
| Export and local serving | Reviewed CPU or guided bytes, in-process CPU serving | Startup probe, not continuous health | Integrated execution. Production qualification is closed. | [P0 local](p0-implementation.md), [production stack](../../deploy/production/README.md) |
| Development corrections | Failed cases on a suite marked development | Corrections publish a training dataset and are excluded from protected final tests | Integrated execution of the handoff. Automatic next-batch labeling stays unbuilt. | This ledger |
| Private team | One owner invitation | Bounded local invitation | Integrated execution | [Team access](verification/task49-team-access-2026-10-23/report.md) |
| RAG and context | Pinned CPU MiniLM retrieval and SmolLM2 generation | Closed corpus. Position exact-match is 0. | Integrated execution. Not a release-quality answer system. | [Task 73](verification/task73-end-to-end-2026-10-23/report.md) |
| Alignment, vision, audio | Bounded CPU or named Apple profiles | See each guide | Integrated execution under Advanced. Not the guided decision. | Operation guides |

Reference device for guided GPU evidence: Apple MPS, and only for the measured three-step envelope. This ledger does not treat “GPU detected” as support. CUDA, ROCm, and XPU are unqualified.

## Commercial gate

Customer discovery is open. Paid packaging is closed. GitHub issue 16 is the human gate. The automated activation script measures a seconds-long CPU fixture and is not a user baseline. No design-partner evidence is recorded here.

## Installation

The single-host HTTPS stack in `deploy/production/` is the install we will qualify. It does not start a worker. Signup is off by default. Password reset emails a code only when `EMAIL_HOST` is set, and never returns the code when debug is off. `scripts/replay_evaluation_gate.py` fails when a saved report regresses or is not decisive. `scripts/rehearse_restore_copy.py` checks a byte copy and records `production_qualified: false`. Off-host PostgreSQL restore, a worker on that host, and a clean-host train-decide-export journey are still open. Executor code remains trusted; the worker protocol does not sandbox it.

## R1 scenarios, current reading

The October scenario table in [capability-evidence.md](capability-evidence.md) is historical. The current reading is:

| Scenario | Current envelope | Level |
| --- | --- | --- |
| 01 Scratch | CPU fixture loss, not a declared architecture trained from recorded initialization | Simulation |
| 02 Fine-tune | Named SmolLM2 and reference profiles above | Integrated execution, not hardware qualified |
| 03 Preference / reward | Bounded CPU and Apple paths | Integrated execution, Advanced |
| 04 Verifier RL | CPU character path | Integrated execution, not a release gate |
| 05 Formats | Text, PDF, DOCX, CSV, and bounded image/audio paths | Partial integrated execution |
| 06 Custom format | Local helper | Integrated execution of the helper |
| 07 Isolation | Selected API and project boundaries | Integrated execution |
| 08 Recovery | Fenced local checkpoints and one SQLite restore drill | Integrated execution, one topology |
| 09 Portability | Independent consumers for named CPU and Safetensors exports | Integrated execution, not every deployment |
| 10 Release | Local review and CPU serving probe | Integrated execution. `production_qualified: false` |
| 11 Dataset Bank | Software acquisition | Integrated execution with fixtures, not live upstream qualification |
| 12 Broker | Outbox, leases, and tests | Integrated execution, not a production broker topology |
| 13 RLHF | CPU reward and RLOO reference | Integrated execution. DPO does not stand in for RLHF. |
| 14 RAG | SQL retrieval and cited generation | Integrated execution. Position exact-match 0 stays a failure. |
| 15 Cluster | Measured PCA table | Integrated execution, not a large-data explorer |
| 16 Context | Paired CPU inference | Integrated execution, no long-context claim |
| 17 Labeling | One explicit CPU review cycle | Integrated execution. Automatic batches stay deferred. |

PRD section 5.4 is the release-scope amendment that matches this table. Provider backlog ids other than the already implemented Runpod control plane are deferred until a pilot asks for one provider.
