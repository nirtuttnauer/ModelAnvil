# ModelAnvil Product Requirements

Product requirements document

Version 0.7 | 8 October 2026 | Status: Proposed baseline for product and engineering review

## 1 Product definition

We will build ModelAnvil, a platform that lets many teams create, improve, evaluate, and release open-weight language and multimodal models. It will connect data collection, cleaning, annotation, synthetic data, training, reward modeling, retrieval-augmented generation (RAG), context engineering experiments, evaluation, compute management, and model distribution in one workspace.

The first release must support both training a model from randomly initialized weights and adapting an existing model. Organizations must be able to use managed cloud or a fully self-hosted installation. Hybrid operation will connect the hosted workspace to customer-controlled workers and storage.

The platform will preserve the relationship between source data, transformations, labels, training runs, model artifacts, and evaluation results. A team must be able to explain how a model was produced, compare it fairly with alternatives, and export the artifacts and recipe needed to reproduce its workflow.

Broad format coverage is a product requirement. The platform must distinguish importing a file, inspecting and annotating its content, and training a compatible model. Custom formats will use field mappings or versioned extensions. Model compatibility must remain explicit.

This document defines product behavior and release evidence. Version 0.7 adds an iterative human-reviewed labeling and model-training cycle alongside RAG implementation, retrieval and answer evaluation, an embedding cluster explorer, and context engineering experiments, retaining the ideal customer profile, application stack, complete RLHF requirement, open Dataset Bank, and job dispatch design. Section 8 records the selected planning baseline and the integrations requiring qualification. Numeric service targets, exact dependency versions, hardware configurations, and multimodal training recipes require validation. No delivery date, engineering budget, or platform license has been set. These are product and architecture specifications; application services, connectors, and training integrations are not implemented.

### 1 1 Confirmed direction and proposed choices

| Topic | Status | Direction |
| --- | --- | --- |
| Training paths | Confirmed | Pretraining from scratch and fine-tuning from the first release |
| Audience | Confirmed | A platform serving many teams |
| Deployment | Confirmed | Managed cloud and self-hosted; hybrid included in the deployment design |
| Data formats | Confirmed | Broad coverage, including custom formats where feasible |
| Core workflow | Confirmed | Collection through training, evaluation, ranking, reward modeling, and release |
| Iterative labeling | Confirmed | Manual or model-assisted seed batch, human correction, labeling-model training, and repeated batch review |
| RAG and context engineering | Confirmed | Build retrieval pipelines, test context strategies, measure quality, and inspect embedding clusters |
| Initial training coverage | Proposed | A tested text architecture plus selected multimodal recipes |
| Capacity and service targets | Proposed | Initial qualification profile in Section 10 |
| Backend engines and licensing | Open | Validate integrations and choose the platform license separately |

## 2 Problem and intended outcomes

Model development currently requires teams to move data and configuration between separate tools. Those transitions can lose provenance, introduce schema mismatches, repeat expensive work, and make comparisons unreliable. A labeling decision may be disconnected from the dataset used in training. A benchmark improvement may hide regressions in another language or task. An interrupted training job may leave incomplete artifacts whose status is unclear.

We want users to complete the full workflow without assembling a new infrastructure stack for each experiment. Experts must retain access to configuration, code extensions, APIs, and exported artifacts. Guided workflows should help less experienced users choose compatible inputs and identify missing prerequisites.

The platform should make improvement measurable against project-specific goals. It will not promise a universally best model. Each project will define its intended tasks, languages, deployment constraints, baseline, and evaluation criteria before comparing candidates.

### 2 1 Product goals

- Complete both training paths inside a shared, versioned workflow.
- Build and evaluate RAG applications and context strategies using the same data, models, and release evidence.
- Reduce the manual work required to prepare data, run experiments, compare results, and package a release.
- Preserve data provenance and model ancestry across team collaboration.
- Allocate compute fairly and make usage and spending visible.
- Expand formats, architectures, and evaluators through documented extension interfaces.
- Let organizations retain control over deployment, data location, and model artifacts.

### 2 2 Boundaries

The first release will publish a tested compatibility matrix. Universal architecture support, unrestricted cluster scale, every proprietary file format, and every reinforcement-learning algorithm are outside the initial guarantee. Foundation training for image or audio generation is separate from conditioning a language model on images or audio and requires its own supported recipe.

Open-weight output does not determine the license of the platform or remove restrictions attached to base models and datasets. Release records must preserve those restrictions and author-selected distribution terms. Autonomous spending or automatic publication will be available only within permissions and policies configured by the organization.

## 3 Ideal customer profile and users

### 3 1 Primary ideal customer profile

Our proposed initial customer is an organization building an AI product or a shared internal model platform, with dedicated ML engineers and multiple teams that repeatedly adapt open-weight models. Its models serve a defined domain, language, or output format, and the organization needs control over training data, evaluation, deployment, and exported weights. This profile is a product hypothesis to validate through customer interviews and pilots; it is not a finding from completed market research.

The strongest fit has usable data rights, subject-matter experts who can judge outputs, access to GPU capacity or a funded compute plan, and an owner accountable for model quality. Company size and geography are secondary to these capabilities. The customer already runs experiments and needs a repeatable workflow that other teams can use.

An initial use case could be a design-software company improving SVG generation. Its ML team imports eligible icon presets and its own authorized examples, reviews render quality, collects human preferences, fine-tunes a model, and runs RLHF when a qualified recipe supports its model and task. It compares candidates on held-out SVG tasks before exporting weights. The same team can compare retrieval from its authorized SVG reference library and different context recipes against a fine-tuned baseline, including their combination. A knowledge-heavy AI product team can instead begin with domain document retrieval and context experiments. These are illustrative customer scenarios, not existing customer commitments.

### 3 2 Customer segments and priority

| Segment | Priority | Fit and adoption path |
| --- | --- | --- |
| AI product companies with dedicated ML teams | Primary | Repeated domain or format-specific model improvement; begin with a bounded adaptation and evaluation project, then expand across teams |
| Enterprise AI platform teams | Secondary | Shared model workflows, identity controls, private data, and internal compute; qualify self-hosted or hybrid operation with their infrastructure team |
| Research organizations and model builders | Secondary | Scratch pretraining, alignment research, custom recipes, and reproducible experiments; begin with a small qualified workload |

Initial customer acquisition should focus on the primary segment while the product retains both scratch training and fine-tuning as first-release requirements. Research customers provide important qualification workloads, but a large foundation-model training program should not determine every early onboarding decision.

### 3 3 Buying committee and daily users

| Role | Typical owner | Decision or need |
| --- | --- | --- |
| Economic buyer | CTO, Head of AI, or AI platform director | Fund the platform and compute; assess total cost and delivery impact |
| Internal champion | ML lead or senior ML engineer | Prove a useful model improvement and get the team to adopt the workflow |
| Daily users | ML engineers, data engineers, evaluators, and annotators | Prepare data, run jobs, review outputs, and compare candidates |
| Technical approver | Infrastructure or security lead | Validate deployment, access controls, worker isolation, and integration |
| Data and procurement approver | Data owner, legal reviewer, or procurement lead | Review source rights, export terms, vendor terms, and purchasing requirements |

One person may hold several roles. Buying authority must be confirmed during discovery rather than inferred from a job title.

### 3 4 Needs triggers and selection criteria

The customer needs to turn authorized source data and expert feedback into a measurable model improvement, then reproduce and release the result. Likely pain points include disconnected labeling and training tools, slow dataset preparation, unclear experiment lineage, unreliable comparisons, and difficulty sharing compute across teams. These are discovery hypotheses to test with examples from the customer's current workflow.

Buying triggers include a new domain model project, an upcoming model release, a second team needing the same infrastructure, or a requirement to move training into customer-controlled infrastructure. A pilot should begin when a team has a named task, baseline, evaluation set, dataset owner, and compute budget.

Selection criteria are demonstrated task improvement, time to a usable experiment, reproducible runs, supported model and format combinations, deployment fit, source-license traceability, and total operating cost. Expected objections include migration effort, overlap with existing tools, training reliability, maintenance of self-hosted installations, and compute costs. Address these through a bounded pilot with artifact export, measured resource use, and a documented compatibility matrix.

### 3 5 Qualification and pilot success

Prioritize customers who can name a recurring model-development problem, provide authorized representative data, assign an ML champion and reviewers, fund a bounded workload, and agree on evaluation criteria. Lower initial priority applies to users seeking only a hosted inference endpoint, organizations without data or compute access, and projects requiring unqualified architectures or modalities. Independent developers may still use the product, but they are not the primary multi-team buying profile.

Before a pilot starts, agree on the task metric, minimum improvement or acceptable tradeoff, maximum spend, completion window, and reviewer responsibilities. Success requires a reproducible candidate compared with its baseline, recorded data and model lineage, measured compute use, and an exportable release package. Track preparation time, time to first evaluated run, human preference results where relevant, and adoption by another team. Numeric thresholds must be agreed per pilot; they are not promised outcomes.

The product implications are guided recipes alongside expert controls, a useful Dataset Bank, human review, visible job and budget status, and portable artifacts. Tenant isolation and deployment choices remain essential even when the first pilot involves only one team.

### 3 6 Users and permissions

| User | Main tasks | Default permission scope |
| --- | --- | --- |
| Organization administrator | Manage identity, teams, storage, workers, and policy | Organization settings and delegated project access |
| Researcher or ML engineer | Prepare recipes, train, debug, and compare models | Assigned projects and compute allocations |
| Data engineer | Collect, extract, clean, and version data | Assigned sources and datasets |
| Annotator | Label, rank, and review assigned examples | Assigned annotation batches only |
| Evaluation lead | Maintain tests, inspect failures, and review releases | Evaluation suites and permitted model candidates |
| Infrastructure operator | Maintain worker pools and investigate job failures | Infrastructure access with separately controlled data access |

The resource hierarchy will be organization, team, and project. Projects contain sources, datasets, annotation campaigns, experiments, models, knowledge bases, retrieval pipelines, context recipes, evaluation suites, and releases. Organizations are the primary isolation boundary. Cross-project sharing requires an explicit grant; cross-organization transfer requires an explicit sharing or publishing workflow.

Permissions must distinguish reading data, editing labels, launching compute, installing executable extensions, exporting artifacts, and publishing a release. A user who can administer workers must not automatically receive access to every dataset through the application.

## 4 Core user journeys

### 4 1 Create a model from scratch

A researcher creates a project, records its goals, selects a supported architecture, and establishes evaluation suites. A data engineer imports sources, previews cleaning rules, removes duplicates, checks evaluation overlap, and creates versioned train, validation, and test splits. The researcher trains or imports a tokenizer, inspects coverage, chooses a data mixture, and runs a small pilot to measure throughput and memory use.

After the pilot, the researcher launches pretraining within an allocated budget. The platform records checkpoints, validation loss, throughput, and hardware use. Interrupted work resumes from a verified checkpoint with its sampler and optimizer state where supported. The team can then run supervised or preference training, compare candidates, and export a release with weights, tokenizer, configuration, and provenance.

### 4 2 Adapt an existing model

A researcher imports a base model at an exact revision, validates its tokenizer and input template, and measures a baseline. The team creates instruction or domain data and launches continued pretraining, supervised fine-tuning, or an adapter run. It compares the candidate with the baseline on intended tasks and protected capabilities before selecting a release.

### 4 3 Improve behavior through human feedback and rewards

The team generates multiple responses to selected prompts. Annotators review randomized, blinded comparisons using a versioned rubric and can record ties, abstentions, and uncertainty. Reviewers resolve disagreements. For RLHF, the team trains and validates a reward model from human preferences, selects a starting policy and reference policy, and optimizes the policy using fresh rollouts scored by that reward model. The run records reward and divergence controls, resource use, checkpoints, and independent evaluations. Reviewers compare the resulting policy with its starting model on held-out prompts before release. New feedback can produce a new reward-model version and another explicitly launched training iteration. DPO remains a separate direct preference-training path; verifier-based RL remains available for tasks with deterministic checks.

