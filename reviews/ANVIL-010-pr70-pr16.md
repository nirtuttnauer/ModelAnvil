# ANVIL-010: PR #70 and PR #16, reviewed after merge

12 November 2026. Aftur TASK-84. Architecture and QA review.

The ticket was written on 29 October, before either PR merged. Both PRs merged on 2026-10-29 at 03:45:16 UTC. This review judges each claim against the PR #70 head and its check runs, then lists what still needs fixing on current main (`56b35cc`).

| PR | State | Head | Base | Merge commit |
| --- | --- | --- | --- | --- |
| #70 Publish the capability ledger and measured SmolLM2 CPU envelope | merged | `4dbda069a066b951fa2a9a2017ec1f2edfd76a19` | `3200915506331979c712c17ffd0b1817f95fda75` | `5dddd7ad63b893e9eae1e4d2c3c9e1c3f3dca4c0` |
| #16 Prepare private AI customer discovery and pilot validation | merged as a draft | `99b229a2bbd2cbe49a7c52b68de5c5febb3bf2b4` | `f065fbd1a22c7ad7865ec91db727d8843b5aac3e` | `ba2ede43f3c87452c1791eac71fd776c8ff25d71` |

Sources: `gh pr view 70` and `gh pr view 16` with `statusCheckRollup,body,files`; `gh api repos/nirtuttnauer/ModelAnvil/commits/<sha>/check-runs` and the job logs, all read-only; the files at `4dbda06`; a local run of `4dbda06` recorded in `docs/engineering/verification/anvil-010-2026-11-12/`. Line numbers are at `4dbda06` unless a line says "main".

## Verdicts

- **#70 Architecture: keep it merged, with follow-ups.** One support page, banners on the older plans, and a test that ties the ledger's numbers to the code are the right direction. Three design problems remain. The CPU training limits and the evaluation token ceiling are read at import time from a JSON report under `docs/`. The CPU memory gate was cut from 16 GiB to 3.82 GiB on a probe that does not match the runtime. The decision report is advisory, because the accept endpoint does not use it.
- **#70 QA: the counts hold, five claims do not, and G-skip fails at this head.** CI on the head was green: 6 of 6 check runs. Locally, the frontend passed 235 of 235, matching the claim. The backend ran 1248 tests with no failures, but 10 were skipped (59 in CI), so G-skip fails and the evidence script refused to write the backend record. The claims that do not hold are listed in the table below.
- **Canonical source for ANVIL-016:** `docs/engineering/supported-capabilities.json` should be canonical for capability levels and evidence. `docs/engineering/capability-ledger.md` stays the human-readable page and is checked against it. Details are in the section on the canonical source.
- **#16: rewrite `docs/product/customer-discovery.md` to discovery-only, or delete it.** Nir decides. Closing the PR is no longer possible. I could not find the exact wording of Nir's 28 October 20:58 and 21:02 decisions anywhere in the repo or in the Aftur project memory. Only paraphrases exist.

## Check runs on the #70 head

Two CI workflow runs on `4dbda06`, from the push and pull_request events. All six jobs completed with `success`. Each job has one notice annotation, about the `ubuntu-latest` image migration. Counts are taken from the job logs.

| Check run | Workflow run (event) | Job | Started to completed (UTC, 2026-10-27) | Result in log |
| --- | --- | --- | --- | --- |
| 122517609978 | 40597671886 (push) | backend | 22:49:15 to 22:57:18 | `Ran 1248 tests`, `OK (skipped=59)`; smoke `Ran 4 tests`, `OK` |
| 122517610255 | 40597671886 (push) | frontend | 22:49:15 to 22:49:41 | `tests 235`, `pass 235`, `skipped 0`; `npm run build` (`tokens:check && tsc -b && vite build`) and Storybook build passed |
| 122517610301 | 40597671886 (push) | pgvector | 22:49:15 to 22:52:58 | `--tag=pg`: `Ran 24 tests`, `OK` |
| 122517687776 | 40597694718 (pull_request) | backend | 22:49:26 to 22:57:57 | `Ran 1248 tests`, `OK (skipped=59)` |
| 122517687738 | 40597694718 (pull_request) | frontend | 22:49:26 to 22:50:06 | `tests 235`, `pass 235`, `skipped 0` |
| 122517687396 | 40597694718 (pull_request) | pgvector | 22:49:26 to 22:53:35 | `Ran 24 tests`, `OK` |

