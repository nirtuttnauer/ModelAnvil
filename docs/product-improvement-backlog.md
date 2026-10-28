# ModelAnvil product improvement backlog

The current screen review is translated into the [prioritized implementation backlog](product-implementation-backlog.md), dated 12 October 2026. This document preserves the earlier task mappings and planning history.

11 October 2026 · Product review of the current workspace

Drafted from repository evidence. No implementation authorization or delivery dates are implied. P0 protects trust and boundaries; P1 makes the first text-model journey usable; P2 expands qualified workflows. Effort is relative (M/L), not a delivery estimate.

The ModelAnvil project was created through Aftur MCP at `<user-home>/Documents/Code/Aftur/ProjectMemory/ModelAnvil`, linked to this repository. All 12 improvement tasks were created and read back through its separate scoped MCP connection; acceptance criteria, repository assignments, proposed status and dependency links were verified. The mapping is MA-PM-01–12 → TASK-1–12. Priorities are recorded in each task title and description; they are product recommendations, not delivery commitments.

Recommended path: MA-PM-01/02 → MA-PM-04 → MA-PM-06 → MA-PM-07. Onboarding, preflight, run monitoring and one Dataset Bank source support that journey. The first fine-tuning slice does not remove the PRD's scratch-pretraining or other R1 requirements.

## MA-PM-01 — [P0] Make capability and qualification status match actual product evidence

**Owner:** Product + platform · **Relative effort:** M · **Depends on:** None

**Problem:** The status ledger describes fixture-driven work as DONE/QUALIFIED, while the frontend documentation identifies missing executors. TrainingEngine generates deterministic loss curves and validates metadata rather than producing and externally loading trained weights.

**Scope:** Introduce an evidence-backed capability matrix separating configuration-only, simulation, integrated execution and hardware-qualified paths. Label fixture results and gate ready/loadable/qualified claims on the corresponding evidence. Update README and status ledger consistently. Retain useful fixtures as explicitly simulated tests.

**Success measure:** Every surfaced training, evaluation, export and deployment claim links to the evidence level that supports it.

**Acceptance criteria:**

- Audit all 17 acceptance scenarios and record tested environment, artifact evidence and remaining gaps; fixture-only checks never count as hardware or external-load qualification.
- Simulation-origin records are identifiable through API and UI and cannot satisfy production model/release qualification.
- A metadata-only export cannot report external loadability; actual model instantiation and a bounded inference are required for that claim.
- README, status ledger and browser action/status labels agree on currently supported paths.

**Repository evidence:** `docs/engineering/status.md`, `docs/engineering/frontend-workspace.md`, `modelanvil/runners/training/engine.py`, `modelanvil/acceptance/test_r1_scenarios.py`

## MA-PM-02 — [P0] Enforce resource relationships and permissions across project boundaries

**Owner:** Backend + security · **Relative effort:** M · **Depends on:** None

**Problem:** Tenancy and RBAC exist, but tenant filtering alone does not establish every related-resource or project boundary. Some serializers use default relation querysets, and ordinary registry writes share a generic engineer role.

**Scope:** Audit create/update/actions for related model, tokenizer, source, release, suite and artifact references. Define project ownership and grants where absent; consistently validate accessible relationships and action-specific permissions. This is a verification/hardening task, not a claim of a confirmed cross-tenant exploit.

**Success measure:** All selected relationship-write and release-action denial fixtures pass for two tenants and two restricted projects.

**Acceptance criteria:**

- Document an action/resource authorization matrix including project scope and role restrictions.
- For each affected relationship, cross-tenant and unauthorized-project references are rejected before mutation on POST, PUT, PATCH and custom actions.
- Unauthorized promotion, policy exceptions and worker/storage administration are denied and produce appropriate audit evidence.
- Regression tests cover legitimate same-scope writes and denials without leaking existence or internal errors.

**Repository evidence:** `modelanvil/api/views/models_evals.py`, `modelanvil/api/views/registries.py`, `modelanvil/api/views/release_views.py`, `modelanvil/core/models.py`

## MA-PM-03 — [P1] Add guided workspace setup and prerequisite-aware first-run onboarding

**Owner:** Frontend + backend · **Relative effort:** M · **Depends on:** MA-PM-02

**Problem:** The workspace has 15 destinations, uses an API-key connection, and sends users to the API to register training prerequisites. A new user cannot complete setup entirely in the product.