### 4 4 Work with multimodal and custom data

A user imports documents, images, audio, video, or structured records. The platform identifies supported content, preserves original assets, and shows extraction and compatibility results. Users can correct mappings, inspect timestamps and spatial annotations, and attach custom fields. Unknown formats can be stored as opaque assets but require an adapter for parsing, preview, or training. The training preflight explains which model and processor can consume the resulting samples.

### 4 5 Collaborate across deployment modes

An administrator provisions an organization, assigns teams and quotas, and connects storage and compute. A hybrid organization chooses which metadata and logs may leave its infrastructure. Two teams can run independently without seeing each other's private artifacts. A permitted user can export a project manifest and artifacts, import them into another installation, and validate missing dependencies before rerunning the workflow.

### 4 6 Build and qualify a RAG application

A team imports authorized documents through existing source connectors, reviews extraction, creates chunks with source locations and permissions, and builds a versioned embedding and search index. It compares lexical, dense, and hybrid retrieval, with optional reranking, before choosing a generator and context recipe. Reviewers label relevant evidence and expected answers. The team evaluates retrieval and answers separately, inspects failures in traces and the cluster explorer, then releases a qualified pipeline through an authenticated query endpoint or an exportable recipe. Source updates create new index versions and must respect deletions and changed access rights.

### 4 7 Test context engineering

An engineer defines a context recipe containing instructions, examples, retrieved evidence, conversation history, memory, tool schemas, and tool results. The engineer inspects the actual ordered model input and token allocation, then compares selection, ordering, trimming, summarization, and memory strategies on the same versioned test cases. Tests vary evidence position, context length, distractors, contradictory information, and missing evidence. Multi-turn cases check memory updates and tool failures. The team reviews quality, retained evidence, cost, and latency before promoting the recipe with a model or RAG pipeline. These experiments can also run without retrieval.

### 4 8 Improve labeling through repeated batches

A team defines a label schema, rubric, source pool, batch size, and quality/budget limits. It either labels the first batch manually or uses an existing model to draft labels, then reviews and corrects them. Approved labels form a versioned training snapshot for a labeling model. The team trains or fine-tunes a compatible candidate, evaluates it on independent human-labeled evidence, and chooses whether it becomes the next drafting model. That model drafts a new batch; reviewers accept, correct, reject, or escalate each example, and the cycle repeats using accumulated approved data.

The cycle dashboard links every batch to its drafts, corrections, reviewed dataset, model revision, and quality results. Users can pause, adjust batch scope, retrain, or restore an earlier drafting model. A failed candidate does not stop manual review or replace the current qualified model. Starting labels from scratch does not require pretraining a foundation model from random weights; use a compatible task model or fine-tuning recipe. A draft's origin remains visible after human approval.

## 5 Release scope and priorities

R1 means the first complete product release. A requirement marked R1 must pass its acceptance conditions before that release. A target describes proposed coverage whose exact support matrix must be settled before implementation commitment. Later items extend the product after the shared workflows are proven. Development milestones can be incremental, but an early fine-tuning-only milestone does not satisfy R1.

### 5 1 Required in R1

Organization and team isolation; managed and self-hosted operation; hybrid worker attachment; data import and controlled scraping; cleaning and dataset versions; human labeling and ranking; iterative manual/model-assisted labeling with review, labeling-model training, and repeated batches; synthetic-data generation; scratch pretraining; continued pretraining and supervised fine-tuning; preference optimization; reward-model training; a complete RLHF loop with at least one qualified learned-reward policy-optimization recipe; at least one verifiable-reward RL recipe; evaluation and comparison; resumable jobs; usage controls; model export and a supported serving path; custom field mappings and extension SDK; a curated open Dataset Bank with a qualified SVG starter preset and extensible source manifests; a qualified text RAG pipeline with retrieval and answer evaluation; an interactive embedding cluster explorer; context recipe composition, controlled experiments, and regression gates.

### 5 2 Proposed initial coverage

Native records for text, image, audio, video, and mixed samples are part of the initial data design. Proposed training coverage includes one supported text architecture for scratch pretraining and a tested image-and-text fine-tuning recipe. The first qualified RLHF recipe must support a declared text-model and hardware configuration. Audio and video training recipes, multimodal RLHF, and additional architectures will receive explicit support levels after feasibility pilots. Their inclusion in the data model does not imply verified training support. RAG and context engineering must initially support a named text-model, tokenizer, embedding model, index, and evaluator combination in managed and self-hosted modes. Multimodal retrieval, GraphRAG, autonomous agent orchestration, and learned context-selection policies require additional qualification and are later targets.

### 5 3 Later expansion

Additional multimodal training recipes, more schedulers and GPU providers, larger qualified cluster configurations, advanced architecture search, richer active learning, distillation, model merging, and broader quantization support can follow through the same interfaces. These additions must preserve provenance and evaluation comparability.

## 6 Functional requirements

All requirements in this section are R1 unless labeled Target. The acceptance statement describes observable evidence, rather than a particular implementation.

### 6 1 Projects and reproducibility

**PRJ01 Project goals.** A project must record tasks, languages, baseline models, budget constraints, evaluation suites, and release criteria. Acceptance: users can save and revise this configuration, and each run retains the exact configuration revision it used.

**PRJ02 Immutable run inputs.** Runs must reference dataset, model, tokenizer, processor, code, environment, extension, and configuration versions. Acceptance: comparing two runs identifies changed inputs; rerunning never silently resolves an input to a newer revision.

**PRJ03 Workflow execution.** Users must compose dependent processing, annotation, training, evaluation, and packaging steps through the UI or API. Acceptance: completed steps can be reused only when their inputs and configuration match; failed steps can be retried without duplicating committed outputs.

### 6 2 Collection and preparation

**DAT01 Source ingestion.** Import local uploads, object storage, dataset repositories, web sources, and API records through selected connectors. Acceptance: every import produces a manifest containing source identity, acquisition time, content hashes, counts, and failures; large transfers can resume.

**DAT02 Controlled collection.** Scraping must support domains, paths, rate limits, crawl budgets, incremental collection, retries, and source access rules. Acceptance: a crawl stops at its configured limits, records extraction failures, and preserves collection configuration and source URLs.

**DAT03 Extraction.** Extract supported document content and media metadata while preserving original assets. Acceptance: users can inspect the extracted result beside its source; pages, timestamps, and asset relationships remain addressable where supported.

**DAT04 Cleaning and privacy.** Support configurable normalization, language detection, quality filters, boilerplate removal, sensitive-information detection, and custom transformations. Acceptance: a preview reports affected examples; execution records retention counts and reasons; detection confidence and review status remain visible.

**DAT05 Deduplication and split integrity.** Support exact and near-duplicate detection, configurable grouping, and train/evaluation overlap checks. Acceptance: seeded duplicate and overlap fixtures are reported; related records can be kept in the same split; reports state the method and limitations.

**DAT06 Dataset versions and mixtures.** Users must inspect, filter, compare, split, mix, tokenize, shard, and export datasets. Acceptance: every published version has a stable manifest, statistics, lineage, and schema; removing a source creates a new version instead of changing a completed run's input.

### 6 2 1 Open dataset bank

**BANK01 Search and discover.** Provide searchable source cards and task bundles with task, modality, type, declared license, obligations, source URL, review date, size, and compatibility. Acceptance: searching SVG returns the curated icon and emoji candidates, while sources with missing or restricted licenses cannot appear as eligible downloads.

**BANK02 Reproducible download.** Resolve mutable references to immutable snapshots, preserve source and license evidence, and create a durable import job with resumable transfers and checksums. Acceptance: repeated downloads of the same source revision yield matching content manifests; interrupted and cancelled transfers do not produce ready datasets.

**BANK03 Preview and scope.** Let users preview and choose sources, sample limits, subsets, splits, and authorized storage. Acceptance: the launch screen distinguishes measured sizes from unknown estimates and validates storage and budget limits before transfer. Runtime downloads happen on authorized workers, never by silently routing private data through hosted services.

**BANK04 Open content policy.** Exclude noncommercial-only, no-derivatives, research-only, and unclear asset licensing. Retain attribution and applicable notices. Make share-alike material an explicit project policy choice. Acceptance: Lucide retains its ISC and MIT notices; Twemoji graphics use their graphics license; OpenMoji is not silently included in the default preset; unknown licenses fail eligibility validation; gated sources require user acceptance and scoped credentials before download.

**BANK05 Preparation and leakage checks.** Attach versioned preparation recipes to presets. Acceptance: the SVG recipe preserves source code, renders isolated images, records available label quality, validates unsupported constructs, deduplicates across libraries, and groups icon variants before splitting. Synthetic descriptions remain distinguishable from human-reviewed labels.

**BANK06 Versioning and tenancy.** Respect organization/project permissions for downloads, previews, caches, prepared datasets, and exports. Acceptance: a source update creates a new version and never changes completed runs; unauthorized organizations cannot access another organization's import artifacts or derived datasets.

**BANK07 Catalog extensions and maintenance.** Allow authorized maintainers to add public or organization-private source manifests through a validated schema. Acceptance: publishing requires license evidence, connector fixtures, a pinned snapshot, and sample validation; changed source terms suspend new downloads until requalification. Catalog entries and preparation recipes have independent versions.

### 6 3 Annotation and synthetic data

**ANN01 Annotation tasks.** Support ideal answers, classifications, spans, pairwise preferences, rankings, and supported spatial or temporal annotations. Acceptance: outputs validate against a versioned rubric and schema; annotators can save progress and report unsuitable examples.

**ANN02 Review quality.** Support task assignment, overlap between annotators, blinded candidate order, ties, abstentions, calibration examples, agreement reports, and adjudication. Acceptance: reviewers can reproduce an assignment and distinguish original labels from adjudicated results.

**ANN03 Human and model labels.** Human, model-generated, and rule-generated labels must remain distinguishable. Acceptance: each label records its author or model revision, rubric, timestamp, and review state; filters can exclude unreviewed model labels from a training export.

**ANN04 Iterative labeling campaign.** Support a manual seed batch and an existing-model draft seed, followed by repeatable review, approved-data snapshot, labeling-model training, qualification, and next-batch prediction. Acceptance: both entry paths complete two train-and-next-batch cycles on a qualified text task; users can set batch sizes, pause/resume, and select unused examples manually or through a reproducible random policy. Protected evaluation examples and source groups cannot enter campaign training.

**ANN05 Draft review and provenance.** Store model predictions separately from human annotation revisions, including accepted-without-edit, corrected, rejected, skipped, and adjudication outcomes. Acceptance: reviewers inspect originals and diffs, correct supported label types, resolve concurrent edits, and approve eligible labels; the campaign's default training snapshot includes only approved annotations. Approval does not relabel a model-origin draft as independently human-authored.

**ANN06 Labeling model lifecycle.** Train or fine-tune from accumulated approved campaign data through qualified adapters, pinning the starting model, data snapshot, rubric, environment, and recipe. Acceptance: independent quality gates control use for subsequent drafts; users can compare, promote, and roll back versions. A batch pins its model revision, and interrupted/duplicate jobs cannot overwrite reviewed labels or silently switch that revision. Automatic progression requires a configured bounded campaign policy and never bypasses required human label review.

**ANN07 Cycle quality and stopping.** Report task-appropriate held-out labeling quality, review outcomes, agreement, reviewed throughput, time per accepted label, label coverage, and compute/human effort by cycle and slice. Acceptance: quality evidence separates independent audits from draft-assisted review; confidence is labeled by source and calibration status where available. Stop or pause on exhausted data, budget/cycle limits, regression, or inadequate training data. A model-confidence value or acceptance rate alone cannot satisfy the quality gate.

**SYN01 Synthetic generation.** Generate examples and candidate responses from permitted local or remote models. Acceptance: jobs record prompts, templates, model revisions, sampling settings, cost, and provenance; users can enforce diversity, correctness checks, and generation budgets.