The `pgvector` log prints `TASK69_CONTROLS`. That is a small correctness check: held-out nDCG 1.0 next to seeded random 0.021535, on 200 documents. Its baseline is MiniLM nDCG@5 1.0 next to seeded random 0.0215 on 20 queries / 200 SciFact docs. #70 adds no retrieval number.

The merge commit `5dddd7a` is not a clean merge of the tested head. Its first parent is `6424a21`, the workspace redesign, not `3200915`. The merge moved #70's `OverviewPage.tsx` and `TrainingPage.tsx` changes into `LatestResults.tsx`, `CurrentRun.tsx` and `RunHistory.tsx`, and it added two Storybook fixtures. `5dddd7a` has no check runs of its own. The first CI on a tree containing it is the push of `ba2ede4` (run 40813910228), which passed: frontend 249 of 249, backend `Ran 1262`, `OK (skipped=60)`, pgvector 24 `OK`.

## Local run of the #70 head (ANVIL-002)

Full record: `docs/engineering/verification/anvil-010-2026-11-12/report.md`. Apple M5 Pro, macOS 27.0.1, Python 3.12.15, Node v24.22.3, label `local`, clean `git status --porcelain` before each command.

| Suite | #70 claim | CI on head | Local | Baseline `3200915` (ANVIL-002) |
| --- | --- | --- | --- | --- |
| `npm --prefix web test` | 235 passing | 235 / 235 | 235 / 235, exit 0, record written | 234 |
| `manage.py test --noinput --exclude-tag=pg` | none | 1248 ran, 59 skipped | 1248 ran, 0 failures, 10 skipped, exit 0; record refused for skips | 1237 collected, 6 skipped at decoration time |
| `manage.py test --noinput --tag=pg` | none | 24 / 24 | not run | 24 |

The backend difference is the 11 test methods in `modelanvil/core/test_trustworthy_roadmap.py`. The frontend difference is `web/tests/evidence-label.test.mjs`. The PostgreSQL suite was not re-run for this historical head, because another run owns Docker, ports 5432 and 5672, and `/tmp/modelanvil-premerge`. The 10 local skips are listed in `backend-sqlite-skips.txt`: three PostgreSQL-only tests that this head does not tag `pg`, three PDF tests (the shared environment has `pypdf` 6.21.4, and this head pins 6.21.2), RabbitMQ, the Linux verifier, MLX, and GGUF.

## PR #70 claims

The verdict is one of: holds, does not hold, not checkable.

