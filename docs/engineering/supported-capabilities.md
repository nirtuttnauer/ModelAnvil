# ModelAnvil supported capability baseline

23 October 2026 · TASK-44 · Small teams building private AI products

ModelAnvil executes real local data preparation, bounded training, inference, evaluation, export and CPU serving. Support is specific to each operation, recipe and tested environment. The archived guided Apple GPU journey and the current CPU evaluation/release journey have different support envelopes. The GPU reports predate the current dependency upgrade and require fresh hardware qualification. Complete R1 and production model qualification remain open.

The [machine-readable evidence index](supported-capabilities.json) retains its baseline operation snapshots, artifact identities and archived report checksums. Current merged additions are recorded in the operation-specific addendum below. The [11 October audit](capability-evidence.md) and [historical status ledger](status.md) retain their original review history; this baseline incorporates the later implementations and verification below.

| Operation | Current execution evidence | Limits and next qualification |
| --- | --- | --- |
| Import | Actual bounded JSONL/CSV/JSON/DOCX/PDF publication with immutable source provenance. See [source imports](source-import.md). | Guided conversational import has a separate 1,000-example limit. Model metadata registration does not establish executable weights; live external transfer is a separate qualification. |
| Training | Guided SmolLM2-135M full SFT and Apple SmolLM2-1.7B rank-16 adapters. The [14 October run](verification/useful-local-training-2026-10-14/final-training-evidence.json) completed 288 updates with a selected checkpoint. | At most 128 tokens/example, 1,000 examples and 3,000 updates. Large guided profile requires an Apple GPU, at least 32 GiB RAM and 12 GiB process headroom. Narrow answer checks do not establish broad quality. Expand workload support in TASK-45. |
| Evaluation | Actual CPU reference and bounded Safetensors inference with pinned suites, baseline cases, durable jobs and fenced accounting. Guided chat snapshots are scored with their native chat template on the training device; reference bundles stay plain prompts on CPU. [Fresh TASK-44 baseline](verification/task44-activation-2026-10-23/baseline.json). | 1–64 cases and 1–32 generated tokens. A 1.7B guided candidate evaluates on the Apple GPU used for training. `production_qualified` remains false. |
| Export | Actual CPU bundle bytes loaded by an [independent consumer](verification/p0-local/independent-consumer.json). A separate guided [adapter ZIP inspection](verification/useful-local-training-2026-10-14/download-evidence.json) identifies selected step 192. | These are different candidates and consumers. The final shuffled guided ZIP was not independently loaded in that report. Conversions and quantization need their own evidence. |
| Serving | Actual authenticated CPU serving, readiness probe and rollback in the [local pilot](verification/p0-local/local-beta-browser.json). | In-process local CPU service; a startup probe is not continuous health monitoring. Its zero accuracy threshold exercised infrastructure. The [production web stack](../../deploy/production/README.md) has separate customer/worker/serving gates. |
| Recovery | Fenced local checkpoints and an [actual local restore](verification/p0-local/restore-drill.json) verifying 49 artifacts and refusing 12 duplicate commits. | One local SQLite/filesystem topology. No distributed, broker-cluster, managed object-store or production RTO/RPO claim. |

Known identifiers and hashes are recorded as such in the JSON index. Missing candidate hashes remain null. A checksum of an archived report establishes which report was used, not independent verification of every weight file named in it. All entries retain `production_qualified: false` and `hardware_qualified: false` under the existing evidence contract.

## Current merged additions — 23 October 2026

The [integration inventory](integration-inventory.md) and [current evidence audit](capability-evidence.md) map deliveries through PR46. Real pinned CPU embedding serving/builds/fine-tuning, SQL retrieval, cited local generation and repeated position sweeps now have a [source-bound reproducible report](verification/task73-end-to-end-2026-10-23/report.md). Its exact merged-main SHA passed required CI and its corresponding artifact was independently verified. This is bounded CPU reference evidence, with explicit closed-corpus, weak-control and format-scoring limits.

Annotation supports an opt-in [actual reviewed-label CPU train/evaluate cycle](verification/task10-labeling-2026-10-23/report.md) with explicit advance/rollback and protected suites; drafts remain imported. [Private corrections](verification/task53-private-feedback-2026-10-23/report.md), [private-team access](verification/task49-team-access-2026-10-23/report.md), [independent export](verification/task7-export-2026-10-23/report.md) and [token budgets](verification/task72-token-budget-2026-10-23/report.md) have separate scoped checks. Current OCR/layout model qualification, GPU recipes and customer/production outcomes remain open where documented. The baseline JSON's archived entries do not silently expand to these newer operations.

## Local activation and improvement measurements

Activation ends when a team explicitly records an accept or reject decision after an actual candidate/baseline comparison. Evaluation completion, lower training loss, a saved release pointer, and chat anecdotes cannot complete activation on their own.

After guided training, compare that exact candidate with its base model, inspect the paired answers, then use **Record accept** or **Record reject**. Recording a choice does not deploy the model or override release gates. Chat, download, lower loss, a synthetic training fixture, and a three-step setup check do not qualify. Decisions are immutable; repeating the identical submission returns the saved decision. Use a new comparison for another decision. **Overview → Local workflow measurements** exposes the current project report.