**SYN02 Failure selection.** Users must turn evaluation failures and disagreements into annotation candidates. Acceptance: selected examples retain their evaluation origin and pass split-integrity checks before entering training data. Automated uncertainty, disagreement, or diversity prioritization is a Target; manual and reproducible random batching for ANN04 are R1. Preserve selection probabilities where available and compare quality on a separate representative audit set.

### 6 4 Model configuration and training

**TRN01 Model registration.** Import existing models and define supported scratch architectures. Acceptance: registration records revision, architecture, tokenizer or processor, artifact hashes, license metadata, and available training and serving capabilities.

**TRN02 Tokenizer workbench.** Train or import tokenizers and inspect vocabulary, special tokens, coverage, and sequence statistics. Acceptance: changes create a new version; incompatible vocabulary or special-token changes are detected before launch.

**TRN03 Scratch pretraining.** Train a supported model from random initialization using a versioned corpus and mixture. Acceptance: a qualification run records initialization, loss, learning-rate schedule, validation results, checkpoints, and exported weights that load independently of the platform.

**TRN04 Adaptation.** Support continued pretraining, supervised fine-tuning, full-weight training, and LoRA or QLoRA where the backend supports them. Acceptance: validated reference recipes complete and export loadable artifacts; unsupported combinations are blocked before GPU allocation.

**TRN05 Training preflight.** Validate schemas, input templates, tokenizer or processor, sequence limits, precision, hardware, available storage, and backend compatibility. Acceptance: the launch screen shows blocking errors, estimates with assumptions, and a pilot option. Estimates are distinguished from measured usage.

**TRN06 Distributed execution and recovery.** Support declared single-node and multi-node configurations with periodic checkpoints. Acceptance: a worker interruption can resume from a verified checkpoint, recording the recovery event and any unsupported state restoration; partial checkpoints never appear as complete.

**TRN07 Monitoring and comparison.** Show loss, validation metrics, throughput, GPU memory, utilization, storage use, and job cost where available. Acceptance: comparable runs can be overlaid; missing measurements are shown as unavailable; early stopping and bounded parameter searches respect project limits.

**TRN08 Multimodal training.** Target: validate an initial image-and-text recipe with its model, processor, data schema, and evaluations. Acceptance: asset order and text alignment survive preprocessing, training, and inference; other modalities explicitly display their support level.

### 6 5 Human feedback preferences and reinforcement learning

**ALN01 Preference optimization.** Train with direct preference optimization using validated preferred/rejected pairs. Acceptance: the run records pair construction, reference-model settings where applicable, and an independent comparison against its starting model. A separate learned reward model is not a prerequisite.

**ALN02 Reward models.** Train, version, evaluate, and register a reward model using preference data. Acceptance: held-out preference performance, source splits, score distributions, and model ancestry are recorded; users can inspect individual scored examples.

**ALN03 Verifiable rewards.** Run at least one supported RL recipe with a versioned deterministic verifier or task environment. Acceptance: reward components, generated trajectories, evaluation results, and resource limits are recorded.

**ALN04 Reward validation.** Training rewards must remain separate from release evaluations. Acceptance: the interface can show rising reward alongside falling task performance; versioned checks include known invalid outputs that would otherwise exploit a weak reward.


**ALN05 Complete RLHF loop.** Support reinforcement learning from human feedback through human preference collection, reward-model training and validation, rollout generation, and policy optimization against the learned reward. Acceptance: at least one named recipe completes on qualified text models and hardware; its manifest pins feedback, prompts, policy, reference policy, reward model, algorithm, and backend versions. PPO and RLOO are candidates; qualification must select at least one, without claiming all algorithms are supported. Users configure reward scaling, divergence controls, rollout/update limits, evaluation intervals, and budgets. Logs distinguish raw reward, penalties, total objective, divergence, response length, and policy/value metrics where applicable. Checkpoints record policy and optimizer state plus critic, sampler, and rollout state where required, with explicit recovery limits. Independent human comparison and regression evaluations record outcomes against the starting policy; rising reward alone never passes release criteria.

The RLHF workflow must display component lineage and compute requirements before launch. Hold the selected reward-model revision fixed within a run unless a qualified recipe explicitly versions a controlled update; new human feedback and reward-model refreshes create linked versions. Preserve the human or synthetic origin of feedback. AI-only judgments must not be labeled human feedback. Reward or divergence limits, invalid numeric values, budget policy, and user cancellation can stop or checkpoint the run under the selected recipe. Rollout generation, scoring, and policy updates share the worker capacity, allocation, leases, and cancellation contract in Section 8 5; stage dependencies must prevent training on incompatible or stale rollout batches.

### 6 6 Evaluation and release

**EVA01 Evaluation registry.** Version benchmark tasks, project-specific tests, human evaluations, judge prompts, datasets, scoring code, and execution environments. Acceptance: each result identifies its complete evaluation configuration and contamination report.

**EVA02 Fair comparison.** Compare candidates under recorded decoding, prompt, tool, and hardware settings. Acceptance: results show task and language slices, sample counts, failures, uncertainty where applicable, and efficiency metrics. Incompatible protocols receive a visible comparison warning.

**EVA03 Judge calibration.** Model judges must be versioned and checked against a human-reviewed sample. Acceptance: results identify the judge and calibration evidence; a judge's score is never presented as objective ground truth.

**EVA04 Release criteria.** Projects must define required evaluations and allowed regressions. Acceptance: a release records pass/fail outcomes; incomplete checks block promotion unless an authorized user records a policy-permitted exception.

**REL01 Export and serving.** Export complete models or adapters with required tokenizer, processor, configuration, model card, hashes, and declared dependencies. Acceptance: an external loading smoke test succeeds; adapter exports identify their required base revision; a supported endpoint can serve the candidate.

**REL02 Optimization and lifecycle.** Provide supported quantization with post-conversion evaluation, release versioning, endpoint promotion, and rollback. Acceptance: optimized artifacts reference their parent and evaluation results; rollback restores a previous compatible endpoint configuration.

### 6 7 Platform operations and extensions

**OPS01 Isolation and access.** Enforce organization and project permissions on APIs, searches, jobs, storage access, logs, and exports. Acceptance: automated cross-organization access tests fail closed across every resource type and alternate access path.

**OPS02 Compute allocation.** Manage worker capabilities, team quotas, priorities, concurrency, and eligible hardware. Acceptance: jobs run only on authorized workers; a team's configured allocation is enforced; distributed jobs wait for their complete resource set rather than occupying unusable partial allocations.

**OPS03 Budgets and accounting.** Track CPU/GPU time, storage, generation APIs, and provider charges where available. Acceptance: every chargeable job has an owning organization and project; budget policy can prevent launch or stop/checkpoint work; delayed provider billing is disclosed.

**OPS04 Job lifecycle.** Provide durable states for validation, queuing, execution, checkpointing, success, failure, cancellation, and interruption. Acceptance: duplicate requests do not create duplicate chargeable jobs; cancellation reports when workers actually stop and resources are released.

**OPS05 Deployment parity.** Core data, training, annotation, evaluation, and export workflows must work in managed and self-hosted installations. Acceptance: the reference journeys pass in both; self-hosted operation has no mandatory cloud dependency after required artifacts are provisioned.

**OPS06 Hybrid boundaries.** Connect customer workers with scoped, revocable credentials and outbound authenticated connections. Acceptance: configured egress rules prevent private samples, logs, and checkpoints from leaving; worker disconnection preserves durable job status and supports reconnection.

**OPS07 Capacity aware dispatch and recovery.** Workers declare capabilities and free slots and accept only authorized, compatible work within those slots. Acceptance: saturated workers receive no additional assignments; duplicate delivery creates no second active attempt; expired leases recover from a verified checkpoint; stale attempts cannot commit results. Broker recovery, retry limits, draining, and distributed resource reservation are tested.

**EXT01 Custom mappings and SDK.** Support no-code field mappings and versioned extensions for readers, schemas, transformations, viewers, trainers, evaluators, and exporters. Acceptance: a sample custom format can be imported, inspected, converted, trained through a compatible adapter, and exported using the documented SDK.

**EXT02 Extension execution.** Isolate executable extensions, custom training code, and evaluation environments from the platform services. Acceptance: permissions, network policy, resource limits, package versions, and installation authority are explicit; unauthorized storage and organization access are denied.

**API01 Programmatic access.** Provide versioned APIs, a CLI, scoped service credentials, and job events for the core workflows. Acceptance: an integration can create a dataset version, submit training, observe completion, run evaluation, and export artifacts without UI-only steps.

### 6 8 RAG implementation and testing

**RAG01 Knowledge base and index versions.** Reuse authorized sources, extraction, cleaning, and dataset lineage. Version chunk boundaries, page or span locations, content hashes, permissions, embedding configuration, and index manifests. Acceptance: a reviewer follows an answer citation to the exact source revision; interrupted indexing resumes without duplicate commits; updates and deletions produce a traceable index version.

**RAG02 Retrieval pipeline builder.** Configure lexical, dense, and hybrid retrieval, metadata filters, rank fusion, optional reranking, and top-K values behind versioned adapters. Acceptance: the same query suite compares all three retrieval modes and a reranked variant, showing candidate IDs, scores, ranks, filters, and model revisions. Invalid embedding dimensions and incompatible query/document encoders fail preflight.

**RAG03 Answer implementation and traces.** Connect a registered generator, context recipe, citation format, and abstention policy to retrieval. Provide an authenticated query endpoint and portable pipeline configuration. Acceptance: a trace links the query, retrieval candidates, reranked results, final supplied context, generated answer, citations, stage timings, and token use; a released version can be restored. Store observable inputs and outputs without requiring private model reasoning.

**RAG04 Retrieval evaluation.** Import or annotate relevance judgments at document, chunk, or evidence-span level with explicit mappings. Compute Recall@K, Precision@K, Hit@K, MRR@K, and nDCG@K at configured cutoffs. Acceptance: a hand-scored fixture matches the evaluator; reports identify label coverage, relevant-unit definition, tie handling, and excluded cases. Judge-based context recall must have a distinct name from ID-based retrieval recall.

**RAG05 Answer and operational evaluation.** Evaluate groundedness, answer correctness and relevance, citation support and coverage, answerability and abstention, robustness, stage latency, token use, and cost. Acceptance: side-by-side runs expose per-query results, slices, sample counts, and uncertainty; judge configuration and human calibration are recorded. Generation quality cannot be inferred from retrieval scores alone.

**RAG06 Experiments and release gates.** Compare chunking, embeddings, index settings, retrievers, rerankers, context recipes, and generators under bounded budgets and protected test versions. Acceptance: a reproducible comparison isolates changed factors, distinguishes development from held-out evaluation, and blocks promotion when configured quality or latency limits fail. A diagnostic run can compare retrieved context with human-supplied evidence.

**RAG07 Embedding cluster explorer.** Provide a saved 2D projection with optional cluster labels, source/task filters, search, hover previews, lasso selection, outlier inspection, and links to chunks and evaluation failures. Overlay a query and its retrieved and labeled relevant evidence, including retrieval rank. Acceptance: selections resolve to stable IDs; neighbors and similarity values use the declared embedding space; projection parameters, sampling, seed, and versions are recorded. A list/table alternative supports keyboard review. Visual separation is never reported as a retrieval-quality score.

**RAG08 Access freshness and recovery.** Enforce document and tenant permissions during retrieval, context assembly, traces, caches, visualizations, and export. Acceptance: permission revocation blocks use immediately within the declared authorization-consistency contract; deleted evidence is suppressed before reindexing completes; failures retain the last complete usable index without re-exposing revoked content. Rollback cannot restore permission or deletion violations.

### 6 9 Context engineering experiments

**CTX01 Versioned context recipes.** Compose typed instructions, examples, user input, retrieved chunks, history, memory, tool definitions, and tool results using explicit source, trust, order, selection, and budget rules. Acceptance: a preview shows the exact serialized messages and token counts for the selected tokenizer/template, plus included, omitted, truncated, or summarized blocks and their provenance. Unsupported model roles or context limits fail validation.

