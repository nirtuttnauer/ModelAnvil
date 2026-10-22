# ModelAnvil prioritized implementation backlog

Historical planning snapshot. Delivery status is tracked in Aftur and the [current integration inventory](engineering/integration-inventory.md); proposed goals here are not measured results.

12 October 2026 · Proposed work from the screen review · Source baseline `4b90517`

The first delivery goal is a repeatable local text-model journey: set up a project, publish data, acquire a compatible model, train, independently evaluate, review and download the resulting candidate. Production serving has a separate release gate. Complete the blockers below before expanding advanced workflows.

This backlog covers all 16 navigation screens and Run Detail. Tasks describe remaining work; existing CPU training, bounded transformer training, local chat, manual annotation, lexical retrieval and context compilation should be reused. CSV, JSON and DOCX dataset imports are now committed in the source; their absence from the previously inspected running build is a deployment verification gap, not a missing implementation task.

The task definitions originated as **Proposed** work. Current local implementation and verification are tracked in [P0 implementation progress](engineering/p0-implementation.md). Owner roles are suggested disciplines, not assigned people. Dependencies determine execution order; priorities describe user impact. Dates and effort estimates require engineering sizing. These IDs are local planning IDs and have not been registered or approved in an external tracker. The [earlier improvement backlog](product-improvement-backlog.md) retains its historical task mappings; this document does not reopen or change those tasks.

## Priorities and delivery gates

| Priority | Meaning | Delivery gate |
| --- | --- | --- |
| P0 | Blocks the first complete journey or a production claim | PM001–PM006 and PM009 establish the local beta. PM007–PM008 additionally gate production serving. |
| P1 | Makes supported journeys usable, recoverable and connected | Complete before claiming self-service workflow coverage for the affected screens. |
| P2 | Completes advanced product workflows and expands the supported envelope | Several tasks are existing R1 requirements; their later order does not make them optional for full R1 acceptance. |

Start with PM001, PM002 and PM003. Connect their setup paths through PM004. PM005 closes the training-to-evaluation gap; PM006 closes the evaluation-to-export gap. PM009 verifies that chain. PM007 and PM008 then establish production serving and operation. P1 defects that do not require those dependencies, especially PM010, PM012 and PM014, can proceed alongside blocker work.

## Screen coverage

| Screen | First tasks | Subsequent work |
| --- | --- | --- |
| Overview | PM004 | PM009, PM010, PM013 |
| Dataset Bank | PM014 | PM013, PM026 |
| Datasets | PM015 | PM009, PM013, PM016 |
| Annotation | PM016 | PM017, PM019, PM025, PM034 |
| Models | PM003 | PM013, PM018, PM032 |
| Chat and Arena | PM019 | PM003, PM013, PM017 |
| Training | PM001, PM002, PM003 | PM010, PM011, PM020, PM031, PM032 |
| Alignment | PM021 | PM005, PM011, PM013 |
| Evaluation | PM005 | PM013, PM017, PM025, PM027, PM030 |
| Workflows | PM022 | PM011, PM013 |
| RAG | PM026, PM027 | PM028 |
| Context Lab | PM029, PM030 | PM013, PM006 |
| Releases | PM006, PM007 | PM008, PM013, PM035 |
| Infrastructure | PM001 | PM008, PM023 |
| Budgets | PM002 | PM024 |
| Audit | PM025 | PM013, PM008, PM033 |
| Run Detail | PM011, PM012 | PM010, PM013, PM005, PM021 |

## Acceptance rules for every task

- Preserve existing supported behavior and immutable published inputs, results and audit history. New operations enforce the existing tenant, project and role boundaries; concealed resources remain concealed.
- Exercise the actual API path and a browser journey for user-facing changes. Simulation and Storybook fixtures can verify UI states but cannot establish real execution, model quality, external loading or serving readiness.
- Verify relevant validation, unavailable prerequisites, permission denial, network failure and retry behavior. Chargeable writes require an explicit review of scope and usage assumptions, with idempotency for uncertain submissions.
- Record the tested application revision, resources, runtime and hardware when execution is involved. Scope capability claims to that envelope; unknown values remain unknown.
- Changed controls work with keyboard navigation and narrow layouts. Completion requires the appropriate automated checks and evidence named in the task, rather than a passing chart or saved status label alone.

## P0 blockers

### PM001 Enable compute setup from Infrastructure

**Screens:** Infrastructure, Overview, Training, Models. **Proposed owner:** Platform and frontend. **Dependencies:** None.