**Scope:** Provide a resumable setup checklist for connection, organization/project selection, data, model/tokenizer, worker and budget readiness. Link each missing prerequisite to a supported creation/import flow. Use the existing visual system and add a persistent explicit project selector once resource scoping exists.

**Success measure:** Measure elapsed time and abandonment from first valid connection to an executable training preflight; establish a pilot baseline.

**Acceptance criteria:**

- A fresh authorized workspace can create/select a project and register/import pinned model and tokenizer prerequisites without manual API calls.
- The checklist derives readiness from saved resources and worker capabilities and survives refresh/reconnect.
- Switching project resets scoped data and preserves independent drafts without showing another project's resources.
- A task-based pilot verifies setup using keyboard navigation, clear empty/error states and an actionable next step.

**Repository evidence:** `web/src/main.tsx`, `web/src/pages/OverviewPage.tsx`, `web/src/pages/TrainingPage.tsx`, `docs/engineering/frontend-workspace.md`

## MA-PM-04 — [P1] Ship a real worker-backed text fine-tuning journey with verified checkpoints

**Owner:** ML + platform · **Relative effort:** L · **Depends on:** MA-PM-01, MA-PM-02

**Problem:** Training creates pending configurations, and the current TrainingEngine simulates progress. Users cannot yet produce an independently usable trained model through the browser.

**Scope:** Qualify one explicitly bounded text fine-tuning recipe and runtime. Pin dataset/model/tokenizer/recipe revisions, dispatch through durable jobs, persist actual checkpoints/weights and connect browser launch/monitor/cancel. Record the support envelope. Scratch pretraining remains a separate R1 requirement and is not satisfied by this task.

**Success measure:** An authorized user completes data → real fine-tuning → actual checkpoint → externally loaded candidate on the declared reference environment.

**Acceptance criteria:**

- Training configuration requires an immutable prepared dataset, compatible model/tokenizer, qualified runner and worker pool; unsupported combinations fail before dispatch.
- An idempotent launch reserves budget and creates a durable job; retries do not create duplicate chargeable attempts.
- Worker metrics come from the real engine; actual weights and optimizer/checkpoint state are checksummed and recorded with provenance.
- Inject cancellation and worker interruption; verify fenced commits, checkpoint restoration and external loading/inference of the resulting candidate.
- Publish a qualification report naming versions, hardware, workload limits, measured usage and failure-recovery evidence.

**Repository evidence:** `modelanvil/runners/training/engine.py`, `modelanvil/api/views/training_views.py`, `web/src/pages/TrainingPage.tsx`, `docs/engineering/implementation-plan.md`

## MA-PM-05 — [P1] Show actionable training preflight and an honest compute-cost estimate

**Owner:** ML + frontend · **Relative effort:** M · **Depends on:** MA-PM-04

**Problem:** The browser accepts recipe, tokenizer, base model and steps without showing a combined dataset/compatibility/capacity/budget preflight.

**Scope:** Expose server-side preflight for the qualified fine-tuning recipe. Summarize pinned inputs, samples, memory/worker/storage constraints and budget. Distinguish measured pilot estimates from unavailable values, and revalidate changed resources at launch.

**Success measure:** All known incompatible reference fixtures are stopped before compute allocation, with a clear corrective action.

**Acceptance criteria:**

- Preview the actual encoded training samples and resolved recipe/hardware requirements.
- Show itemized compatibility and capacity checks with actionable reasons for each blocking failure.
- Show estimate source, assumptions, units/currency and uncertainty; unavailable estimates are marked unknown.
- Launch rechecks referenced revisions, capacity and budget; stale preflight cannot authorize a changed run.

**Repository evidence:** `modelanvil/runners/training/preflight.py`, `web/src/pages/TrainingPage.tsx`, `modelanvil/budgets/models.py`

## MA-PM-06 — [P1] Execute independent model evaluations and compare candidates fairly

**Owner:** Evaluation + frontend · **Relative effort:** L · **Depends on:** MA-PM-04

**Problem:** Evaluation creates pending configurations and exposes recorded results, but suite creation and real inference are not connected into a user journey.

**Scope:** Add suite import/versioning and durable execution for the qualified text recipe. Freeze candidate/baseline, suite, scorer, template and decoding; persist actual case results and enable comparable candidate/baseline review.

**Success measure:** A real candidate and baseline complete the same held-out suite with inspectable outputs, failed-case counts and reproducible metrics.

**Acceptance criteria:**