### Capability ledger and documentation

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| A1 | "The current support surface is `docs/engineering/capability-ledger.md`" (body; `capability-ledger.md:3`; `README.md:13`) | Holds | The file is added. `modelanvil/runners/evidence.py:4` and `modelanvil/api/views/capability_ledger.py:17` point to it. `README.md:15` still calls `supported-capabilities.md` the place for "current operation-specific evidence", so two pages claim to be current. |
| A2 | "Older roadmaps and backlogs stay in the tree as historical notes" (body) | Holds | Historical banners at line 3 of `docs/ROADMAP.md`, `docs/category-leadership-roadmap.md`, `docs/engineering/implementation-plan.md`, `docs/engineering/README.md`, `docs/engineering/status.md`, `docs/engineering/capability-evidence.md`, `docs/product-implementation-backlog.md`, `docs/product-improvement-backlog.md`, and `docs/engineering/supported-capabilities.md`. |
| A3 | "`production_qualified: false` for every operation below" (`capability-ledger.md:3`) | Holds | `capability_ledger.py:18`, `decision_report.py:68`, the probe report at `report.json:19`, `restore_rehearsal.py:27`. |
| A4 | Hardware qualified: "No current path has this level" (`capability-ledger.md:12`) | Holds | No ledger row uses that level. The MPS report calls its three-step run qualified for that envelope, and the ledger deliberately records it as Integrated execution (`capability-ledger.md:32`). |
| A5 | Browser labels use these names, and a Storybook `fixture` is shown as Simulation (`capability-ledger.md:14`) | Holds | `web/src/api/evidence-label.ts:1-8`. `EvidenceLabel` is used on the Training, Evaluation, Releases and Overview pages and in `ModelExport.tsx`. `web/tests/evidence-label.test.mjs:5-14`. `test_trustworthy_roadmap.py:91-93` ties the names to `LEVELS`. |
| A6 | "Guided sequence tokens: 128", "CPU sequence tokens: 256", "Generated tokens: 48" (`capability-ledger.md:18-22`) | Holds | Imported at head and on main: guided 128 (`hf_runtime.py:50`), CPU 256 (`cpu_hf_runtime.py:16` through `sequence_envelope.py`), evaluation `max_tokens` 48 (`eval_worker.py:21`, `:119-121`). `test_trustworthy_roadmap.py:85-89` checks that the ledger text matches the code. |
| A7 | Row limits: guided "1,000 examples, 128 tokens, 3,000 updates"; CPU "20 updates, 1,000 examples, 256 tokens"; evaluation "1–64 cases, 1–48 generated tokens" (`capability-ledger.md:32-34`) | Holds | Imported limits: guided rows 1000, steps 3000, sequence 128. CPU steps 20, rows 1000, sequence 256. Evaluation `cases` 64, `max_tokens` 48. |
| A8 | Levels for rows #70 did not change: team, RAG, alignment, and the R1 scenarios 01–17 (`capability-ledger.md:38-40`, `:56-74`) | Not checkable here | The levels are prose, and the Report column links Markdown with no hashes. I checked only that all nine linked files exist at the head. |
| A9 | "PRD section 5.4 moves the unmeasured R1 lines to Target" (body) | Holds | `docs/PRD.md:177-200`; `:204` makes section 6 defer to 5.4. |
| A10 | "GitHub issue 16 is the human gate" (`capability-ledger.md:46`; `modelanvil/core/pilot_gate.py:11`) | Does not hold on main | At the head, #16 was an open draft PR, not an issue. It merged on 2026-10-29, and the sentence is still on main. It is shown to every user on the sign-in screen (`web/src/components/Welcome.tsx:59` on main renders `commercial_reason`). |
| A11 | Ledger RAG rows: "Position exact-match is 0" (`capability-ledger.md:39`, `:71`) | Holds, but unlabeled | The number matches the task 73 report (0/6 per position). G-rag: it is not labeled as a small correctness check, and no baseline is shown next to it. |

### 256-token CPU envelope for `modelanvil.smollm2-cpu-sft.v1`

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| B1 | One CPU step on the pinned SmolLM2-135M-Instruct weights completed at 256 tokens, then generated 48 tokens (body; `capability-ledger.md:24`) | Holds as recorded; the run is not checkable | `report.json:10-13`: `model_sha256` is the Instruct hash (`scripts/measure_sequence_envelope.py:17`), `completed_steps` 1, `sequence_tokens` 256, `generated_tokens` 48. The report has no commit SHA, host, date, command, or list of sequence lengths tried. The script tries 256 and 512 by default (`:140`), and the report does not say what happened at 512. The script reads `/proc/meminfo` and treats `ru_maxrss` as kilobytes (`:22-26`, `:41-43`), so it measures only on Linux. The CPU profile trains the base SmolLM2-135M weights (task 15 report), but the probe used the Instruct weights. `admit_report` accepts either hash (`sequence_envelope.py:17`, `:34`). |
| B2 | The envelope applies only to `modelanvil.smollm2-cpu-sft.v1`; guided GPU training stays at 128 tokens (body) | Holds | `sequence_envelope.py:30-31` refuses other profiles. `hf_runtime.py:50` keeps 128. `test_trustworthy_roadmap.py:63-74`. |
| B3 | The probe is not MPS, CUDA, ROCm, XPU, a customer dataset, or a production qualification (body) | Holds | `report.json:3`, `:19-21`. `sequence_envelope.py:54-55` refuses a report that sets either qualification flag. |
| B4 | "The probe reloaded the updated parameter bytes" (`capability-ledger.md:24`) | Does not hold | `measure_sequence_envelope.py:59-61` clones one tensor, clones the clone, and compares the two in memory. Nothing is written or read back. Only the first trainable tensor is checked (`:52`). The script always writes `recovery: parameter_state_roundtrip` (`:63`, `:123`), and admission checks only that string (`sequence_envelope.py:48-49`). |
| B5 | "The CPU memory gate is that run's peak RSS plus 25 percent" (body; `capability-ledger.md:24`) | Holds as code | 3,281,649,664 + 820,412,416 = 4,102,062,080 bytes (`sequence_envelope.py:59`; imported `LIMITS['memory_bytes']` at head and on main). This cut the gate from 16 GiB, which the task 15 report calls "conservative", to 3.82 GiB. The probe enabled gradient checkpointing (`measure_sequence_envelope.py:50-51`). The full-SFT and continued-pretraining runtime does not (`hf_runtime.py:262-264`; checkpointing is only in the LoRA branch, `:299-301`). The probe used one row and one step, for a profile that admits 1,000 rows and 20 updates. The gate is not measured for the configuration it admits. |
| B6 | "Not a raise of the 1,000-row cap" (`capability-ledger.md:24`) | Holds | The imported CPU `rows` is 1000. |
| B7 | "Sequence probe report: `docs/engineering/verification/sequence-envelope-2026-10-28/report.json`" (body, Tests) | Holds | The file exists (22 lines). It is not an ANVIL-002 record: no SHA, machine, command, stdout, or exit code. |