**Task:** Add an administrator setup flow for one supported local worker, pool and installed runner. Reuse the existing worker protocol and trusted operator-installed executor model.

**Acceptance criteria:**

- An administrator can register a pool and worker, select an installed compatible runner, and obtain startup instructions from the product without composing raw API requests.
- Registration returns a one-time scoped credential through a protected setup view; ordinary inventory, logs and persisted browser drafts never expose it. Revocation is available and auditable.
- Setup remains incomplete until a live heartbeat reports matching capabilities. Offline, stale, incompatible and busy workers have distinct explanations; configured slots alone cannot make compute ready.
- A real worker claims a bounded training job on the declared reference host. Registration, reconnect and credential-revocation checks pass; unauthorized roles cannot administer workers.

### PM002 Create and manage usable training budgets

**Screens:** Budgets, Overview, Training, Dataset Bank. **Proposed owner:** Accounting backend and frontend. **Dependencies:** None.

**Task:** Add the missing policy list and administrator editor, starting with training-step policies and the units required by existing acquisitions.

**Acceptance criteria:**

- An authorized administrator can create, enable, edit and disable a policy, with explicit tenant/project applicability, unit, period and positive limit. Resource quantities and monetary currencies cannot be confused.
- The policy view shows committed usage, active reservations and remaining allowance; Training can select an enabled compatible policy immediately after creation.
- A launch reserves usage atomically. Concurrent launches cannot exceed the limit, and cancellation/failure settles the actual committed quantity exactly once.
- Disabled, exhausted or incompatible policies produce corrective actions. Unknown prices remain unpriced and never appear as zero cost.

### PM003 Guide users to executable model configurations

**Screens:** Models, Chat, Training, Evaluation. **Proposed owner:** Model runtime and frontend. **Dependencies:** PM001 for Hub acquisition.

**Task:** Surface the compatibility already enforced by the runtimes before users invest in an import or launch.

**Acceptance criteria:**

- A model version shows whether its actual committed artifacts support Chat, Training and Evaluation, including architecture, tokenizer/template, format, device and measured or declared limits.
- A supported local snapshot and a supported worker-acquired snapshot each become selectable in the appropriate flows after verification. Metadata registration alone does not make either executable.
- Unsupported model/device/recipe combinations are excluded or disabled with a reason; a registered 7B/8B model is not implicitly presented as supported by a bounded small-model runtime.
- The import flow explains missing capacity and gated-access setup, reports verified progress, and links to the resulting version. Compatibility is rechecked before allocation.

### PM004 Finish the Overview setup journey

**Screens:** Overview and the workspace shell. **Proposed owner:** Product frontend and platform. **Dependencies:** PM001, PM002, PM003.

**Task:** Turn each missing prerequisite into an actionable setup step and make dashboard claims consistent with execution evidence.

**Acceptance criteria:**

- A fresh authorized project reaches an approved real training preflight through linked product flows, without manual API calls. One-time execution of the product-generated worker startup command may remain a disclosed host setup step.
- Missing worker and budget steps open the setup/editor flows rather than read-only dead ends. Readiness survives reload and is recalculated after resource or project changes.
- Every surfaced evaluation result identifies its execution-evidence level. Simulation, legacy unknown evidence, local execution and production qualification remain distinct.
- Recent activity opens the exact selected job/run. A keyboard-only pilot records setup duration, blockers and completion on a fresh workspace.

### PM005 Evaluate the transformer candidates produced by Training

**Screens:** Evaluation, Training, Models, Run Detail, Budgets. **Proposed owner:** Evaluation runtime, platform and frontend. **Dependencies:** PM001, PM002, PM003.

**Task:** Extend the evaluation execution contract beyond CPU character bundles to one existing real transformer training profile, then expose its capability precisely.

**Acceptance criteria:**

- An actual candidate produced by the supported transformer profile and its pinned baseline execute the same frozen held-out suite through a durable job; outputs come from verified weights, not expected-answer echoes.
- Preflight pins candidate, baseline, suite, scorer, tokenizer/template, decoding and runtime, and rejects incompatible inputs or known training/evaluation source-group overlap before allocation.
- Case outputs, failures, sample counts, slice metrics and uncertainty are committed with provenance. Partial execution exposes completed, missing and failed cases and cannot report a complete passing evaluation.
- Progress and cancellation are visible through Run Detail. Interruption, duplicate completion and uncertain submission do not duplicate results or charges; existing CPU character evaluation remains available.

### PM006 Create and review a candidate release from evaluation evidence

**Screens:** Releases, Evaluation, Models, Training. **Proposed owner:** Release backend, evaluation and frontend. **Dependencies:** PM005.