**CTX02 Controlled context experiments.** Compare ordering, selection, chunk packing, few-shot examples, history windows, memory retrieval, compression, and per-block budgets through parameter sweeps and ablations. Acceptance: runs pin model, tokenizer, corpus, recipe, tool fixtures, decoding, and evaluation versions; paired cases and repeated samples expose quality, latency, token, and cost tradeoffs. Input plus reserved output must fit the qualified model limit; blocks cannot disappear silently.

**CTX03 Context stress and multi-turn tests.** Test evidence at beginning/middle/end, increasing lengths, distractors, duplicates, contradictions, stale facts, missing evidence, injected instructions, and context overflow. Include session isolation, memory updates/deletions, expired tool results, and tool error/retry fixtures. Acceptance: a suite reports task completion, evidence use, instruction adherence, memory accuracy, abstention, and configured attack success by case and slice. Tools use deterministic fixtures or bounded authorized execution.

**CTX04 Diagnosis and promotion.** Link token allocation and block diffs to answers, tool actions, citations, and failures; support replay and a versioned release gate for a context recipe independently or with a model/RAG pipeline. Acceptance: a reviewer can compare retrieved versus supplied evidence, run gold-context and context-removal diagnostics, inspect failures, and restore a prior qualified recipe. Reports distinguish observed correlations from causal claims and document stochastic replay limits.

## 7 Formats and compatibility

The format registry must show separate statuses for storage, parsing, preview, annotation, training conversion, and export. Status values are supported, experimental, requires extension, and unsupported. A capability is supported only when it passes a fixture suite under a named adapter version.

### 7 1 Proposed format coverage

| Family | Initial import targets | Representation and annotation | Training condition |
| --- | --- | --- | --- |
| Text and chat | TXT, MD, JSON, JSONL | Text blocks, messages, labels, preferences | Validated tokenizer and input template |
| Tables and datasets | CSV, TSV, Parquet, Arrow | Typed records and field mappings | Mapping to a supported sample schema |
| Documents and web | HTML, PDF, DOCX, PPTX, EPUB, WARC | Source assets, extracted text, pages and links | Extracted text or compatible visual processor |
| Code | Source files, Git snapshots, notebooks, diffs | Files, repositories, patches, execution records | Supported text or tool-use recipe |
| Vector graphics | SVG | Source XML, rendered preview, shapes and paired descriptions | Validated text-to-SVG or image-to-SVG recipe |
| Images | JPEG, PNG, WebP, TIFF | Images, captions, boxes, polygons and masks | Compatible image encoder and processor |
| Audio | WAV, FLAC, MP3, Ogg | Audio assets, segments, transcripts and speakers | Compatible audio recipe and sample-rate handling |
| Video | MP4, MOV, WebM | Frames, clips, subtitles and synchronized audio | Compatible temporal processor and training recipe |
| Custom and scientific | Custom JSON, binary, time series, sensor records | Opaque assets or extension-defined types | Validated conversion or custom model adapter |

Exact codecs, document features, size limits, and annotation tools require a published support matrix. Unsupported embedded content must produce a visible extraction report. Unknown binary files can be retained without implying they are safe to execute or meaningful model inputs.

### 7 2 Extension contract

An extension manifest must declare its identity, version, compatible platform API, capabilities, schemas, dependencies, resource needs, and permissions. Readers detect and decode input; validators return structured errors; converters produce normalized samples; viewers and annotators render permitted content; training adapters prepare model inputs; evaluators score outputs; exporters write declared formats.

Extensions need only implement the capabilities they provide. A reader-only extension does not automatically receive training support. The SDK must include fixtures, compatibility tests, a local development workflow, and packaging instructions. Schema migrations must preserve existing run references.

## 8 Shared data and architecture requirements

### 8 1 Artifact and sample model

The core entities are source, asset, sample, dataset version, annotation, recipe, run, checkpoint, model version, evaluation suite, evaluation result, release, worker pool, usage record, knowledge-base version, chunk, embedding set, index version, retrieval pipeline, query trace, relevance judgment, projection, context recipe, context block, session/memory snapshot, labeling campaign, annotation batch, draft prediction, review revision, cycle, and labeling-model assignment. Each entity must have an organization owner, stable identifier, access scope, revision information, and applicable lineage links.

A sample contains ordered content blocks, conversation roles, asset references, annotations, relationships, and metadata. Spatial coordinates must specify their coordinate system; temporal annotations must specify units and time base. Raw assets remain in artifact storage, while large datasets use partitioned manifests and shards. The platform database stores metadata and references rather than every media byte or corpus token.

Committed artifacts must be immutable and checksummed. Lifecycle rules can archive or delete artifacts with dependency checks and an audit trail. Deleting source data does not retroactively remove its influence from trained weights; affected model lineage must remain discoverable for retention and release decisions.

### 8 2 Service boundaries

The workspace and APIs form the user-facing layer. Platform services manage identity, projects, manifests, workflows, queues, evaluations, and accounting. Separate CPU and GPU workers execute data processing, generation, training, inference, and scoring. Credentials and storage authorization must be scoped to the job.

Workflow state must survive service restarts. Data processing should support streaming, partitioned execution, retries, and committed-output checks. Training backends must declare architecture support, distributed topology, checkpoint format, input schemas, and export capabilities. Job submission must validate that the selected worker pool can satisfy those declarations.

### 8 3 Deployment and portability

Managed cloud owns hosted operations and can offer selected compute integrations. Self-hosted installations include the core services, installation guidance, migrations, backup and restore procedures, and offline dependency provisioning. Hybrid mode defines metadata residency as well as artifact residency; keeping checkpoints local does not by itself keep logs or examples local.

Project export bundles must contain manifests, recipes, schemas, evaluation definitions, and authorized artifacts. Secrets must be excluded. Import reports must identify missing artifacts, incompatible versions, unavailable backends, and restricted dependencies before execution. Metering is part of the core product; hosted billing and subscriptions are separate services.

### 8 4 Build and integration approach

We should own the product workflows, common records, compatibility registry, permissions, and release evidence. Existing engines are candidates for data processing, annotation, training, evaluation, and serving. Candidate selection must consider functionality, license compatibility, maintainability, security, hardware fit, and tested version combinations. Section 8 6 records the application stack baseline, while Section 8 5 defines the job protocol. Training engines remain candidates to qualify against the references in Section 15.


### 8 5 Job dispatch and broker recommendation

**Recommendation for R1:** use RabbitMQ for dispatching short work notifications to capacity-aware workers. Use PostgreSQL as the authoritative transactional job and attempt store; use artifact storage for datasets, logs, and checkpoints. Kafka remains an optional later integration for retained, replayable event streams when several independent consumers or measured throughput justify it. This is the planning baseline, pending implementation qualification.

RabbitMQ provides manual acknowledgements, publisher confirms, and prefetch limits suitable for competing workers. Kafka supports retained streams and independent consumer groups; its Share Groups also provide queue-style consumption and became production-ready in 4.2. Kafka can meet the queue requirement. We recommend RabbitMQ because dispatch, routing, and bounded in-flight work are the immediate needs, while long-term replay is not yet a required broker feature. Neither broker schedules GPU resources or guarantees exactly-once training. See the official references in Section 15.

The proposed flow is API to durable job record and transactional outbox, then RabbitMQ, then a compatible worker or worker-pool gateway. The scheduler applies organization authorization, quotas, fair allocation, budget policy, and available hardware before dispatch. Workers request or enable delivery only while they have free slots. RabbitMQ subscriptions can push messages; consumer credit and application admission implement the user's requirement that workers take jobs when ready. Avoid continuous empty polling and do not preassign large batches to busy GPU workers.

Use durable quorum queues for production dispatch, persistent messages, publisher confirms, and an outbox publisher that safely retries. A single broker is acceptable only for development without a high-availability claim; the production reference deployment should qualify a three-node cluster across appropriate failure domains. Separate CPU preparation, GPU training, evaluation, and acquisition pools where useful, with controlled routing by compatible capabilities. Queue routing must not replace database authorization or tenant fairness. Keep messages small: job ID, attempt/routing metadata, schema version, and trace ID; no corpus bytes, checkpoints, or embedded secrets.

On receipt, a worker atomically claims the eligible job attempt in the database and reserves its execution slot. It acknowledges the dispatch message only after that claim is durable, then executes under a renewable application lease with periodic heartbeats. A long training run must not hold a RabbitMQ delivery unacknowledged for its whole duration. A recovery reconciler detects abandoned claims, checks attempt and checkpoint state, and schedules a bounded recovery attempt through the outbox. Completion commits checked artifacts and final state before dependent jobs become eligible.

Delivery is at least once. Stable job IDs, conditional attempt claims, fencing tokens, and immutable output commits must make duplicates harmless. Expired or superseded attempts cannot renew their lease or publish final results. Recovery must revoke the old allocation or obtain execution-backend evidence that it stopped before starting a new chargeable training attempt; if that cannot be established, mark the job interrupted and require operator resolution. A message acknowledgement means dispatch was recorded, not that the model finished training.

Retries distinguish transient failures from invalid input, missing permission, and incompatible hardware. Use bounded exponential backoff with jitter and a recorded retry schedule; quarantine poison dispatches for inspection instead of creating a requeue loop. Cancellation is durable desired state checked by workers and the execution backend; report actual stop and checkpoint status. Draining workers stop accepting jobs and finish or checkpoint according to policy. Track queue age, ready jobs, dispatch latency, unacknowledged notifications, available slots, lease age, retries, failed attempts, and starvation by team.

For multi-node training, reserve the complete resource group and launch it through a qualified Kubernetes, Slurm, or other execution adapter; individual workers must not independently claim fragments of a distributed run. Hybrid workers can use an outbound authenticated gateway/long-poll protocol that bridges dispatch and lease operations under organization policy, without requiring customer machines to expose broker endpoints publicly. Broker choice does not change residency, offline provisioning, or egress requirements.

### 8 6 Technology stack

Use a Django application organized into domain modules, with separate worker runtimes for acquisition, data preparation, training, and evaluation. The browser and native Mac clients share a versioned API. The following choices establish the planning baseline; exact versions and support claims require qualification. Architecture decision 002 records the detailed contracts and alternatives.

| Layer | Choice | Responsibility |
| --- | --- | --- |
| Browser | React and TypeScript with Vite | Main workspace and annotation tools; build static assets for production |
| Mac application | SwiftUI | Native client of the same API, with local file selection, transfers, and job monitoring |
| Application API | Python, Django, Django REST framework, ASGI | Permissions, projects, datasets, recipes, jobs, evaluations, and releases |
| Metadata database | PostgreSQL | Tenant records, lineage, job attempts, leases, budgets, and transactional outbox |
| Retrieval baseline | PostgreSQL full-text search and pgvector to qualify | Lexical, vector, and hybrid retrieval with explicit access filters |
| Artifact storage | S3-compatible interface | Original assets, dataset shards, model weights, checkpoints, and log archives |
| Storage providers | SeaweedFS to qualify for self-hosting; managed S3 for cloud | Provider-specific deployment behind the common storage contract |
| Dispatch | RabbitMQ | Short capacity-aware work notifications under Section 8 5 |
| Collection | Scrapling in isolated Python workers | HTTP and browser acquisition through a versioned source adapter |
| Execution | Separate CPU and GPU worker containers | Run qualified processing and training backends with explicit resources |
| Deployment | Docker Compose; Kubernetes and Helm for multi-node production | Development and single-server packages, plus a production cluster reference |

Prefer Django 5.2 LTS as the initial API qualification target; select a compatible Python and REST framework release and pin their patch versions. Worker images have independent dependency locks for their engines. The API process must not run scraping or training inline. Publish an OpenAPI contract and compatible client models. Use polling initially for job state and add authenticated server-sent events where useful; durable job state remains authoritative after reconnection. Define Mac feature coverage explicitly before committing to parity with the browser.