### Wilson-interval decision reports, no win or loss under 30 cases

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| C1 | "Decision reports use Wilson intervals" (body; `capability-ledger.md:35`) | Holds | `decision_report.py:9-18`, a 95 percent Wilson score interval. Imported: 30/30 gives [0.8865, 1.0]; 15/30 gives [0.3315, 0.6685]; 0/30 gives [0.0, 0.1135]. |
| C2 | Reports "refuse to call a sample under 30 cases a win or a loss" (body) | Holds for the report | `decision_report.py:6`, `:37-39`. Imported: 29 cases all better gives `inconclusive` and `decisive: false`; 29 all worse gives `inconclusive`; 30 all better gives `accept`. `test_trustworthy_roadmap.py:97-110`. The comparison treats paired cases as two independent samples and requires non-overlapping intervals. That is conservative, not wrong. |
| C3 | The same rule governs the recorded accept (PRD 5.4 at `docs/PRD.md:185`: a report "that refuses a small sample as a win") | Does not hold server-side | `record_decision` (`models_evals.py:389-399`; `modelanvil/core/activation.py:53-65`) never calls `report_for_run`. `accepted_improvement = outcome == 'accept' and accuracy > baseline` (`activation.py:65`, same on main) counts a 4-case win as an accepted improvement in the activation report. Only the browser disables Accept. At the head it was blocked when the report was not `accept`. On main the merge narrowed that to eligible reports (`web/src/pages/EvaluationPage.tsx:141` on main). |
| C4 | `scripts/replay_evaluation_gate.py` "fails when a saved report regresses or is not decisive" (`capability-ledger.md:50`; `installation-qualification.md:9`) | Does not hold for slice regressions | `evaluation_gate.py:18-21` checks only `decisive` and overall accuracy. It ignores `regressed_slices`, `recommended_outcome` and `gate.passed`. Imported at the head and on main: 90 better cases in slice a plus 30 worse cases in slice b gives a report with `recommended_outcome: inconclusive`, `gate.passed: false`, `regressed_slices: ['b']` and `decisive: true`, and `gate_status` returns 0 (pass). |
| C5 | Storybook fixtures agree with the 30-case rule and the 48-token ceiling | Does not hold on main (added by the merge, not at the head) | `web/src/stories/demo-network.ts:62` returns `minimum_decisive_cases: 20`. `web/src/stories/workspace-fixtures.ts:77` returns `generated_tokens: 32`. |

### Three starter playbooks

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| D1 | "Three starter playbooks ship with that contract" (body) | Holds | `playbooks/classification`, `playbooks/extraction` and `playbooks/constrained`. Each has `limits.json`, `suite.json`, `train.jsonl`, `comparison.json` and `external-load.md`. Checked by `test_trustworthy_roadmap.py:112-131`. |
| D2 | "including one 30-case rejection protocol" (body; `limits.json` `rejection_protocol_cases: 30`) | Holds, narrowly | `playbooks/classification/comparison.json:1` is a 30-case fixture in which every candidate case fails and every baseline case passes. It says "These rows are not SmolLM2 outputs". `build_report` returns `reject`. It is not a model run. |
| D3 | Starter examples with independent evaluation suites (`docs/ROADMAP.md:9`; roadmap TASK-51 "with independent evaluations"; `docs/category-leadership-roadmap.md:56`) | Does not hold | Each `suite.json` has 2 cases, so no playbook can reach a decisive result under the 30-case rule. Every suite prompt is copied from that playbook's `train.jsonl`: classification c1 and c2 are train lines 1 and 2, extraction e1 and e2 are lines 1 and 2, constrained k1 and k2 are lines 1 and 4. `limits.json` names `modelanvil.smollm2-gpu-sft.v1` with `generated_tokens: 48`, a ceiling that comes from the CPU evaluation worker. The three `external-load.md` files are identical. Nothing outside the test reads `playbooks/`. |