- Import/version a bounded suite in the browser and declare its protected evaluation role and source grouping.
- Before launch, reject training overlap and incompatible candidate/baseline/tokenizer/scorer combinations.
- Dispatch real inference through the job/budget protocol and preserve case outputs, failures, scorer version and run environment.
- Compare only compatible frozen configurations; show sample counts, slices, missing/failed cases and uncertainty/N/A accurately.
- Duplicate callbacks, partial failures and cancellation never produce fabricated passing scores or an incorrect completed status.

**Repository evidence:** `web/src/pages/EvaluationPage.tsx`, `modelanvil/api/views/models_evals.py`, `modelanvil/runners/eval_executor.py`

## MA-PM-07 — [P1] Export verified model bundles and review evidence before release

**Owner:** Platform + evaluation + frontend · **Relative effort:** M · **Depends on:** MA-PM-04, MA-PM-06

**Problem:** The training export path builds registry/metadata bundles, and the browser release surface focuses on SPDX output. Users need a downloadable, independently loadable candidate with inspectable qualification evidence.

**Scope:** Create an immutable export of actual weights/tokenizer/config, recipe, lineage, licenses and checksums. Add a release review view for frozen required evidence and explicit failures. Qualify export first; endpoint serving and quantization require separate runtime evidence.

**Success measure:** A clean external environment loads the exported candidate and performs the declared inference without access to ModelAnvil internals.

**Acceptance criteria:**

- Export only a completed real candidate with required artifact and access checks; repeated exports of the same frozen candidate are idempotent.
- A bundle contains actual model/adapter bytes, required base reference, tokenizer/config, immutable recipe and source/evaluation/license manifests.
- The release view shows each required gate, evidence freshness and actionable failure; missing evidence blocks qualification.
- External loading and a bounded inference verify checksums and output compatibility; metadata presence alone is insufficient.
- Endpoint records/pointer changes remain visibly separate from verified live serving readiness.

**Repository evidence:** `modelanvil/api/views/training_views.py`, `modelanvil/releases/lifecycle.py`, `modelanvil/api/views/release_views.py`, `web/src/pages/ReleasesPage.tsx`

## MA-PM-08 — [P1] Add one durable run-detail view for progress, failures and recovery

**Owner:** Frontend + platform · **Relative effort:** M · **Depends on:** MA-PM-04

**Problem:** Training/evaluation and jobs expose separate views, require manual refresh and do not provide one linked recovery experience.

**Scope:** Add stable deep links joining logical runs, worker jobs/attempts, pinned inputs, metrics, checkpoints, usage and next actions. Use bounded polling or events, preserve filters and safely resume/retry supported work.

**Success measure:** A user can identify a failed run's cause and recover it from one view; refresh/reconnect retains the selected run.

**Acceptance criteria:**

- Run URLs persist across reload and browser back/forward and link to the related dataset/model/evaluation/job attempt.
- Live updates expose observed and desired state separately and show last update/connection freshness without losing drafts or selection.
- Cancellation remains requested until backend acknowledgement; unknown/lost ownership is explicit.
- Resume/retry is allowed only from compatible verified checkpoints and rechecks permissions/budget; prior attempts/evidence stay intact.
- Accessible details work at desktop and narrow widths, including a long-history and transient-connection-failure case.

**Repository evidence:** `web/src/pages/WorkflowsPage.tsx`, `web/src/pages/TrainingPage.tsx`, `web/src/pages/EvaluationPage.tsx`

## MA-PM-09 — [P1] Turn Dataset Bank selection into a resumable, published dataset acquisition

**Owner:** Data + frontend · **Relative effort:** L · **Depends on:** MA-PM-01, MA-PM-02

**Problem:** Selecting a Dataset Bank source currently creates a metadata draft and asks users to upload bytes themselves; it does not connect the catalog/downloader/preparation capabilities.

**Scope:** Qualify one bounded existing source/preset and connect preview, access/license preflight, queued acquisition, resume/cancel, preparation and immutable publication. Reuse existing downloader and preparation foundations; other sources remain explicitly unavailable until qualified.

**Success measure:** A user acquires the reference source, resumes an interrupted transfer and publishes a version with verified provenance from the browser.

**Acceptance criteria:**

- Preview real bounded samples and disclose source revision, access conditions, license obligations, scope and destination before launch.
- Use worker capacity and budget policy for acquisition; partial, failed or cancelled downloads never appear as ready datasets.
- Resume after an interruption from persisted transfer state and verify source/artifact digests before publication.
- Published versions retain attribution, transformations, rejection reports and source/group-aware protected splits.
- Held sources remain blocked; cross-tenant cache access and upstream revisions are tested without overwriting existing versions.