PostgreSQL stores metadata and artifact references. Large corpora and checkpoint bytes belong in object storage. Authorize transfers through Django, then use short-lived, scoped upload/download access where the provider supports it. Verify hashes before committing artifact manifests. S3 compatibility must be tested for multipart resume, range reads, authorization, retries, and incomplete transfers. The user-selected direction is SeaweedFS qualification and managed S3; the cloud vendor remains open. MinIO community is not the default for new installations because its repository is archived and marked unmaintained. Existing MinIO endpoints may be supported only after the same compatibility checks.

### 8 7 Collection integration

Select Scrapling as the first web acquisition engine to qualify, behind the source connector interface. Use HTTP fetching by default and browser fetching only for sources that need it. Persist source URLs, fetch metadata, raw content, extraction configuration, and checkpoint artifacts. Crawl checkpoints must survive worker replacement, and output commits must deduplicate replayed work. The platform owns source permissions, domain policy, crawl budgets, provenance, and dataset eligibility. Public accessibility alone does not establish an open dataset license.

Enable robots rules and bounded per-domain concurrency in the shipped recipe; Scrapling documents robots compliance as disabled by default. Validate cancellation, restart, throttling, selector changes, and tenant isolation with controlled fixtures. Keep browser dependencies in the acquisition image. Git, dataset repositories, APIs, and object-storage sources use their own connectors rather than being forced through the web crawler.

### 8 8 Deployment and operational baseline

Provide Docker images and a Compose package for development and a documented single-server installation. Compose alone does not establish multi-host scheduling or high availability. Recommend Kubernetes with Helm for the multi-node production reference; Docker Swarm remains an alternative to evaluate if an operating requirement warrants another deployment adapter. GPU execution must reserve complete resource groups under Section 8 5. Qualify persistent storage, database recovery, broker replication, and node-failure behavior separately from application replicas. Managed database and object-storage services can sit outside the application cluster.

The Mac application runs natively and connects to the selected installation. Local GPU execution is a separate backend capability, not implied by a SwiftUI client. Keep the deployment initially limited to the API, outbox publisher, recovery scheduler, worker pools, PostgreSQL, RabbitMQ, artifact storage, and the web-serving ingress. Add caches, search engines, or stream infrastructure when a measured requirement justifies them. Centralize structured logs, metrics, and trace correlation across requests and job attempts.