### Development corrections

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| E1 | "Failed development cases can be saved as a training dataset" (body; `capability-ledger.md:37`) | Holds | `modelanvil/runners/development_cycle.py:25-95`, endpoint `models_evals.py:407-417`. Only `development` suites (`:30-31`); nothing is promoted (`:85-94`). `test_trustworthy_roadmap.py:172-186`. |
| E2 | "those source groups cannot be declared a protected final test" (body) | Holds | `modelanvil/annotation/feedback.py:53-66` refuses `protected_eval` cases whose `source_group_id` belongs to a `development_inspected` suite. The handoff sets that role (`development_cycle.py:82-84`). Development suites skip the check by design (`models_evals.py:224`). |

### Commercial gate and providers

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| F1 | "Paid packaging stays closed" (body) | Holds | `pilot_gate.py:8`, `:23-24`, returned by `/api/v1/capability-ledger/` and `/api/v1/accounts/status/`. `test_trustworthy_roadmap.py:191-206`. |
| F2 | "Customer discovery stays the open human gate" (body) | Holds at the head; stale on main | `pilot_gate.py:7`. #16 is merged, and Nir's 28 October decision, as paraphrased in TASK-84, dropped pilots. See A10 and the #16 section. |
| F3 | "Provider ids other than the existing Runpod control plane are refused until a pilot asks for one" (body; `capability-ledger.md:76`; `docs/PRD.md:198`) | Does not hold as worded | Only the 19 ids in `DEFERRED_UNTIL_PILOT` (`modelanvil/compute/plugins.py:18-22`) are refused (`:48-49`). Any other id can still be installed by an operator, which `provider-integration-todo.md:7` itself says. The refusal also breaks the plugin list: `compute/views.py:88-96` calls `definition()` for every installed plugin. When an operator configuration has one deferred id, `GET /api/v1/compute-plugins/` returns 500 `internal_error` for the tenant (`PluginError` reaches the generic handler). Reproduced in-process at the head and on main. |
| F4 | The 19 provider names in `provider-integration-todo.md:7` match the code | Holds | 19 names in the document and 19 ids in `plugins.py:18-22`. |
| F5 | Welcome screen says paid packaging stays closed (body, linked Cursor artifact) | Not checkable | The image is an external artifact. The code path is `Welcome.tsx:66` at the head, rendering `pilot_gate.py:9-12`. |

### Installation

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| G1 | "`production_qualified` remains false" (body) | Holds | See A3. |
| G2 | Off-host PostgreSQL restore, a worker on the production host, and a clean-host upgrade rehearsal are still open (body) | Holds | `docs/engineering/installation-qualification.md:14-18`. |
| G3 | Password reset emails a code only when `EMAIL_HOST` is set and never returns the code when debug is off (`capability-ledger.md:50`; `installation-qualification.md:8`) | Holds | `modelanvil/api/views/accounts.py:162-176`. Mail also needs `MODELANVIL_SEND_RESET_EMAIL` (`settings.py:52`), which the ledger omits. `test_trustworthy_roadmap.py:229-242`. |
| G4 | "Signup is off by default" (`capability-ledger.md:50`) | Holds for the production stack | `settings.py:50-51`: signup defaults on when `DJANGO_DEBUG` is 1, which is the development default, and off in production. |
| G5 | `scripts/rehearse_restore_copy.py` checks a byte copy and records `production_qualified: false` (`capability-ledger.md:50`) | Holds | `modelanvil/core/restore_rehearsal.py:9-30`. |

### Tests and counts

| # | Claim and source | Verdict | What decides it |
| --- | --- | --- | --- |
| H1 | "`npm --prefix web test` (235 passing)" (body) | Holds | Both CI frontend jobs: `tests 235`, `pass 235`. Locally: 235 of 235, 0 skipped, exit 0 (`frontend-npm-test.json`). |
| H2 | "`tsc -b`" (body) | Holds in CI | Both frontend jobs ran `npm run build` (`tokens:check && tsc -b && vite build`) and passed. Not re-run locally. |
| H3 | Roadmap, CPU admission, GPU runtime, durable evaluation, accelerator support, activation, and application-feedback tests (body) | Holds | Those modules are in the default suite. CI and local runs had 0 failures and 0 errors in 1248 tests. |
| H4 | "checks green 27.10" (TASK-84) | Holds | 6 of 6 `success`, 2026-10-27 22:49 to 22:57 UTC. |
| H5 | Under G-skip, a skip at runtime is a failure (QA ruling, 29 October) | Does not hold at this head | 59 skips in CI, 10 locally. The evidence script refused the backend record (`runs/0/skipped: 0 was expected`). |