**Task:** Connect a real candidate and its evaluations to an immutable release review and independently loadable export.

**Acceptance criteria:**

- A user can select an actual completed candidate, create a release revision in the browser, and attach exact compatible evaluation, license and provenance evidence.
- The review shows required criteria, thresholds, measured results and missing/failing evidence. Evidence for another candidate or incompatible protocol cannot satisfy a gate.
- An authorized download contains the supported model or adapter bytes, required base reference, tokenizer/configuration, manifests, hashes and notices. A clean consumer outside ModelAnvil verifies and loads it and performs bounded inference.
- Local export review never sets production qualification. Export copy accurately distinguishes actual bytes from metadata previews, and endpoint-record creation remains separate from deployment.

### PM007 Implement verified serving and deployment lifecycle

**Screens:** Releases, Infrastructure, Run Detail. **Proposed owner:** Serving platform and evaluation. **Dependencies:** PM005, PM006. **Gate:** Production serving.

**Task:** Deliver one authenticated serving backend with actual readiness, evidence-backed promotion and rollback.

**Acceptance criteria:**

- Deploying a supported release starts a real serving process, verifies its exact artifacts and serves an authenticated test request. Creating an endpoint record alone never reports serving readiness.
- A trusted qualification path records independently verified runtime, quality and deployment evidence; client metadata, fixture gates and policy exceptions cannot manufacture or waive required production evidence.
- Promotion preserves the previous active deployment until the new one passes readiness. Failure leaves a visible failed attempt and does not silently move the active endpoint.
- Rollback loads the selected previously qualified revision, rechecks current permissions and compatibility, and verifies service health. Operator interruption and unhealthy startup are exercised on the declared topology.

### PM008 Qualify the production operating environment

**Screens:** Infrastructure, Releases, Budgets, Audit. **Proposed owner:** Operations and platform. **Dependencies:** PM007. **Gate:** Production operation.

**Task:** Qualify the deployment and recovery foundations needed to operate the serving slice outside local development.

**Acceptance criteria:**

- The chosen deployment uses authenticated TLS, a production application server and managed secret provisioning. Development credentials and the development server are excluded from its deployment configuration.
- A restore drill recovers database and artifact state and verifies manifests, accessible releases, job ownership and accounting consistency without duplicate execution or charges.
- Database, broker, worker and storage interruption drills document observed recovery and unresolved ownership. The supported storage provider passes the applicable transfer and integrity checks.
- Installation and upgrade from the packaged revision are exercised on a clean reference environment. The support matrix names the tested topology, recovery evidence and remaining exclusions; other topologies remain unqualified.

### PM009 Prove the complete local beta journey

**Screens:** Overview, Datasets, Models, Training, Chat, Evaluation, Releases. **Proposed owner:** Product acceptance and engineering QA. **Dependencies:** PM001, PM002, PM003, PM004, PM005, PM006.

**Task:** Run the first complete journey against the packaged application and a fresh project, and prevent running-build drift from obscuring readiness.

**Acceptance criteria:**

- The packaged app displays its revision and presents the committed JSONL, CSV, JSON and DOCX import capabilities accurately. Browser and API capability checks identify incompatible versions rather than silently omitting features.
- A fresh project publishes data, acquires/initializes supported prerequisites, trains actual weights, runs candidate inference, executes a held-out candidate/baseline evaluation and downloads the exact reviewed candidate.
- The pilot records artifact hashes, runtime/hardware, committed steps, evaluation outputs and external loading. A failing candidate remains failed; success means the journey works, not that every model passes quality gates.
- Reload/reconnect and queued/running cancellation preserve the recorded resources and report actual outcomes. The result establishes the local beta envelope and does not certify production serving or complete R1 coverage.

## P1 usability and connected workflows

### PM010 Preserve unfinished work across navigation

**Screens:** Training and other authoring forms, Annotation, Chat, Context Lab. **Proposed owner:** Frontend. **Dependencies:** None.

**Task:** Preserve form drafts and make discard behavior explicit using a consistent scoped draft policy.

**Acceptance criteria:**

- The reproduced Training case retains a changed total-step value after leaving the page and returning. Recipe choices and other unsaved configuration follow the same behavior.
- Drafts are isolated by organization, project and form/resource; changing scope never submits another scope's draft. Credentials are never included in saved drafts.
- Each affected form exposes saved/unsaved state, restore and explicit discard behavior. Sensitive content uses a disclosed storage policy rather than silent indefinite retention.
- Reload, back/forward and transient failure checks preserve the expected draft. Restoring a draft still requires current permissions, input validation and fresh preflight before launch.