**Repository evidence:** `web/src/pages/DatasetBankPage.tsx`, `modelanvil/data/bank/downloader.py`, `modelanvil/data/bank/catalog.py`, `web/src/pages/DatasetsPage.tsx`

## MA-PM-10 — [P2] Complete a bounded labeling → retraining → qualification campaign loop

**Owner:** Annotation + ML · **Relative effort:** L · **Depends on:** MA-PM-04, MA-PM-06

**Problem:** Manual/imported-prediction review and snapshot export exist, but automatic drafting, actual retraining and independent promotion are disconnected. Protected IDs do not establish source-group reservations.

**Scope:** Implement one classification or text-labeling recipe using real workers, approved cumulative snapshots, reserved source-group audit/test sets and independent candidate gates. Manual advance is the default; bounded automation is opt-in.

**Success measure:** Both manual-seed and existing-model-seed paths complete two real cycles with preserved corrections and independent candidate evidence.

**Acceptance criteria:**

- Reserve protected source groups before the first batch and exclude their examples/variants from review-training snapshots.
- Pin each batch's drafting model/prompt; preserve original predictions separately from human revisions and resolve/adjudicate conflicts before closure.
- Batch closure atomically freezes approved cumulative labels and dispatches at most one budgeted training job.
- Independently evaluate the candidate; failed/worse candidates retain the previous qualified drafting model.
- Pause, cancellation, rollback and configured spend/iteration limits stop future stages without discarding approved labels.

**Repository evidence:** `web/src/pages/AnnotationPage.tsx`, `modelanvil/annotation/campaign_engine.py`, `docs/engineering/frontend-workspace.md`

## MA-PM-11 — [P2] Build a usable versioned RAG index and retrieval-comparison workflow

**Owner:** Retrieval + frontend · **Relative effort:** L · **Depends on:** MA-PM-02, MA-PM-06

**Problem:** The RAG browser queries registered indexes with lexical retrieval, while index construction, projection and retrieval/generation qualification remain operator/backend work.

**Scope:** Add source selection, pinned chunking/embedding recipe, durable index construction, retrieval diagnostics and one measured lexical-versus-dense/hybrid comparison on a qualified local stack. Add explorer projection only when actual coordinates and original-space neighbors are available.

**Success measure:** A user builds a real index and compares reproducible retrieval results on labeled held-out queries from the browser.

**Acceptance criteria:**

- Index jobs freeze source permissions/revisions and recipes; interrupted builds cannot become queryable completed indexes.
- Query traces show actual retrieved source spans, selected retrieval mode and reranking/context inputs where qualified.
- Report deterministic retrieval metrics with qrels version, unit, cutoff, coverage and N/A semantics.
- Current permissions and tombstones deny revoked/deleted content in old indexes, caches, exports and explorer views.
- Projection displays its method and limits and has a table equivalent; no simulated coordinates or generated-answer support claims.

**Repository evidence:** `web/src/pages/ClusterExplorerPage.tsx`, `modelanvil/rag/pipeline.py`, `modelanvil/rag/retrieval.py`, `docs/engineering/frontend-workspace.md`

## MA-PM-12 — [P2] Author context recipes and run measured paired Context Lab experiments

**Owner:** Application ML + frontend · **Relative effort:** L · **Depends on:** MA-PM-06

**Problem:** Context Lab compiles a selected saved recipe with estimated counts, but users cannot author blocks or run actual model experiments in the browser.

**Scope:** Add versioned block authoring, pinned model/tokenizer/template compilation and one real paired experiment workflow. Expose token budgets and omitted evidence, compare case outcomes and keep memory/tool fixtures scoped.

**Success measure:** A user authors two recipes and compares measured task success, actual token usage and latency on the same frozen cases/model.

**Acceptance criteria:**

- Author/reorder/version blocks and preview the exact resolved model input including omissions and output-token reserve.
- Use the pinned runtime tokenizer/template for exact counts; estimates remain explicitly labeled until qualified.
- Run actual model inference for paired recipe variants with fixed cases and recorded decoding/seeds/environment.
- Show case-level differences, evidence retention, failures, usage and latency; deterministic synthetic curves do not qualify task performance.
- Exercise overflow, conflicting/untrusted context and session-isolated memory fixtures with reproducible saved results.

**Repository evidence:** `web/src/pages/ContextLabPage.tsx`, `modelanvil/context_lab/compiler.py`, `modelanvil/context_lab/experiments.py`, `docs/engineering/frontend-workspace.md`