## Architecture notes

1. **Runtime limits come from a documentation file.** `sequence_envelope.py:13` reads `docs/engineering/verification/sequence-envelope-2026-10-28/report.json` when the module is imported. A missing file, bad JSON, or a package pin bump silently restores 128 tokens, 32 generated tokens and the 16 GiB gate (`:64-94`). The in-repo test `test_trustworthy_roadmap.py:56-59` catches that in the source tree. The Docker image copies the whole tree, so the file is present there. Editing that report changes the CPU training `CONTRACT` and the evaluation `CONTRACT_DIGEST` (`eval_worker.py:21-22`). I did not check how already-pinned runs react to a changed digest. The admitted envelope should live next to the code, and admission should fail loudly.
2. **The memory gate was relaxed on unrepresentative evidence.** See B4 and B5.
3. **The decision report is advisory.** See C3 and C4.
4. **The commercial gate is hard-coded text.** `pilot_gate.py` puts a GitHub number and a pilot condition into a sentence that every user sees on the sign-in screen.
5. **The provider deferral fails as a 500.** See F3.
6. **There are two candidate sources of truth for capability levels.** See the next section.

## Canonical source for capability levels (for ANVIL-016)

Make `docs/engineering/supported-capabilities.json` canonical for capability levels and their evidence. Keep `docs/engineering/capability-ledger.md` as the human-readable support page that the API and browser link to. Have the ANVIL-016 test check every ledger Level cell and every README Evidence cell against the JSON. Numeric limits stay canonical in code, as #70 already does in `test_trustworthy_roadmap.py:85-89`.

Reasons:

- The ledger's Level column is prose, for example "Integrated execution for the pinned profiles. MPS evidence is a three-step correctness check." Its Report column links Markdown files with no hashes, and two rows cite "This ledger" as their own evidence. A test cannot verify that without parsing sentences.
- The JSON already has level codes, evidence paths and sha256 values. That is what ANVIL-016's acceptance criteria require.
- ANVIL-016 already says to extend the existing manifest rather than add a second one.
- No code reads the ledger's levels. Only the limit numbers are tested, and the ledger path is used as a link.

Before ANVIL-016 can rely on the JSON:

- The JSON is stale. It was reviewed on 2026-10-23, has 8 operations, all `integrated_execution`, and no Simulation row. It does not cover the ledger rows for the 256-token CPU probe, the decision report, development corrections, team access, or RAG.
- 7 of its 19 evidence sha256 values no longer match their files on main. Commit `75e2565`, after #70, rewrote digests in those JSON files as `\u` escapes to avoid gitleaks hits, which changed the bytes. The 7 files are `task40-mps-pilot.json`, both `task44-activation` `baseline.json` files, and the `numerical-report.json` and `independent-zip-and-api-report.json` files under task 23 and task 24. All 19 matched at `4dbda06`.
- The banners conflict. The ledger says it is "the current support surface" (`capability-ledger.md:3`). `supported-capabilities.md:3` says "Supporting evidence, not the status page". `README.md:15` calls `supported-capabilities.md` current. ANVIL-016 should change all three to say that levels come from the JSON.

## Follow-ups on current main