### PM011 Add safe self-service run recovery

**Screens:** Run Detail, Training, Workflows. **Proposed owner:** Job platform, accounting and frontend. **Dependencies:** PM001, PM002.

**Task:** Add an idempotent recovery action for a failed/interrupted supported training execution, preserving its history and accounting contract.

**Acceptance criteria:**

- Eligible runs expose Resume from the selected verified checkpoint, with exact step, pinned inputs, optimizer/runtime compatibility and remaining required budget. Ineligible runs explain each blocker.
- Recovery creates an explicitly linked execution with a new reservation where required by the existing one-settlement-per-job accounting contract. It does not rewrite or recharge previously committed work.
- Concurrent requests and uncertain retries produce at most one recovery execution. Active or unknown ownership, unresolved cancellation, corrupt checkpoints, exhausted budget and unauthorized roles block restart.
- An interrupted real worker resumes the supported state and produces the expected continuation under the declared replay limits. Parent attempts, checkpoints, usage and failure evidence stay readable.

### PM012 Correct Run Detail presentation and errors

**Screen:** Run Detail. **Proposed owner:** Frontend and API. **Dependencies:** None.

**Task:** Fix the reproduced absent-job error and render information appropriate to each run type.

**Acceptance criteria:**

- A simulated training run with no durable job shows No worker job and does not request unavailable attempt history or display a resource-not-found alert.
- Training shows supported training/validation measurements, evaluation shows case metrics and uncertainty, and ordinary jobs show relevant execution state without an irrelevant loss panel.
- Nested metric values remain inspectable and never render as `[object Object]`. Missing metrics are distinct from failed loads.
- Back navigation returns to the originating list with selection/filters; long history, stale updates and narrow-layout checks pass.

### PM013 Link exact resources and their lineage

**Screens:** Run Detail, Datasets, Models, Evaluation, Releases, Audit. **Proposed owner:** Frontend and resource APIs. **Dependencies:** None; integrate PM006 when available.

**Task:** Add stable resource/version routes and contextual handoffs across the main journey.

**Acceptance criteria:**

- Model-version and dataset-revision links from a run open those exact authorized records after reload, rather than generic lists. Unavailable records show an appropriate scoped state.
- Dataset revisions expose Train, Annotate, Evaluate or Index only where eligible; model versions expose compatible Chat, Train, Evaluate and Release actions with the selected version carried forward.
- A candidate's view follows its dataset, recipe, run, checkpoints, evaluations and release; an audit event opens its exact resource or explains deletion/access loss.
- Receiving forms revalidate pinned references and preserve immutable launched configurations. Browser back/forward retains the source selection and filters.

### PM014 Restore Dataset Bank acquisitions and review their scope

**Screen:** Dataset Bank. **Proposed owner:** Data backend and frontend. **Dependencies:** None; use PM001/PM002 for new executions.

**Task:** Recover persisted acquisition state on return/reload and show a concrete acquisition review before launch.

**Acceptance criteria:**

- Returning to a source restores its authorized acquisition/job history, verified progress and cancel/resume actions from server records. Page-local state is not the only way to find a transfer.
- Preview shows real bounded samples, pinned upstream revision, license obligations, destination, supported scope/subset and known/unknown size and usage; unqualified connectors remain blocked with a reason.
- Confirmed acquisition uses the selected scope and budget. Interruption resumes verified work; cancellation or failure never publishes a complete dataset prematurely.
- The completed acquisition links to its exact published revision and preserves attribution and integrity evidence. Changed upstream revisions create separate records.

### PM015 Make Datasets a preparation and revision workbench

**Screen:** Datasets. **Proposed owner:** Data backend and frontend. **Dependencies:** None.

**Task:** Extend existing import/publication with preview, record inspection, configurable preparation and complete browsing.

**Acceptance criteria:**

- JSONL, CSV, JSON and DOCX imports show a bounded parsed preview, field mapping and excluded-content limits before publication. Invalid records link to examples and errors.
- Users inspect preparation changes, drop/deduplication reasons and actual source-group split assignments. Insufficient independent groups are visible when requested validation/test allocation cannot be achieved.
- Existing datasets and revisions have pagination/search and exact revision inspection; resources beyond the first page are reachable. A changed recipe creates a new immutable revision.
- Long uploads expose progress and supported cancellation/resume behavior, or explicit limits with a recoverable failure. A failed preparation can be inspected/retried without silently duplicating published resources.

### PM016 Connect Annotation review to sources and training data