Stack evidence reviewed on 8 October 2026: [Vite](https://vite.dev/guide/), [React](https://react.dev/learn/build-a-react-app-from-scratch), [SwiftUI](https://developer.apple.com/documentation/swiftui), [Django support](https://www.djangoproject.com/download/), [Django REST framework](https://www.django-rest-framework.org/), [PostgreSQL support](https://www.postgresql.org/support/versioning/), [Scrapling](https://scrapling.readthedocs.io/en/latest/index.html), [Scrapling crawl settings](https://scrapling.readthedocs.io/en/latest/spiders/advanced.html), [SeaweedFS](https://github.com/seaweedfs/seaweedfs), [MinIO repository status](https://github.com/minio/minio), [Docker Compose deployment](https://docs.docker.com/compose/how-tos/production/), [Kubernetes GPU scheduling](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/), and [Helm charts](https://helm.sh/docs/topics/charts/). These sources establish component capabilities; they do not establish a tested ModelAnvil integration.

### 8 9 RAG and context architecture

Qualify PostgreSQL full-text search and pgvector as the first retrieval backend, reusing S3 artifacts and RabbitMQ worker execution. Record embedding dimensions, normalization, distance, and query/document encoding; separate incompatible embedding spaces. Qualify exact search as a reference and approximate search under real tenant and metadata filters. Approximate-index recall against exact neighbors is a separate operational measure from relevance Recall@K. Compare latency and result completeness under filters before choosing an index topology. Large retrieval workloads may need a separate PostgreSQL deployment or another backend without changing the pipeline contract.

LlamaIndex is a candidate orchestration adapter, Sentence Transformers a candidate embedding/reranking integration, ir-measures a candidate for deterministic retrieval metrics, and Ragas a candidate for answer and context judges. ModelAnvil owns permissions, stable IDs, workflow state, and experiment records. Qualify a local model path for self-hosted retrieval, generation, and judging; remote providers require explicit egress permission. Pin each model's license and revision separately from the library license.

Run extraction, embedding, index builds, evaluation, projection, and clustering in worker jobs. Query serving uses a separately sized execution service with timeouts and concurrency limits; interactive queries must not wait behind training jobs or load model weights in Django requests. Version a release manifest linking corpus/index, retriever, reranker, generator, context recipe, and evaluation evidence. Authorization overlays and deletion tombstones apply to all versions and caches independently of immutable content history.

Use UMAP for the first 2D visualization candidate and PCA as a comparison baseline. Qualify HDBSCAN or K-means for optional cluster labels in the original embedding space or a declared higher-dimensional reduction. Do not silently cluster the 2D display. Record the clustering space, distance, settings, seed where applicable, dependency versions, and saved coordinates. Qualify a browser WebGL renderer such as Plotly scattergl against a bounded point-count profile; larger sets use declared sampling or server aggregation. A Mac explorer can follow its feature matrix while using the same projection artifacts and permissions.

Context assembly is an explicit stage shared by direct model experiments, RAG, and bounded tool workflows. Preserve block lineage before and after trimming/compression, the exact supplied input, tokenizer/template, output reserve, and any provider-reported token counts. Memory is scoped to organization, project, principal, and session as applicable; tests cannot share mutable memory accidentally. Frozen replay uses stored tool results and memory snapshots, while live tests are labeled separately. Traces have configurable retention, redaction, and access, since inputs may contain private source data.

## 9 Interface requirements

Navigation will include Overview, Data, Annotation, Models, Training, Evaluation, RAG, Context Lab, Releases, and Infrastructure. Data includes a searchable Dataset Bank with output/task filters, license obligations, sample previews, access conditions, size, and separate download and training readiness. Infrastructure shows worker capability, available slots, queue age, and draining status. Project pages must show their organization and active project context. Every long job needs progress, current state, logs, ownership, usage, and available recovery actions.

Guided workflows should expose recommended recipes with explanations and editable assumptions. Advanced users can inspect and export the full configuration. The UI and CLI must operate on the same records and validation rules. Users must never need to recreate a UI experiment manually to automate it.

Dataset previews must preserve source links and display filtering reasons. Model comparisons must show baseline, protocol, slices, and sample counts beside scores. Annotation screens must support keyboard operation, media controls where applicable, and unbiased candidate presentation. Training launch must make hardware eligibility, estimated usage, output location, and budget policy visible before submission.

RAG includes knowledge-base builds, pipeline editing, query inspection, metric comparison, and the cluster explorer. Context Lab includes a block composer, ordered message preview, token-allocation bars, side-by-side block diffs, experiment comparison, and an evidence-position versus length heatmap. Link cluster selections to failure tables and review batches. Display sampling and projection settings beside the plot. Provide quality-versus-cost and quality-versus-latency comparisons with raw examples; do not compress every outcome into a single unexplained score.

Annotation includes a campaign setup flow with manual or model-assisted starting modes, batch queue, draft-versus-correction view, review/adjudication states, and a cycle timeline. The timeline shows approved data counts, drafting model per batch, training/qualification results, next-batch selection, limits, and pause/rollback controls. Users can hide predictions for independent audit work. Invalid drafts remain visible as failed predictions and can be labeled manually. Show accepted-without-edit and corrected counts separately.

## 10 Reliability and qualification targets

The following numbers are proposed engineering targets for qualification, not approved commercial service commitments. The benchmark configuration must record hardware, dataset shape, organization count, workload mix, and software versions. Larger deployments require additional published qualification profiles.

| Measure | Proposed R1 target | Verification |
| --- | --- | --- |
| Team concurrency | 10 organizations, 50 teams, 100 active sessions | Mixed-workload load test with isolated resources |
| Job concurrency | 10 running GPU jobs and 20 data jobs on adequately provisioned pools | Queuing, fairness and resource-release test |
| Distributed training | At least one tested 2-node configuration | Scratch training and worker-interruption recovery |
| Dataset qualification | A 1 TB source corpus and a 1 million-record manifest | Streaming preparation and paginated inspection |
| Interactive API latency | p95 below 2 seconds for defined metadata operations | Measured under the qualification load; transfers excluded |
| Dispatch latency | p95 below 60 seconds when full eligible capacity is available | Submission-to-worker-start measurement; image pulls reported separately |
| Hosted control-plane availability | 99.5 percent monthly target | Availability definition and monitoring agreed before launch |
| Metadata recovery | RPO at most 15 minutes and RTO at most 4 hours | Backup and restore drill; artifact recovery tested separately |

Additional release requirements are zero successful unauthorized cross-organization accesses in the defined test suite; checksum verification for committed artifacts; restoration of a documented self-hosted backup; and keyboard access to core workflows. Training checkpoints must record backend-dependent recovery guarantees. Bitwise-identical reruns across hardware are not required; seeds, environment, and known nondeterminism must be documented.

RAG qualification must publish corpus and embedding size, concurrent queries, language mix, filter selectivity, point count for visualization, index build time, and stage/end-to-end p50/p95 query latency. Retrieval and generation targets must be set per recipe and hardware; metadata API targets do not imply generated-answer latency. Context qualification records tested lengths and useful task performance rather than equating advertised context capacity with effective evidence use.

## 11 Product success measurement

The primary outcome is the number of active teams completing a reproducible, evaluated model or RAG/context release. A completed release must have loadable model artifacts or an executable pipeline/recipe, provenance, and its required evaluation results. Counts of training launches alone do not establish value.

During pilot operation, collect time to first completed scratch run, time to first evaluated fine-tune, weekly active teams, completed release rate, infrastructure-caused job failure rate, successful recovery rate, annotation agreement, and attributable compute usage. Record manual setup time and workflow handoffs against each pilot team's previous process.

Model improvement is project-specific. Report intended-task gains, regressions, uncertainty, latency, memory, and cost under comparable protocols. Numerical adoption and productivity targets should be set after the pilot establishes a baseline. Product telemetry must respect installation and egress settings; self-hosted telemetry is configurable.

## 12 Release acceptance scenarios

Each scenario must produce a stored test report linked to the applicable requirement IDs. A release requires all R1 scenarios to pass on the declared compatibility matrix. Target features receive separate reports and must not be labeled supported without them.

1. **Scratch model journey.** Import and clean a corpus, train a tokenizer, create splits, run pretraining from random initialization, evaluate, export, and load the model outside the platform. Covers DAT01-DAT06, TRN01-TRN03, EVA01, and REL01.
2. **Fine-tuning journey.** Register an exact base revision, run its baseline, train both a full-weight reference recipe and a supported adapter recipe, compare results, and load their exports. Covers PRJ02, TRN04-TRN05, EVA02, and REL01.
3. **Preference and reward journey.** Generate blinded candidates, collect human preferences, adjudicate a disagreement, train DPO and a reward model, and report held-out results. Covers ANN01-ANN03, SYN01, and ALN01-ALN02.
4. **Verifiable RL journey.** Run the supported verifier-based recipe in a bounded environment, record trajectories, and evaluate independently of the reward. Covers ALN03-ALN04 and EXT02.
5. **Data diversity journey.** Import fixtures from every format labeled supported, inspect extraction errors, preserve asset relationships, and perform applicable annotations. Demonstrate a mixed-media sample. Covers DAT03, ANN01, and Section 7.
6. **Custom format journey.** Map a custom record without code, then install a sample reader and training-conversion extension. Reject malformed inputs and train through a compatible backend. Covers EXT01-EXT02.
7. **Isolation and quotas.** Run two organizations concurrently; attempt unauthorized reads through UI, API, artifact URLs, logs, search, and worker credentials; exhaust one team's quota without blocking the other's allocation. Covers OPS01-OPS03.
8. **Failure and recovery.** Interrupt a distributed worker and restart platform services. Resume verified work, avoid duplicate committed outputs, and confirm cancellation releases resources. Covers PRJ03, TRN06, and OPS04.
9. **Deployment and portability.** Complete scratch and fine-tuning reference journeys in managed and self-hosted modes. Run a hybrid job under restrictive egress policy and transfer an authorized project without secrets. Covers OPS05-OPS06 and Section 8.
10. **Release and rollback.** Enforce a failing evaluation criterion, record a permitted exception, export a complete candidate, evaluate a supported quantization, promote an endpoint, and restore its previous version. Covers EVA04 and REL01-REL02.


11. **Open dataset preset journey.** Search SVG, preview a bounded starter preset, download to authorized storage, interrupt and resume the transfer, prepare image/SVG pairs, deduplicate and group variants, and export license and lineage manifests. Block unclear-license sources and unauthorized cache reads. A new upstream revision creates a distinct dataset version. Covers BANK01-BANK07, DAT01, DAT04-DAT06, and OPS01.
12. **Capacity and broker recovery.** Saturate a worker, show that it takes no extra job, then free a slot and dispatch compatible work. Inject duplicate messages, broker restart, lost heartbeats, and a stale attempt. Verify durable job recovery, no duplicate authorized GPU allocation, fencing of stale output, bounded retry/quarantine behavior, and full-group reservation for distributed training. Covers OPS02, OPS04, OPS07, and TRN06.


13. **Complete RLHF journey.** Collect and adjudicate human preferences, train and validate a reward model, then optimize a text policy using fresh rollouts and that learned reward with a named qualified algorithm. Inspect raw reward, penalties, divergence, and resource use; interrupt and recover under documented checkpoint guarantees; compare against the starting policy using held-out human judgments and regression tests. Inject a reward-hacking fixture and a configured stop-limit breach, and verify that reward improvement alone cannot promote a release. Covers ANN01-ANN03, ALN02, ALN04-ALN05, EVA01-EVA04, OPS03-OPS04, OPS07, and TRN06.

14. **RAG implementation and evaluation.** Import a fixture corpus, build lexical/dense/hybrid pipelines with reranking, compare hand-scored relevance metrics and answer checks, expose an authenticated query endpoint, and export a release manifest. Change a document, revoke another document's access, and delete evidence; verify freshness, suppressed access in every trace/cache, index recovery, and safe rollback. Covers RAG01-RAG06, RAG08, OPS01, and EVA01-EVA04.
15. **Cluster investigation.** Save a projection and cluster assignment, filter and select chunks, overlay a query's retrieved/relevant results, and open linked source locations and failure cases. Reopen the same artifact without recomputing coordinates, inspect embedding-space neighbors, and verify sample disclosure, table access, and tenant isolation. Covers RAG07-RAG08.
16. **Context engineering comparison.** Compare full history, windowed history, and summarized history on a frozen multi-turn suite. Sweep evidence position and input budget, inspect exact inputs and retained evidence, inject an instruction attack and stale memory/tool-result fixture, and verify session isolation and context-limit validation. Record repeated-run uncertainty and quality/cost tradeoffs, enforce a failing gate, export the recipe, and restore its previous version. Covers CTX01-CTX04, RAG03, and OPS01-OPS04.

17. **Iterative labeling journey.** Run one campaign from a manual seed and another from existing-model drafts on a qualified text-labeling fixture. Review/correct the seed, train and qualify a labeling model, draft and review the next batch, and repeat the train-and-next-batch cycle once more. Verify accumulated approved-data snapshots, protected split exclusion, original predictions and reviewer lineage, unchanged in-flight model assignments, failed-candidate handling, rollback, pause/resume, duplicate-job recovery, and configured stop limits. Covers ANN01-ANN07, DAT05-DAT06, TRN04-TRN06, EVA01-EVA03, and OPS01-OPS04.

## 13 Delivery plan and dependencies

### 13 1 Foundation and feasibility

Define the sample schema, artifact lineage, organization boundary, backend contracts, support matrix, and worker protocol. Qualify RabbitMQ dispatch with database leases/outbox and the first SVG bank connector, including interrupted-download recovery and license snapshots. Pilot scratch training, fine-tuning, distributed recovery, custom-format conversion, and a candidate multimodal recipe. Qualify a small RAG corpus, retrieval metrics fixture, context assembly trace, and projection prototype. Exit when the highest-risk compatibility assumptions have measured evidence.

### 13 2 Both training journeys

Implement versioned ingestion and preparation, tokenizer workbench, model registration, preflight, job execution, monitoring, evaluation, and export. Establish managed and self-hosted packaging together. Exit when scratch and fine-tuning journeys complete using shared records.

### 13 3 Data collaboration and alignment

Add controlled collection, annotation quality workflows, synthetic generation, preference optimization, reward training, complete learned-reward RLHF, verifier-based RL, and failure selection. Add the iterative labeling campaign, approved-data snapshots, labeling-model qualification, next-batch prediction, and cycle dashboard. Integrate core format adapters and the public SDK. Exit when preference, reward, complete RLHF, verifier-based RL, custom-format, and iterative-labeling scenarios pass, including scenario 17.

### 13 4 RAG and context workbenches

Build knowledge-base/index versioning, retrieval and answer pipelines, relevance labeling, query traces, and an authenticated serving adapter. Add the embedding explorer and linked failure review. Implement context composition, frozen multi-turn replay, ablations, stress suites, metric comparison, and recipe release gates. Exit when scenarios 14-16 pass on the declared text recipe with local self-hosted models and judges.

### 13 5 Multi-team qualification and release

Complete quotas, accounting, hybrid egress enforcement, identity integration, backups, upgrades, serving, and rollback. Execute load, isolation, and recovery tests and publish installation and support documentation. Exit when all R1 scenarios pass with named backend versions and hardware configurations.

These milestones require GPU access, representative datasets, annotators, identity and storage integrations, and pilot organizations. Named owners, staffing, dates, and cost estimates must be assigned after feasibility and capacity choices. Milestones describe dependencies rather than a promised calendar.

## 14 Risks and decisions

### 14 1 Principal risks

| Risk | Consequence | Required response |
| --- | --- | --- |
| Format breadth exceeds tested coverage | Users import data that cannot reach training | Publish capability levels and test adapter fixtures |
| Backend version incompatibility | Runs fail or exports cannot load | Pin validated combinations and run integration tests |
| Training cost or scale exceeds estimates | Budget overrun or poor utilization | Pilot workloads, expose assumptions, enforce limits |
| Labeling loop reinforces draft errors | Repeated approval hides systematic labeling mistakes | Independent human audit, rubric/version control, diverse review, held-out gates, and rollback |
| Evaluation leakage or weak rewards | Apparent improvement does not generalize | Split checks, held-out tests, independent evaluations |
| Shared infrastructure leaks data or starves teams | Loss of trust and service reliability | Isolation tests, scoped credentials, quotas and scheduling |
| Self-hosted deployments diverge | Upgrades and support become unreliable | Versioned packages, migration tests and support policy |
| Stale or unauthorized retrieval | Answers expose revoked content or outdated evidence | Query-time authorization, deletion overlays, cache invalidation, freshness and rollback tests |
| Weak context tests or misleading projections | Attractive plots or easy synthetic tasks hide failures | Labeled evidence, real task suites, position/length tests, human calibration, saved projection metadata |
| Source or base-model restrictions are lost | Inappropriate data use or distribution | Preserve metadata and enforce organization release rules |

### 14 2 Decisions needed before implementation commitment

- **Capacity:** largest model, GPU types, node counts, interconnect, dataset volume, and concurrent workload to qualify.
- **Model coverage:** initial scratch architecture and exact image, audio, and video training recipes; identify which remain experimental.
- **Infrastructure:** initial compute provider, storage interfaces, scheduler adapters, offline installation requirements, and supported operating environments.
- **Commercial model:** platform license, community versus paid capabilities, support obligations, and hosted billing approach.
- **Identity and residency:** required SSO standards, regions, data retention, hybrid metadata location, and audit requirements.
- **RAG and context:** corpus scale, local embedding/reranker/generator/judge revisions, supported languages, retrieval topology, visualization limits, and memory/tool integration scope.
- **Labeling loop:** initial task/schema, trainer and drafting-model combinations, independent audit size, review roles, quality gates, batch/cycle limits, and automatic-progression policy.
- **Evaluation:** pilot tasks and languages, protected capabilities, release thresholds, and human-review capacity.
- **Extension governance:** installation authority, package distribution, review expectations, and supported API lifetime.
- **Execution:** product owner, technical owners, staffing, feasibility budget, delivery milestones, and success targets.

The recommended immediate planning task is a feasibility matrix connecting data types, annotation tools, architectures, training methods, hardware, and evaluation suites. Its results should settle the R1 support matrix before a delivery estimate is approved.

## 15 Terms and technical references

### 15 1 Terms

**Open weight:** model parameters are available under stated distribution and use terms. This does not imply that all training data, source code, or rights are unrestricted.

**Pretraining:** learning from a broad or domain corpus, starting from random initialization for a scratch run. Continued pretraining starts from existing weights.

**SFT:** supervised fine-tuning using examples of desired outputs. **LoRA:** training low-rank adapters instead of all model parameters. **QLoRA:** an adapter-training approach using a quantized base model in supported configurations.

**DPO:** direct preference optimization using preferred and rejected responses. **Reward model:** a trained model that scores outputs. **Verifiable reward:** a task check such as a correctness test or test-suite result. **RL:** reinforcement learning using a specified reward and training recipe. **RLHF:** reinforcement learning from human feedback; the required learned-reward path connects human preferences to a trained reward model and policy optimization. **PPO:** proximal policy optimization. **RLOO:** REINFORCE leave-one-out. DPO uses preferences directly without requiring a separate learned reward model or the same rollout-based RL loop.

**RPO:** the maximum targeted metadata loss interval after an incident. **RTO:** the targeted time to restore service. **p95:** a threshold met by 95 percent of measured requests or events.

**RAG:** retrieval-augmented generation; retrieve source evidence and supply it to a generator at query time. **Context recipe:** versioned rules for assembling the actual model input, including instructions, examples, evidence, history, memory, and tool information. **Relevance judgments or qrels:** labeled relationships between queries and evidence units used to evaluate retrieval.

**Iterative model-assisted labeling:** repeated model drafts, human review/correction, and training of a new labeling-model version for subsequent batches. **Active learning:** selecting examples for labeling using a declared acquisition strategy; advanced automated strategies are separate from the R1 batching loop. A labeling model proposes annotations and need not be the final product model or reward model.

### 15 2 Candidate integration references

Official project documentation reviewed on 8 October 2026. These references support integration discovery; product requirements and coverage targets above are proposed platform behavior.

- [Label Studio ML integration](https://labelstud.io/guide/ml.html) and [prediction import](https://labelstud.io/guide/predictions.html) are candidates for prediction/review adapters. Verify edition-specific capabilities and task schemas; ModelAnvil must own the campaign lifecycle and cannot assume an automated loop is included in a community labeling frontend.
- [DataTrove](https://github.com/huggingface/datatrove) provides text extraction, filtering, deduplication, and processing pipelines. Candidate for the data layer.
- [Hugging Face TRL](https://huggingface.co/docs/trl/index) provides supervised, preference, reward-model, and reinforcement-learning training components. Candidate for post-training adapters.
- [TRL reward modeling](https://huggingface.co/docs/trl/reward_trainer), [RLOO](https://huggingface.co/docs/trl/rloo_trainer), and [PPO on the main documentation branch](https://huggingface.co/docs/trl/main/en/ppo_trainer) are algorithm/backend references for RLHF feasibility. Documentation availability does not establish a stable integration; qualify and pin the selected release and API.
- [Megatron LM](https://github.com/NVIDIA/Megatron-LM) provides tooling for training transformer models at scale. Candidate for distributed pretraining.
- [Language Model Evaluation Harness](https://github.com/EleutherAI/lm-evaluation-harness) provides language-model evaluation infrastructure. Candidate for benchmark integration alongside custom evaluations.

- [RabbitMQ acknowledgements and confirms](https://www.rabbitmq.com/docs/confirms), [consumer prefetch](https://www.rabbitmq.com/docs/consumer-prefetch), and [quorum queues](https://www.rabbitmq.com/docs/quorum-queues) explain broker delivery controls and replication. They do not provide application job leases or GPU scheduling.
- [Apache Kafka design](https://kafka.apache.org/41/design/design/) describes retained-log and consumer-group concepts; the [Kafka 4.2 release announcement](https://kafka.apache.org/blog/2026/01/14/apache-kafka-4.2.0-release-announcement/) establishes production-ready Share Groups with queue-style consumption. Check the exact selected version and client support during qualification.

## 16 Open dataset presets by intended output

### 16 1 Catalog policy and readiness

This catalog contains 33 publisher-declared open source candidates: 23 initially reviewed on 8 October 2026 and ten added on 11 October 2026. The [source bank](open-dataset-bank.md) records preparation and split requirements for the expansion. Open here means the declared content license permits reuse, modification, and redistribution, including commercial use, subject to its obligations. Noncommercial-only, no-derivatives, research-only, and unclear asset licensing are excluded. Attribution must be preserved. Share-alike sources remain open but require an explicit project policy choice. License obligations for adapted data and released weights require scope-specific assessment; the platform must not invent a universal rule.

Each source below links to its publisher and license evidence. Candidate status records the inspected declaration, not a rights guarantee for every future revision or a qualified connector. Before enabling download, pin the revision or archive hash, inspect selected-asset exceptions, archive notices, measure sizes, validate a sample, and publish the connector's qualification report. Source code licensing alone is insufficient evidence for separately gathered data. Gated access is displayed separately from content licensing and cannot be accepted silently.

The categories describe intended model outputs. Upstream JSONL, Parquet, NPZ, or ZIP describes packaging and does not determine what a model learns to generate. A compatible model, task construction, and qualified training/export recipe remain prerequisites. File conversions such as PNG to WebP or WAV to FLAC do not require a new semantic corpus, but their converters need tests. The source catalog is a starter bank for experiments, not a complete foundation-pretraining corpus.

### 16 2 SVG vector graphics

Output formats: svg.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [Lucide](https://github.com/lucide-icons/lucide) | [ISC AND MIT](https://github.com/lucide-icons/lucide/blob/main/LICENSE) | Outline icons with consistent geometry and semantic filenames. |
| [Tabler Icons](https://github.com/tabler/tabler-icons) | [MIT](https://github.com/tabler/tabler-icons/blob/main/LICENSE) | Outline and filled UI icon variants. |
| [Heroicons](https://github.com/tailwindlabs/heroicons) | [MIT](https://github.com/tailwindlabs/heroicons/blob/master/LICENSE) | UI icons in several sizes and styles. |
| [Bootstrap Icons](https://github.com/twbs/icons) | [MIT](https://github.com/twbs/icons/blob/main/LICENSE) | UI icons with outline and filled shapes. |
| [Phosphor Icons](https://github.com/phosphor-icons/core) | [MIT](https://github.com/phosphor-icons/core/blob/main/LICENSE) | Icons spanning multiple stroke weights and styles. |
| [Feather Icons](https://github.com/feathericons/feather) | [MIT](https://github.com/feathericons/feather/blob/main/LICENSE) | A compact outline-icon collection suitable for initial experiments. |
| [Material Design Icons](https://github.com/google/material-design-icons) | [Apache-2.0](https://github.com/google/material-design-icons/blob/master/LICENSE) | SVG assets from the Material icon family. |
| [Twemoji graphics](https://github.com/jdecked/twemoji) | [CC-BY-4.0](https://github.com/jdecked/twemoji/blob/main/LICENSE-GRAPHICS) | Colored emoji SVG artwork indexed by Unicode sequences. |
| [OpenMoji](https://github.com/hfg-gmuend/openmoji) | [CC-BY-SA-4.0](https://github.com/hfg-gmuend/openmoji/blob/master/LICENSE.txt) | Colored and monochrome emoji with accompanying metadata. |
| [Game Icons](https://github.com/game-icons/icons) | [CC-BY-3.0](https://github.com/game-icons/icons/blob/master/license.txt) | Game-related silhouettes and symbolic artwork organized by contributor. |

These sources supply icons and emoji, not verified natural-language/SVG instruction pairs. Render source SVG into paired images in isolation; available names and tags are weak labels. Review generated descriptions and retain their origin. Deduplicate across collections and keep semantic, size, style, and color variants in one split. Complex diagrams, long illustrations, animation, fonts, and chart editing require additional data.

### 16 3 Prose chat and reasoning

Output formats: txt, md, jsonl.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [OpenAssistant OASST1](https://huggingface.co/datasets/OpenAssistant/oasst1) | [Apache-2.0](https://huggingface.co/datasets/OpenAssistant/oasst1) | Human conversation trees and ranking signals for supervised and preference training. |
| [Databricks Dolly 15k](https://huggingface.co/datasets/databricks/databricks-dolly-15k) | [CC-BY-SA-3.0](https://huggingface.co/datasets/databricks/databricks-dolly-15k) | Instruction following, question answering, and summarization examples. |
| [GSM8K](https://huggingface.co/datasets/openai/gsm8k) | [MIT](https://huggingface.co/datasets/openai/gsm8k) | Grade-school math problems with worked answers for training and held-out evaluation. |
| [SmolTalk: Smol-Magpie-Ultra](https://huggingface.co/datasets/HuggingFaceTB/smoltalk) | [Apache-2.0](https://huggingface.co/datasets/HuggingFaceTB/smoltalk) | Synthetic multi-turn instruction conversations from the Smol-Magpie-Ultra subset. |
| [UltraChat 200k](https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k) | [MIT](https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k) | Filtered synthetic multi-turn conversations for supervised instruction tuning. |
| [SQuAD 1.1](https://huggingface.co/datasets/rajpurkar/squad) | [CC-BY-SA-4.0](https://huggingface.co/datasets/rajpurkar/squad) | Wikipedia passages with questions and answer spans for extractive question answering. |
| [UltraFeedback Binarized](https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized) | [MIT](https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized) | Synthetic chosen/rejected conversations and scores for preference optimization and SFT. |
| [CLEVR v1.0](https://cs.stanford.edu/people/jcjohns/clevr/) | [CC-BY-4.0](https://cs.stanford.edu/people/jcjohns/clevr/) | Synthetic scenes paired with visual questions, answers, scene graphs, and reasoning programs. |

OASST1 needs tree reconstruction and tree-grouped splits. Dolly is a share-alike opt-in. GSM8K training examples can support reasoning; its official test split is reserved for evaluation and excluded from synthetic-data seeds. These small instruction sources do not meet broad scratch-pretraining scale or coverage.

### 16 4 Rankings and reward scores

Output formats: json, jsonl, parquet.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [Anthropic HH RLHF](https://huggingface.co/datasets/Anthropic/hh-rlhf) | [MIT](https://huggingface.co/datasets/Anthropic/hh-rlhf) | Chosen and rejected conversations for preference optimization and reward modeling. |
| [UltraFeedback Binarized](https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized) | [MIT](https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized) | Synthetic chosen/rejected conversations and scores for preference optimization and SFT. |
| [OpenAssistant OASST1](https://huggingface.co/datasets/OpenAssistant/oasst1) | [Apache-2.0](https://huggingface.co/datasets/OpenAssistant/oasst1) | Human conversation trees and ranking signals for supervised and preference training. |

HH supplies chosen/rejected pairs; OASST1 includes ranking signals that require task-specific reconstruction. Rankings are supervision for preference or reward training, not calibrated numeric ground-truth rewards. Maintain held-out prompts and preserve ties or missing judgments.

### 16 5 Code and notebooks

Output formats: py, source_files, ipynb.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [Mostly Basic Python Problems](https://huggingface.co/datasets/google-research-datasets/mbpp) | [CC-BY-4.0](https://huggingface.co/datasets/google-research-datasets/mbpp) | Python generation examples with natural-language tasks and tests. |
| [HumanEval](https://github.com/openai/human-eval) | [MIT](https://github.com/openai/human-eval/blob/master/LICENSE) | Python completion benchmark; evaluation only in default presets. |

Use MBPP official train split for training and preserve the other splits for their stated roles. HumanEval is evaluation-only in default presets and must never be included in training or synthetic seeds. Source files can be wrapped in notebooks by a converter, but this does not supply notebook-editing or repository-scale supervision. Run code tests in isolated execution environments.

### 16 6 Structured records and tool calls

Output formats: json, jsonl, yaml.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [xLAM function-calling 60k](https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k) | [CC-BY-4.0](https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k) | Queries, tool schemas, and structured function-call answers. |
| [Glaive function calling v2](https://huggingface.co/datasets/glaiveai/glaive-function-calling-v2) | [Apache-2.0](https://huggingface.co/datasets/glaiveai/glaive-function-calling-v2) | Synthetic conversations with function schemas and tool-call turns. |
| [CLEVR v1.0](https://cs.stanford.edu/people/jcjohns/clevr/) | [CC-BY-4.0](https://cs.stanford.edu/people/jcjohns/clevr/) | Synthetic scenes paired with visual questions, answers, scene graphs, and reasoning programs. |

xLAM is declared CC BY 4.0 but currently gated: the user must review current conditions and authorize scoped credentials before access. It is not an anonymous one-click default. Preserve tool schemas and validate calls against them. JSON-to-YAML conversion alone does not create general structured-data expertise.

### 16 7 Raster images

Output formats: png, jpeg, webp, tiff.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [dSprites](https://github.com/google-deepmind/dsprites-dataset) | [Apache-2.0](https://github.com/google-deepmind/dsprites-dataset/blob/master/LICENSE) | Synthetic binary shape images with known factors; small image-generation and conversion fixture. |
| [Fashion MNIST](https://github.com/zalandoresearch/fashion-mnist) | [MIT](https://github.com/zalandoresearch/fashion-mnist#license) | Small grayscale clothing images and class labels for pipeline smoke tests. |
| [CLEVR v1.0](https://cs.stanford.edu/people/jcjohns/clevr/) | [CC-BY-4.0](https://cs.stanford.edu/people/jcjohns/clevr/) | Synthetic scenes paired with visual questions, answers, scene graphs, and reasoning programs. |

dSprites contains simple binary shapes and known factors, useful for small controlled generation experiments. Fashion MNIST is an image/class-label smoke-test fixture, not a captioned image-generation corpus. SVG renders supply an additional narrow image source. This bank does not yet include a diverse verified open natural-image/caption corpus.

### 16 8 Speech audio

Output formats: wav, flac, mp3, ogg.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [LibriTTS](https://www.openslr.org/60/) | [CC-BY-4.0](https://www.openslr.org/60/) | English speech and text designed for text-to-speech research. |
| [LibriSpeech](https://www.openslr.org/12) | [CC-BY-4.0](https://www.openslr.org/12) | Read English speech aligned with transcripts. |
| [CSTR VCTK 0.92](https://datashare.ed.ac.uk/handle/10283/3443) | [CC-BY-4.0](https://datashare.ed.ac.uk/items/30e7453c-9ea8-48b4-8e18-f96d0dc62928/full) | English speech from multiple speakers and accents with transcript files. |
| [LibriTTS-R](https://www.openslr.org/141/) | [CC-BY-4.0](https://www.openslr.org/141/) | Restored English speech aligned with text for multi-speaker speech synthesis. |

LibriTTS supports text-to-speech examples; LibriSpeech primarily supports speech-to-text and alignment, where the generated output is text. Audio codecs are export choices, not new task supervision. Preserve speaker splits and check shared origin before mixing these related corpora. Music, sound effects, and multilingual speech generation need additional sources and model recipes.

### 16 9 Video

Output formats: mp4, webm, mov.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [Big Buck Bunny](https://peach.blender.org/download/) | [CC-BY-3.0](https://peach.blender.org/about/) | Open movie for video decoding, clip preparation, and limited generation experiments; not a diverse captioned corpus. |

Big Buck Bunny is a single open movie fixture for decoding, temporal sampling, and limited experiments, not a sufficient video-generation corpus. Select the released movie only; separately released isolated music can have different terms and is excluded. Captions and prompt/clip pairs need a separately versioned labeling recipe. Hold FineVideo outside the default bank pending per-asset license and additional access-term review.

### 16 10 Tables and time series

Output formats: csv, tsv, parquet, arrow, npy, hdf5.

| Source | Declared license | Intended use |
| --- | --- | --- |
| [UCI Electricity Load Diagrams](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014) | [CC-BY-4.0](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014) | Electricity consumption series for numeric forecasting and table-output adapters. |
| [Iris](https://archive.ics.uci.edu/dataset/53/iris) | [CC-BY-4.0](https://archive.ics.uci.edu/dataset/53/iris) | Small labeled flower-measurement table for classification and tabular pipeline checks. |
| [Wine Quality](https://archive.ics.uci.edu/dataset/186/wine+quality) | [CC-BY-4.0](https://archive.ics.uci.edu/dataset/186/wine+quality) | Red and white wine chemistry tables with quality scores for regression or classification. |

The UCI source provides real numeric sequences for forecasting and table adapters. Use chronological splits with non-overlapping windows; preserve numeric and daylight-saving conventions. It does not supply universal CSV-generation or scientific reasoning supervision.

### 16 11 Documents presentations and web pages

Output formats: html, pdf, docx, pptx, epub.

No dedicated open document-layout output corpus has been qualified in this starter bank. General text sources can populate content, but do not supply page layout, slide structure, accessibility, or document-editing targets. Plan a separately licensed synthetic template corpus with known structured documents and deterministic render/export into HTML, PDF, DOCX, PPTX, and EPUB. This is a proposed source recipe, not an existing downloadable dataset.

### 16 12 Custom formats 3D and other modalities

Output formats: custom.

No universal source can cover arbitrary custom formats. Require a reviewed source manifest, schema, validator, viewer, output converter, and compatible model adapter. Dedicated 3D mesh, CAD, motion, scientific binary, and other modality corpora remain a catalog coverage gap; unknown files can be retained without a training claim.

### 16 13 Presets and user workflow

The first preset to qualify will be SVG starter: Lucide, Tabler, Heroicons, Bootstrap, Phosphor, Feather, and Material SVG assets. An attribution expansion adds Twemoji graphics and Game Icons. A separate share-alike expansion adds OpenMoji after project policy enables it. Start with a bounded preview, proposed 100 assets per source, and let users adjust the scope before acquisition.

The flow is Data, Dataset Bank, intended output or task, preset/source selection, sample preview, destination and scope, download, preparation, dataset version, then compatible training or evaluation. A card shows publisher, license evidence, obligations, access conditions, last check, pinned revision, available splits, measured size or unknown, label quality, and readiness. Training-only and evaluation-only roles must be visible before selection.

Acquisition is a queued worker job governed by the same capacity, permissions, leases, retries, and budget policy as other jobs. Download cancellation or partial transfer never produces a ready dataset. Repeated requests reuse a matching committed snapshot within authorized scope; upstream updates create new versions. The prepared dataset retains source hashes, raw assets, transformations, split assignments, license snapshots, attribution, and rejection reports.

The JSON catalog defines source manifests and SVG presets; BANK07 governs their qualification.


## 17 RAG and context evaluation contract

### 17 1 Retrieval metrics

Let K be a positive cutoff, R the set of labeled relevant evidence IDs for a query, and T the first K distinct retrieved IDs. Document and chunk scores are separate; chunking changes require a new mapping from labeled source spans. Record the relevance threshold, tie policy, and metric implementation version. The initial binary metrics use these definitions.

| Metric | Meaning | Reporting rule |
| --- | --- | --- |
| Recall@K | Number of IDs in both T and R divided by the number in R | Measures recovery of known relevant evidence; incomplete labels limit interpretation |
| Precision@K | Number of IDs in both T and R divided by K | Missing result slots count as nonrelevant; also show actual result count |
| Hit@K | One if T includes any ID in R, otherwise zero | Useful when at least one supporting result is sufficient |
| MRR@K | Mean reciprocal rank of the first relevant result within K | Per-query reciprocal rank is zero if none is found |
| nDCG@K | Graded gain discounted by rank and normalized against the ideal ranking | Initial recipe uses gain (2^grade - 1) and discount 1 / log2(rank + 1); pin the formula |

Queries with no labeled relevant evidence have undefined Recall@K and ideal-normalized nDCG; display N/A and the excluded count rather than silently scoring them zero. Evaluate confirmed unanswerable queries in a separate abstention slice. State the treatment of unjudged results and report judged coverage. Aggregate per-query scores with macro means, sample counts, language/task/source slices, and uncertainty where meaningful. Never merge document-level, chunk-level, approximate-index, and judge-based recall into one number. Deterministic metric definitions and available implementations can be checked against [ir-measures](https://ir-measur.es/en/latest/measures.html).

### 17 2 Answer evaluation

Groundedness measures support in supplied evidence; correctness measures agreement with a reference or task rubric. A grounded answer can still be wrong if its source is outdated. Track answer relevance, exact match or token F1 where the task permits, citation support precision, coverage of claims requiring citations, and correct abstention on unanswerable cases. Name whether context precision/recall is ID-based, reference-claim-based, or judge-based. Ragas documents [context recall variants](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/) and [faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/); it is an integration candidate, not the owner of the release policy.

Each metric must declare required fields, denominator, treatment of empty answers/evidence, evaluator revision, and missing-data behavior. Pin judge model, prompt, decoding, and thresholds; calibrate against a human-reviewed set and expose disagreement and failed evaluations. Synthetic query generation accelerates development but needs review and remains labeled by origin. Hold out final evaluation queries and answers from recipe tuning and fine-tuning; the supporting documents remain in the RAG corpus when the task intentionally tests retrieval from them. Include robustness cases for adversarial or conflicting sources and measure operational latency, tokens, cost, index build time, and freshness separately.

### 17 3 Context engineering metrics and diagnostics

| Measure | Question answered | Evidence required |
| --- | --- | --- |
| Task success and instruction adherence | Did the answer or bounded tool workflow meet its goal? | Expected result, output/schema checks, task rubric, human or calibrated judge review |
| Evidence retention and use | Did required facts survive packing/compression and support the output? | Labeled evidence spans, before/after block mappings, citations or task checks |
| Position and length robustness | Does quality change when evidence moves or context grows? | Paired cases with controlled evidence position, length, and distractors |
| Memory accuracy and isolation | Are facts correctly stored, updated, recalled, expired, and scoped? | Versioned multi-turn fixtures, expected memory state, cross-session access probes |
| Injection and conflict handling | Does untrusted text redirect behavior or override intended rules? | Defined attack objective, conflict policy, observed output/actions, attack success rate |
| Efficiency and budget adherence | What quality is achieved for the input, cost, and latency? | Per-block tokenizer counts, retained evidence, compression ratio, output reserve, measured p50/p95 and usage |

Use paired ablations such as no retrieval, normal retrieval, gold evidence, reordered evidence, and removed context blocks to investigate failures. A quality drop after removing a block is an experimental observation; do not claim a general causal effect without controlled comparisons. Compare summaries against task-relevant facts rather than compression ratio alone. Plot quality against input tokens and evidence position; publish the tested operating envelope instead of a universal effective context-window claim. The [Lost in the Middle research](https://arxiv.org/abs/2307.03172) motivates position tests, and [RULER](https://github.com/NVIDIA/RULER) is a candidate synthetic stress-suite adapter. Neither replaces real project tasks; verify benchmark and dependency licenses before enabling a preset.

### 17 4 Cluster interpretation and reproducibility

The explorer is an investigation aid. UMAP documentation notes that projection can distort density and split apparent clusters; projected distances cannot substitute for the configured embedding-space similarity or retrieval metrics. Save coordinates and cluster labels with complete manifests and display the selected input space. Compare representative neighbors and human labels before assigning semantic cluster names. [UMAP clustering guidance](https://umap-learn.readthedocs.io/en/latest/clustering.html).

Proposed integration references: [pgvector](https://github.com/pgvector/pgvector), [LlamaIndex](https://developers.llamaindex.ai/python/framework/), [Sentence Transformers](https://sbert.net/docs/sentence_transformer/usage/usage.html), [cross-encoder reranking](https://sbert.net/examples/cross_encoder/applications/README.html), and [Plotly WebGL rendering](https://plotly.com/javascript/webgl-vs-svg/). Their documentation supports qualification planning; no RAG, visualization, or context integration is implemented yet.


## 18 Iterative labeling cycle contract

Each cycle follows batch selection, optional model drafting, human review/correction, adjudication, approved-data snapshot, labeling-model training, independent qualification, and next-batch assignment. The manual seed omits drafting. An existing-model seed records its model revision, prompt/context recipe where applicable, and output-to-label mapping. Campaigns may use the model registry for drafts, but a model must support the label schema and data modality before it is eligible.

The default training input is the accumulated approved set, with an explicit recipe for weighting, replay, exclusions, and class balance. Training from the original base versus continuing the previous labeling checkpoint is a recorded recipe choice; qualify both paths separately before claiming support. Reject pseudo-labels, unresolved reviews, invalid schema values, and protected validation/test examples from the default campaign snapshot. Later pseudo-label policies require separate support and must never bypass origin tracking.

Before the first training cycle, reserve a human-labeled validation/audit set and a protected final test set using source/group-aware splits. The audit labels should be created without draft visibility or independently adjudicated to reduce reviewer anchoring. A first small batch may lack enough labels or classes to train a useful model; preflight must explain the deficiency and allow more manual labeling. Validation can guide cycle selection, while the final test set stays out of repeated tuning. Labels selected for targeted active review are not automatically representative of the deployment distribution.

Track raw task metrics on independent evidence, accepted/corrected/rejected/skipped counts, review agreement, throughput, median review time, class/source/language coverage, and cost. Prediction scores must identify whether they are calibrated probabilities, backend scores, or model self-reports; do not compare confidence values across models as equivalent. For generative labels, use a task rubric and schema checks with independent review. Compare error slices and examples as well as aggregate scores; there is no guaranteed improvement every cycle.

Batch states are selected, drafting, ready for review, in review, awaiting adjudication, and closed; prediction failures can fall back to manual annotation. Training and qualification are separately recorded jobs with their own failure/cancellation states. A cycle is complete only when its data snapshot and next-model decision are recorded. Pending batches never change model versions implicitly; re-drafting creates a distinct prediction revision and preserves existing human work.

Manual advance is the default. A campaign owner can configure automatic training after batch approval and automatic next-batch drafting after a candidate passes named gates, within explicit compute, iteration, and data-scope limits. Pause stops future stages and requests cancellation for active jobs through the shared job protocol; already accepted labels remain available. A failed or worse candidate keeps the previous qualified drafting model or returns to manual mode. Restoring an earlier model does not discard corrections or undo source permissions.

PostgreSQL owns campaign state and model assignments. RabbitMQ dispatches prediction and training; S3 holds assets, approved snapshots, and checkpoints. Atomic closure and immutable manifests prevent duplicate training triggers; reruns record compatible attempts. Annotation adapters map external task/prediction/review IDs under organization/project authorization. Callbacks cannot launch untracked training or export private data. Label Studio requires edition/version, license, identity, and prediction/review round-trip qualification.

R1 must qualify both seed paths and repeated cycles on one text-labeling task. Each additional label type needs a qualified schema, correction UI, trainer, and evaluator. Import support does not establish training support. Advanced uncertainty/disagreement/diversity sampling remains a Target; representative random audit batches remain independent.