1. Enforce the decision report on the server. In `record_decision` (`modelanvil/core/activation.py:53-65`, `modelanvil/api/views/models_evals.py:401`), refuse `accept`, or at least never set `accepted_improvement`, unless `report_for_run(run)['recommended_outcome'] == 'accept'`. Add a test with a 4-case win.
2. Make `gate_status` fail when `regressed_slices` is not empty or `gate.passed` is false (`modelanvil/core/evaluation_gate.py:18-21`). Fix the wording at `capability-ledger.md:50` and `installation-qualification.md:9`.
3. Stop the plugin list from returning 500 when an operator configuration contains a deferred id (`modelanvil/compute/views.py:88-96`). Skip that id or show it as deferred, and add a test.
4. Correct `capability-ledger.md:24` now: the probe did not reload parameter bytes. Then either re-measure with the runtime's own step, or put the CPU memory gate back to 16 GiB until a matching measurement exists. A matching measurement uses no gradient checkpointing for full SFT, the base weights, more than one row, a serialized and reloaded state, and records the SHA, host, date, command and sequences tried.
5. After Nir's decision text is recorded, rewrite the pilot conditions: `capability-ledger.md:46`, `:76`; `modelanvil/core/pilot_gate.py:9-12`, which the sign-in screen shows; `docs/PRD.md:188`, `:198`; `docs/ROADMAP.md:11`, `:13`; `docs/engineering/provider-integration-todo.md:5-7`; the comment and name of `DEFERRED_UNTIL_PILOT` in `modelanvil/compute/plugins.py:16-17`. This needs Nir.
6. Playbooks: give each suite cases that are not in its `train.jsonl`, and enough of them to reach the 30-case rule, or label the suites as format examples only. Make `limits.json` say that the 48-token ceiling is the CPU evaluation worker's.
7. Storybook fixtures: `minimum_decisive_cases` 20 to 30 (`web/src/stories/demo-network.ts:62`), `generated_tokens` 32 to 48 (`web/src/stories/workspace-fixtures.ts:77`).
8. G-rag: label "Position exact-match is 0" (`capability-ledger.md:39`, `:71`) as a small correctness check, 0/6 per position, and show it next to its baseline.
9. Fix the 7 stale sha256 values in `docs/engineering/supported-capabilities.json` as part of ANVIL-016.

## PR #16

**State.** #16 was a draft and merged anyway, on 2026-10-29 at 03:45:16 UTC, as `ba2ede4`, directly after #70. It adds `docs/product/customer-discovery.md` (179 lines) and a link in `docs/engineering/README.md`. The file on main is identical to the head (`git diff 99b229a 56b35cc -- docs/product/customer-discovery.md` is empty). CI on the head ran 4 jobs, backend and frontend for the push and pull_request events, all `success` on 2026-10-22. The PR changed no code.

**Decision text.** I did not find the exact wording of Nir's 28 October 20:58 decision or his 21:02 decision. I searched this repository on main, including `docs/category-leadership-roadmap.md`, which does not mention either time. I also searched the Aftur project memory for ModelAnvil: tasks, the empty `decisions/` folder, the four decision requests (none from 28 October), and the October activity log. Only second-hand paraphrases exist, and they do not agree on what 21:02 said:

- TASK-84 (this ticket): "Nir's 28.10 20:58 decision dropped pilots and services, while 21:02 allows 2–3 discovery talks without a paid offer."
- TASK-113: "Open core approved as a hypothesis (Nir 21:02)".
- TASK-108: "Nir 21:05: offer hosting on his infrastructure", with a server started only after one month prepaid.

Read against the TASK-84 paraphrase, the merged file conflicts in these places:

- Its go gate needs eight interviews, five observed workflows and five willing design partners (`customer-discovery.md:7-8`, `:20-24`, `:168-169`). The paraphrase allows 2–3 discovery talks.
- It is built around pilots: the invitation (`:59`); interview step 5, which asks about the budget owner, approval process, spend and "a bounded pilot" (`:81-84`); the rubric rows "Buying process" and "Pilot commitment" (`:118-119`); the section "Confirm pilot scope" with partner slots P01 to P05 (`:126-145`); and the closing reference to "the paid-pilot assumptions in TASK-56" (`:178-179`). The PR title says "pilot validation", and the README link describes "pilot scope records".
- It makes no paid offer. It says to "Leave commercial terms open" (`:144`) and sends no outreach (`:61-62`). Those parts agree with "without a paid offer".

**Recommendation.** Rewrite the file to discovery-only once Nir's decision is written into the repo, for example under `docs/decisions/`, because the rewrite should use his words. Keep the interview and observation guide (`:64-91`) and the task comparison (`:93-109`), without the buying and pilot rows. Replace the 8/5/5 gate with the allowed number of conversations. Delete the partner slots, the pilot questions and the TASK-56 sentence. If discovery is not wanted at all, delete the file and its README link instead. Nir decides. The same decision also governs the pilot text that #70 put on main (follow-up 5). The Aftur tickets TASK-43, which still requires 8 interviews and 5 partners, and TASK-56, "Validate paid pilot packaging", carry the same conflict.