**Screens:** Annotation, Datasets, Training. **Proposed owner:** Annotation and data frontend/backend. **Dependencies:** PM013, PM015.

**Task:** Select existing source revisions, improve human review and publish approved labels as a usable dataset revision.

**Acceptance criteria:**

- Campaign setup selects an authorized source revision and reserves protected source groups; batch selection excludes protected, reused and training-ineligible examples without manual JSON copying.
- Review supports keyboard controls, visible save/conflict/offline state and recovery of unsaved edits. Span/rubric schemas use validated dedicated editors or remain explicitly unsupported.
- Reviewer assignment, escalation and adjudication retain attribution and original predictions. Independent audit mode can hide predictions; unresolved disagreements block approval/closure according to policy.
- Closing a reviewed batch publishes approved labels into the supported training schema with source/rubric provenance and protected splits. Train this snapshot opens the exact eligible revision; rejected/skipped examples remain excluded.

### PM017 Complete the iterative labeling campaign

**Screens:** Annotation, Training, Evaluation, Budgets. **Proposed owner:** Annotation orchestration and ML. **Dependencies:** PM005, PM011, PM016.

**Task:** Connect one declared text-labeling task through drafting, review, actual retraining, independent qualification and next-batch assignment.

**Acceptance criteria:**

- Both manual-seed and existing-model-seed journeys complete two actual train-and-next-batch cycles on the supported task, preserving human corrections and exact drafting-model revisions.
- Only approved cumulative snapshots train a candidate. A held-out source-group audit evaluates the candidate independently of assisted review; insufficient data blocks promotion.
- Passing candidates can be assigned to future batches; failing/regressing candidates preserve the previous assignment. Rollback affects future work without changing prior batches or labels.
- Real stage reservations enforce spend/cycle limits. Pause, cancellation, duplicate dispatch and interrupted recovery stop unsafe progression; automatic advance is bounded and never bypasses human review.

### PM018 Add model version inspection and import recovery

**Screen:** Models. **Proposed owner:** Model acquisition backend and frontend. **Dependencies:** PM003, PM013.

**Task:** Provide version/artifact inspection and controls for imports already supported by the backend.

**Acceptance criteria:**

- Selecting a model opens its immutable versions, verified weight/tokenizer references, licenses, lineage, supported capabilities and matching evaluation evidence.
- Users find imports beyond the first page and reopen their exact progress/job. Cancel/resume/retry controls reflect supported transfer behavior and actual worker acknowledgement.
- Local imports show per-file progress and recover from partial uploads without silently reuploading already verified artifacts. Limits and required files are checked before costly work.
- An interrupted/corrupt import cannot create an executable version. Successful acquisition opens the exact new version and appropriate compatible action.

### PM019 Make Chat sessions usable and connect arena feedback

**Screens:** Chat, Models, Annotation. **Proposed owner:** Inference frontend/backend. **Dependencies:** PM003, PM013; PM016 for feedback publication.

**Task:** Improve session management, runtime guidance and the handoff from informal comparisons to reviewed preferences.

**Acceptance criteria:**

- Eligible models and devices are filtered by current capability. The composer shows the actual supported context/output limits and rejects overflow before generation where determinable.
- Users search/page saved conversations, rename and explicitly delete them, and understand whether partial or completed output has been saved. Runtime errors preserve recoverable user input.
- A saved comparison preserves exact inputs, outputs, settings and vote attribution. It remains labeled informal, and can enter an authorized review batch without becoming qualified human feedback automatically.
- Switching conversation/model/device during execution cannot mix responses or save to the wrong conversation. Stream failure and stop release the runtime and report actual save state.

### PM020 Finish the Training experiment workbench

**Screen:** Training. **Proposed owner:** Training runtime and frontend. **Dependencies:** PM003, PM010, PM011, PM013.

**Task:** Add supported configuration, measured pilot launch and meaningful run comparison around the existing runtimes.

**Acceptance criteria:**

- The form exposes only parameters supported by the selected recipe, including applicable optimizer/schedule, validation and checkpoint controls. Defaults and pinned profile limits are visible.
- A bounded pilot is a real metered execution whose measured runtime can inform an estimate for the same compatible configuration. Unknown monetary cost stays unknown.
- Users browse all runs and compare changed inputs plus compatible training/validation metrics. Curves from incompatible recipes/protocols are not presented as a fair quality comparison.
- QLoRA quality evidence distinguishes its quantized and unquantized baselines. The known failing bounded candidate remains failed until new independent evidence satisfies the declared gate; execution success cannot override quality failure.