| Measure | Counting rule |
| --- | --- |
| Weekly improvement cycles | Unique team/candidate/evaluation tuples with an explicit decision and complete, currently verifiable worker training and candidate/baseline execution. |
| Teams completing a cycle | Distinct team identities among those tuples. |
| Accepted improvements | An explicit accept choice whose measured task accuracy exceeds the baseline on the pinned suite. Ties, lower loss and unsupported latency/cost claims do not qualify. |
| Rejected candidates | Explicit reject choices on complete verified comparisons. |
| Workspace sessions | Unique local browser session/project pairs that opened the workspace. Reload replays the same open event. |
| Interaction time | Browser-reported time following pointer, keyboard or scroll interaction in a focused, visible page. Idle intervals over 15 seconds are excluded. This is a best-effort lower bound, not a human productivity study. |
| Time to first decision | Server time between the project's first recorded workspace-open event and its first decision. Earlier uninstrumented installation/account creation is outside that interval. |
| Queue and execution | First claim minus job creation, and summed completed attempt wall times, reported separately for training, evaluation and model acquisition. Execution includes loading/checkpointing. Retry backoff is not GPU kernel time. |

Weeks run from Monday 00:00 UTC to the following Monday, excluding the latter boundary. A repeated submission or another review of the same tuple does not inflate counts. Simulated, incomplete, missing-baseline and unverified results are excluded. Reports recheck access and artifact/protocol identity; changed or unavailable evidence cannot continue contributing a valid cycle. These counts do not establish a statistically meaningful quality improvement by themselves; TASK-47 adds the fuller decision report and uncertainty treatment.

### API contract

- `POST /api/v1/activation/events/` accepts only event ID, session ID, `workspace_opened`/`activity` and 0–60,000 active milliseconds. Unknown fields are rejected. `X-Project-ID` is required. Identical event replays are idempotent; conflicting reuse returns 409.
- `POST /api/v1/evaluation-runs/{run_id}/record-decision/` accepts only `{"outcome":"accept"}` or `{"outcome":"reject"}`. Engineer access and an active project are required. The service verifies actual completed training, distinct candidate/baseline, all case IDs, pinned artifacts and the current evaluator contract. Training marked as a synthetic fixture or a setup check is rejected. An identical decision replay returns 200; a new decision returns 201.
- `GET` and `POST /api/v1/training-runs/{run_id}/comparison/` queue that comparison for one completed guided run, using its held-out split or a confirmed question list. The same managed worker executes it. The recorded choice still uses the decision API above.
- `GET /api/v1/activation/report/?week=2026-10-19` returns the selected project's report for that UTC week. An administrator without project scope can inspect tenant totals, deduplicated across projects by team/candidate/evaluation. Ordinary project users cannot request tenant totals. Responses are `Cache-Control: no-store`.

Measurement records have fixed fields and no prompt, answer, filename, URL, email, arbitrary metadata or credentials. The report hashes existing execution evidence without copying its content into measurement records. Authentication headers are used by the existing API authentication path and are not stored in activation events. The browser captures scope before sending so project switching and cleanup cannot attribute time to the new project.

No external analytics transport is implemented or enabled. Adding one requires an explicit owner choice before any export; local collection never implies consent to external processing. Diagnostic/report output should remain in the installation unless the owner explicitly chooses to share it.

### Fresh observed baseline

Run from the repository root with the installed Python environment:

```sh
.venv/bin/python scripts/measure_activation_baseline.py \
  --output /absolute/path/activation-baseline.json
```

The command creates and migrates a disposable database, prepares local reference weights/data, executes two genuine optimization steps, runs a durable held-out comparison, records a rejection and writes a content-free report. It uses the same qualification fixtures as the API regressions; it does not contact a model provider or touch the user's database. Temporary resources are removed afterward.

The [21 October automated observation](verification/task44-activation-2026-10-21/baseline.json) reached its decision in approximately 3.33 seconds from fresh-database setup, including approximately 1.77 seconds of migrations and 1.22 seconds of preparation/training/evaluation. That tiny CPU workflow is an operational baseline. Model download, dependency installation and human onboarding were not observed and remain null. A representative user baseline belongs to the TASK-43 pilots; no customer activation, model quality, retention or performance target is inferred from this automation.

The [23 October fresh-environment observation](verification/task44-activation-2026-10-23/baseline.json) created a new Python virtual environment and installed the current base requirements in 11.638 seconds (pip cache allowed; Python installation excluded). A fresh database then reached an explicit reject decision in 6.745 seconds, including 4.423 seconds of migrations and 1.863 seconds of resource preparation, genuine CPU training and evaluation. The report separately records training/evaluation queue and execution times. One unique cycle and one rejected candidate were counted; accepted improvements remained zero. Download and human effort remain null because neither was observed. These are local correctness observations, not customer activation or retention figures.

The seven restored historical reports match the SHA-256 values already published in the index. Their original dates and claims are retained. Checksums identify reports, not newly reproduced hardware or production qualification.