### PM021 Extend Alignment through one real transformer workflow

**Screens:** Alignment, Annotation, Evaluation, Run Detail. **Proposed owner:** Alignment runtime and platform. **Dependencies:** PM005, PM011, PM016.

**Task:** Keep the existing CPU reference recipes and deliver one explicitly supported transformer alignment recipe with durable execution and evidence.

**Acceptance criteria:**

- Reviewed preferences publish immutable training/held-out artifacts with actual source separation; preflight validates policy/reference/reward compatibility and required resources for the chosen recipe.
- Actual transformer updates produce verified candidate weights. The supported algorithm is named; other methods remain limited to their existing qualified envelope rather than inheriting support.
- Alignment has a durable run route, stage progress, cancellation, compatible recovery, measured usage and component lineage. For learned-reward RLHF, rollout, scoring and updates are separately inspectable.
- Independent evaluation compares the candidate and baseline; reward growth alone cannot pass a release gate. Interruption, invalid numeric values and corrupted inputs stop safely without duplicate commitments.

### PM022 Build a typed workflow composer

**Screens:** Workflows and Run Detail. **Proposed owner:** Workflow platform and frontend. **Dependencies:** PM005, PM006, PM011, PM013.

**Task:** Replace raw-job-only composition with one saved versioned workflow made from existing supported stages.

**Acceptance criteria:**

- Users compose a data-to-training-to-evaluation-to-export workflow through typed stage forms and an equivalent accessible structured view. Raw JSON is optional for advanced configuration.
- Validation rejects cycles, missing inputs, incompatible ports, unavailable permissions/resources and insufficient budget before launch; human-review nodes wait for actual authorized decisions.
- A launched workflow freezes its graph and resource revisions. Its timeline links each node to the real job, committed outputs and failure cause; changing a template cannot change an active run.
- Retrying a failed node preserves successful history and reruns affected downstream stages. Reuse is allowed only for exact input/configuration matches with current access; uncertain retries cannot duplicate chargeable work.

### PM023 Add operational capacity and worker controls

**Screen:** Infrastructure. **Proposed owner:** Scheduling platform and frontend. **Dependencies:** PM001.

**Task:** Extend inventory with actual capacity, queue diagnosis and safe administration.

**Acceptance criteria:**

- The screen distinguishes configured, free and allocated capacity using authoritative worker/allocation records and freshness; stale or unavailable measurements remain explicit.
- Queued jobs show missing capabilities, unavailable resources, queue age and applicable contention rather than simply an active pool label.
- Authorized operators can drain a worker/pool, observe acknowledgement, and prevent new claims while retaining configured completion/checkpoint behavior for active work.
- Credential revocation, supported egress-policy changes and reconnect are auditable and do not hide unresolved ownership. A disconnect/reconnect drill shows actual allocation and recovery state.

### PM024 Explain budget attribution and reservation use

**Screen:** Budgets. **Proposed owner:** Accounting and frontend. **Dependencies:** PM002, PM013.

**Task:** Add filters and drill-downs that explain who/what consumed or reserved each budget.

**Acceptance criteria:**

- Date, project, unit and currency filters have explicit scope; tenant-wide policies are not mislabeled as project-only values.
- Usage and reservation rows open the exact jobs, adjustments and policy periods. Users distinguish estimated reservations from committed usage and released amounts.
- Policy thresholds expose remaining allowance and an in-product alert with freshness. Forecasts identify their measured basis or remain unavailable; mixed units/currencies are never summed into an invalid total.
- Filtered totals reconcile with the immutable ledger, including concurrent settlement, corrections and unpriced events. A complete scoped export declares its period and completeness.

### PM025 Support complete audit investigation

**Screen:** Audit. **Proposed owner:** Audit backend and frontend. **Dependencies:** PM013.

**Task:** Replace loaded-row-only investigation with server filtering, complete scoped export and actionable resource history.

**Acceptance criteria:**

- Server-side date, actor, action, outcome, project and resource filters find matching events beyond the currently loaded page and survive reload/back navigation.
- Resource history opens the exact authorized record and distinguishes deletion, access loss and unavailable historical content.
- Export includes the complete selected scope through a bounded snapshot/paginated process, with period, filters, count and completeness metadata; a partial export is visibly partial.
- Representative setup, launch, cancellation, recovery, review, promotion and denied actions appear with reliable attribution. Empty audit results do not conceal a failed query; cross-project access checks pass.

## P2 advanced workflows and remaining R1 scope

### PM026 Build versioned RAG sources and recoverable indexes

**Screens:** RAG, Datasets, Run Detail. **Proposed owner:** Retrieval and data platform. **Dependencies:** PM001, PM002, PM013, PM015.

**Task:** Extend pasted-text lexical indexing to authorized dataset sources and durable versioned index construction.

**Acceptance criteria:**

- Users select exact authorized source revisions and inspect extraction/chunk boundaries, hashes, locations and supported chunking/index settings before launch.
- Index construction runs as a durable metered job with progress, failure inspection and supported recovery; partial builds cannot become complete queryable indexes.
- Updating sources creates an immutable new index version while preserving prior membership and lineage. Source revocation/deletion is enforced against old indexes and query results.
- All knowledge-base/index pages are reachable. A real import, interrupted build, resume and source-deletion journey passes on the declared corpus size.

### PM027 Complete RAG answering and independent evaluation

**Screens:** RAG, Evaluation, Context Lab, Releases. **Proposed owner:** Retrieval, inference and evaluation. **Dependencies:** PM005, PM006, PM026, PM029.

**Task:** Add one measured dense/hybrid retrieval pipeline with supported reranking, actual context assembly, generation and evaluation.

**Acceptance criteria:**

- Users select supported retrieval modes and pinned encoders/reranker/generator/context recipe. Dimension and protocol incompatibility block execution before allocation.
- The trace separates retrieved candidates, reranked results, supplied context and actual answer, with timings and measured tokens. Citations open exact authorized source spans; missing evidence supports explicit abstention.
- Versioned relevance judgments and answer cases produce retrieval and answer metrics separately, with cutoffs, coverage, sample counts and N/A semantics. Lexical and new modes are compared on the same frozen queries.
- Permission/deletion overlays apply to indexes, answer traces and caches. Only independently passing pipeline evidence can enter the applicable release review.

### PM028 Add a real cluster explorer to RAG

**Screen:** RAG. **Proposed owner:** Retrieval visualization and frontend. **Dependencies:** PM026, PM027.

**Task:** Add saved projection and evidence investigation using actual embedding data.

**Acceptance criteria:**

- Projection coordinates come from the declared algorithm and pinned vectors; the view reports method, sampling, input count and limits instead of manufacturing coordinates.
- Queries and relevant/failed evidence can be overlaid and filtered by source/task. Neighbor inspection uses original embedding space rather than treating projection distance as similarity.
- Keyboard and table alternatives support the same selected records as the visual view, including the qualified corpus bound.
- An eligible failure selection can enter review with origin and split checks; revoked/deleted evidence cannot return through saved projections or exports.

### PM029 Author context revisions and count actual model tokens

**Screen:** Context Lab. **Proposed owner:** Context compiler and frontend. **Dependencies:** PM003, PM010, PM013.

**Task:** Extend the fixed three-block form into a versioned editor tied to a supported model/tokenizer/template.

**Acceptance criteria:**

- Users create, reorder, edit and version supported instructions, evidence, examples, history and tool blocks; existing published recipes remain immutable.
- Compilation previews the exact serialized model input with provenance, per-block allocation, transformations, omissions and output reserve.
- Token counts match the selected pinned runtime tokenizer/template. Unsupported exact counting remains visibly estimated and cannot claim guaranteed capacity.
- Overflow, missing variables, contradictory priority and essential-block truncation have actionable errors. Editing/navigating preserves drafts and the selected immutable version.

### PM030 Run measured paired Context Lab experiments

**Screens:** Context Lab, Evaluation, Releases. **Proposed owner:** Application ML and evaluation. **Dependencies:** PM005, PM006, PM029.

**Task:** Execute actual paired recipe comparisons and one bounded declared sweep against frozen cases.

**Acceptance criteria:**

- Two recipes run the same pinned model, cases and decoding protocol, recording actual outputs, task scores, input/output tokens, latency and measured or unknown cost.
- Users inspect block diffs, case failures, evidence retention and stochastic variance where applicable; compiler estimates and deterministic fixture scores cannot substitute for model results.
- Frozen history/memory/tool fixtures exercise missing evidence, overflow, injected instructions, tool errors and cross-session isolation within the declared supported envelope.
- A recipe can enter review/promotion only with the required compatible evidence. Failing comparisons preserve the prior selected recipe and remain inspectable.

### PM031 Implement real scratch training

**Screens:** Training, Models, Evaluation. **Proposed owner:** Training runtime and platform. **Dependencies:** PM001, PM002, PM005, PM011, PM032.

**Task:** Deliver one declared architecture with actual random initialization, published data consumption and worker execution. Keep synthetic scratch fixtures explicitly separate.

**Acceptance criteria:**

- The browser configures the supported architecture and random seed with a pinned tokenizer, data/splits, precision and resource profile; preflight rejects unsupported combinations.
- Actual training updates randomly initialized tensors using published samples and records loss, validation, throughput, checkpoints and measured usage with reproducible inputs.
- Cancellation and compatible checkpoint recovery restore required optimizer/sampler state without duplicate committed steps or charges, within documented replay limits.
- A clean independent consumer loads the exported candidate and runs inference; an independent held-out evaluation executes. The result satisfies the declared scratch journey rather than a fixture status label.

### PM032 Add tokenizer training and inspection

**Screens:** Models, Training, Datasets. **Proposed owner:** Tokenizer runtime and frontend. **Dependencies:** PM001, PM002, PM015.

**Task:** Add a tokenizer workbench around actual assets and one supported tokenizer-training recipe.

**Acceptance criteria:**

- Users import verified tokenizer assets or train one from a pinned corpus through a durable metered job, preserving corpus and recipe lineage.
- Inspection shows vocabulary/special tokens, supported language or corpus coverage and measured sequence-length examples; metadata-only registration is clearly distinct.
- Changes create immutable versions. Vocabulary, special-token and template incompatibility blocks use with an existing model before launch.
- The saved/exported tokenizer reproduces sampled encodings in an independent supported consumer, and interrupted training never registers an incomplete ready version.

### PM033 Add workspace and permission administration

**Screens:** Workspace shell and new administration surfaces. **Proposed owner:** Identity platform and frontend. **Dependencies:** None; align with PM001 and PM002.

**Task:** Expose existing organization/project/team/grant administration and supported integration settings through scoped product controls.

**Acceptance criteria:**

- Authorized administrators manage project/team membership and resource/action grants; users can inspect their effective permissions and receive actionable denials.
- API-key creation, revocation and supported rotation use protected flows with one-time secrets and audit attribution; ordinary lists and drafts do not expose credentials.
- Supported storage, Hub access and integrations have validated configuration and connection checks. Installed executable extensions remain an explicit trusted administrator action.
- Restricted users cannot view/administer other projects or settings, and permission changes take effect on existing routes and caches. Unsupported identity integrations remain labeled unavailable.

### PM034 Generate synthetic data through a reviewed workflow

**Screens:** Annotation, Datasets, Workflows. **Proposed owner:** Data generation and ML platform. **Dependencies:** PM001, PM002, PM003, PM016.

**Task:** Add a bounded generation flow using one supported model and pinned training-eligible prompts.

**Acceptance criteria:**

- The configuration pins source prompts, model, template, decoding, output schema, scope and budget; protected evaluation sources are rejected before launch.
- A durable job records actual generated outputs, failures, origin and usage. Partial/cancelled jobs expose their actual completeness and cannot silently publish ready training data.
- Human review accepts/corrects/rejects generated items; accepted records preserve synthetic origin and all transformations rather than relabeling them as independent human data.
- Publication creates an immutable compatible dataset revision. Invalid outputs, duplicate callbacks, contaminated inputs and insufficient budget are exercised.

### PM035 Convert and evaluate actual quantized releases

**Screens:** Releases, Evaluation, Chat. **Proposed owner:** Model conversion and evaluation runtime. **Dependencies:** PM005, PM006.

**Task:** Replace simulated release-conversion results with one supported actual quantization/export path. Keep native training-time QLoRA evidence separate.

**Acceptance criteria:**

- Conversion produces actual committed bytes from a pinned source candidate and records conversion/runtime versions, hashes and target compatibility.
- Original and converted candidates run the same frozen evaluation and independent loading protocol. Report measured quality changes, size and applicable runtime behavior rather than fixed compression/accuracy values.
- Missing, failing or excessive-regression evidence blocks qualification/promotion; conversion success alone does not pass the gate.
- Corrupted outputs, unsupported formats and interrupted conversion fail without exposing a completed loadable artifact or rewriting the original release.

## Completion and tracker handoff

For each task, retain its ID, proposed owner role, dependencies and acceptance criteria when creating implementation tickets. Relate it to existing tracker work only after checking the current scope and evidence; do not duplicate accepted implementation under an old missing-feature description.

The local beta closes with PM009. Production serving additionally requires PM007 and PM008. Full R1 acceptance still requires the applicable scratch, labeling, alignment, retrieval/context, data-diversity and operational scenarios in the [PRD](PRD.md) and [engineering implementation plan](engineering/implementation-plan.md); completing the local beta must not be represented as complete R1 delivery.
