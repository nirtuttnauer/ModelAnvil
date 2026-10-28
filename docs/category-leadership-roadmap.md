# ModelAnvil category leadership roadmap

21 October 2026 · Audience: small teams building private AI products

Make ModelAnvil the easiest private workspace for a small team to improve an AI product, prove the improvement on its own tasks, and ship the exact version it tested. The product promise is a repeatable path from private examples to a measured result and a portable release.

The initial category is **private model improvement for small product teams**. Start with text classification, structured extraction, and constrained response tasks. Validate one of these as the first commercial use case before broadening. Teams with changing factual knowledge should also compare retrieval and prompt changes before choosing training.

## Strategy and competitive position

Training through a friendly interface is already available. [Unsloth](https://unsloth.ai/docs) provides a local interface for running and training models. [LlamaFactory](https://github.com/hiyouga/LlamaFactory) provides a broad fine-tuning CLI and web UI. [AutoTrain](https://huggingface.co/docs/autotrain/main/tasks/llm_finetuning) documents CSV/JSONL input, chat templates, and local/cloud training. [Argilla](https://docs.argilla.io/v2.4/) focuses on collaborative data and feedback. [MLflow](https://mlflow.org/docs/latest/genai/datasets) connects application traces to evaluation datasets.

The strategic opportunity is to make those activities feel like one dependable product for a small team: understand a failure, review a correction, improve a candidate, compare it fairly, and release or reject it. This is a positioning hypothesis to validate with users and comparative pilots. Local execution, evaluation, and feedback are each established capabilities in the market.

Build an advantage through excellent defaults, a short time to useful evidence, task-specific data guidance, reliable operations, and complete portability. Keep customer datasets and weights under customer control. Improvements to recipes and onboarding should come from permissioned research and reproducible examples.

## Starting point

| Existing foundation | Evidence and implication |
| --- | --- |
| Guided fine-tuning, real Apple GPU execution, saved chat, and downloadable artifacts | Reuse the [guided journey](engineering/guided-fine-tuning.md). The [14 October report](engineering/verification/useful-local-training-2026-10-14/report.md) demonstrates a narrow customization task; six answer checks do not establish broad model quality. |
| Published datasets, checkpoints, durable jobs, budgets, candidate review, and bounded evaluation | Reuse the [local implementation](engineering/p0-implementation.md). Its local CPU evidence has a different scope from the guided GPU path. |
| A deliberately bounded guided runtime | [Runtime limits](../modelanvil/runners/training/hf_runtime.py) currently include 1,000 rows, 128 tokens per example, and 3,000 updates. These limits constrain realistic conversations and extraction workloads. Expand them through measured profiles. |
| Durable evaluation with real inference | The [evaluation worker](../modelanvil/runners/eval_worker.py) currently declares CPU execution, plain prompt formatting, and a maximum of 32 output tokens. Qualify evaluation of the exact guided adapters with their native templates before presenting an automatic quality verdict. |
| A production web deployment definition | The [deployment stack](../deploy/production/README.md) includes PostgreSQL, Gunicorn, and Caddy. Customer invitations, hosted workers, and complete training qualification have separate gates. |
| Annotation, retrieval, context, and advanced training foundations | Finish the supported portions needed by the initial use case. The [18 October labeling report](engineering/verification/labeler-2026-10-18/test-summary.json) still excludes automatic drafting, retraining, and qualification. |

Older status documents describe earlier snapshots. Reconcile the capability ledger with newer source and verification reports; a saved task status or passing fixture does not establish current product qualification.

## Delivery assumptions

Use the following windows for sequencing, starting when the team begins this roadmap. They are planning ranges, not delivery commitments. Assume three engineers covering product, applied ML, and platform, with founder-led product research and part-time design. A smaller team should preserve the order and extend the windows. Re-estimate after the first two weeks using actual work and pilot hardware.

Keep one primary installation and hardware profile for the first beta. Start from the existing Apple Silicon evidence; prioritize one Linux/NVIDIA profile if pilot hardware requires it and physical qualification becomes available. Do not make all accelerator vendors a beta dependency.

## Weeks 1 and 2 establish the customer and baseline

Interview eight prospective teams and observe at least five attempts at a real task. Record the current workflow, data restrictions, hardware, failure modes, setup time, and who owns the buying decision. Select one task and recruit five design partners with lawful access to usable data. Prepare outreach materials; contacting people requires a separate human instruction.

Define activation as a team completing a baseline comparison and understanding whether its candidate improved. Track setup time, active user effort, workload runtime, completion rate, and repeat usage separately. Keep operational measurement local by default and make external analytics optional.

Reconcile the current implementation and Aftur tickets with their actual evidence. Produce a short supported matrix for import, train, evaluate, export, serve, and recover. Treat already implemented work as verification or acceptance work where appropriate.

**Exit gate:** one documented use case, five willing design partners, a frozen evaluation rubric, an observed activation baseline, and a measured plan for the next stage. If the use case is not compelling, revise it before expanding the runtime.

## Weeks 3 through 6 support useful workloads

Expand the guided path to a measured first target of 2,048 tokens per example and 10,000 examples on the selected profile. These are qualification targets; memory and throughput measurements may justify a smaller first supported envelope. Add token-length distributions, actionable invalid-row repair, source-group deduplication, and enough headroom information to reject jobs before allocation. Avoid silent truncation.

Finish the relevant portions of existing model acquisition, adapter training, hardware admission, preflight, and run recovery work. Preserve the simple guided path while making advanced settings available when needed. Make the next action clear after import, training, and failure.

Ship a supported installation route for the reference machine and publish three reproducible starter examples: classification, structured extraction, and constrained responses. Each includes data, an evaluation suite, expected runtime limits, and an external loading example. Begin discussing paid pilot terms while product work continues.

**Exit gate:** at least four of five observed first-time pilot users reach real baseline/candidate outputs without developer assistance. Target no more than 15 minutes of active setup after installation and model provisioning; report cold download time and compute time separately. Long examples and insufficient memory produce useful errors.

## Weeks 7 through 10 make improvement visible and trustworthy

Connect the exact guided candidate, adapter, baseline, tokenizer, native chat template, and decoding settings to durable evaluation. Preserve real outputs, failed and missing cases, scoring versions, source-group checks, and execution provenance. Offer deterministic task checks first; calibrate any model judge against human review before using it for decisions.

Add a decision report that answers: what improved, what regressed, how many cases support the result, what it cost in measured resources, and whether the candidate meets the team's declared release gates. Show per-case changes, slices, uncertainty, runtime, and measured latency. A lower training loss must never become an answer-quality claim.

Maintain separate training, development evaluation, and final test sets. Cases repeatedly inspected for tuning belong to development evaluation. Turning a development failure into training data must preserve its origin and exclude related source groups from the protected final test. Rotate final evidence when it has influenced tuning.

**Exit gate:** three pilot tasks produce reproducible decision reports, including at least one correctly rejected candidate. Set the required improvement before running each comparison; an example goal is a ten percentage point increase in task success without a declared regression. Report uncertainty and collect more cases when the sample is too small. Final claims use an independent test sized to the task, usually hundreds of cases rather than a handful of demos.

## Weeks 11 through 16 complete the improvement cycle

Connect failed development cases to the existing annotation workflow, reviewed corrections, a new immutable dataset, training, and another independent comparison. Preserve the original prediction and each correction. Allow the previous model to remain active when a candidate fails. Reuse the campaign engine and its job/budget contracts.

For knowledge tasks, compare prompt changes, retrieval, and fine-tuning using the same task protocol. Show the simplest option that meets the target. Freeze the corpus and context configuration when comparing retrieval-based systems; retain citations and source permissions.

Add customer-controlled application feedback ingestion with minimal retained content. Support small-team invitations, reviewer permissions, and project membership before inviting a second team member. Apply private-data policy to judges, synthetic generation, analytics, logs, and support bundles as well as training.

**Exit gate:** three teams complete two genuine review/improvement cycles. At least one rejected or worse candidate keeps the prior version active. A team can identify the exact data, recipe, evaluation, and exported artifact behind its selected result. Development feedback never contaminates the protected final test.

## Weeks 17 through 24 make the product dependable in daily use

Qualify the complete reference deployment: authentication, backup/restore, upgrades, worker interruption, cancellation, duplicate delivery, artifact corruption, memory exhaustion, and rollback. Reuse existing local restore and production-stack work, then extend the evidence to the actual pilot topology. Verify the real trained export in a clean external consumer and exercise a real application request through the supported inference endpoint.

Add a small Python/CLI interface for replaying evaluations and enforcing declared regression thresholds in CI. Add explicit, budgeted recurring evaluations with slice changes, latency, failure rate, and model-version identity. Keep alerts actionable and retain the evidence behind a failure.

Run paid pilots with clear installation, support, and upgrade boundaries. Keep the existing MIT code license intact. Test paid deployment/support and team workflow services; price only after measuring value and support cost. Customer-owned compute remains an option. An optional managed service needs separate data-location and operations qualification.

**Exit gate:** target ten activated pilot teams, six returning for another cycle within 30 days, and three paying or explicitly committing to a paid pilot. These are validation goals. Revisit the proposition if retention or willingness to pay is weak. Declare service targets for the tested topology and verify them over a stated period; a load test alone cannot establish uptime.

## Months 7 through 9 prove an advantage and expand selectively

Publish permissioned case studies and reproducible comparisons against realistic alternatives: a fine-tuning UI workflow, an evaluation/data toolchain, and the customer's existing scripts. Measure task quality, hands-on time, complete-cycle time, total resource cost, and recovery behavior. Pin versions and disclose task/hardware limits. Use the results to substantiate specific advantages; avoid an unsupported universal category ranking.

Add a private remote worker and managed artifact transfer only after pilot demand and retention justify expansion. Qualify authorization, scoped input/output transfers, revocation, reconnect, and recovery before offering rented GPUs. Then implement one customer-owned compute provider with bounded allocation lifetime, confirmed cleanup, and usage reconciliation. Select the provider from actual customer requirements.

**Exit gate:** three reproducible customer outcomes, a measured advantage on the chosen task and workflow, and clear demand for the next supported environment. Expand one environment or provider at a time.

## Measures that define success

The primary measure is **weekly teams completing an independently evaluated improvement cycle and recording a release or rejection decision**. Count a cycle once, identify the exact candidate and evaluation, and require real execution. Rejections count because the product helped avoid a bad release. Track accepted improvements separately so rejection volume cannot hide poor model outcomes.

| Measure | Definition or initial target |
| --- | --- |
| Activation | Baseline and candidate compared, evidence inspected, decision recorded; first pilot target 4 of 5 observed users |
| Time to first decision | Separate installation/download, hands-on work, queue time, training, and evaluation; establish the baseline in weeks 1 and 2 |
| Useful improvement | Task-specific success increase, or lower measured latency/resource cost at the same declared quality threshold |
| Repeat use | Initial target: 6 of 10 activated teams complete another cycle within 30 days |
| Reliability | Workflow completion on the supported profile, recoverable failures, artifact integrity, restore results, and observed endpoint health |
| Commercial viability | Initial target: 3 paid or committed pilots, measured support effort, and a plausible margin for the chosen service |
| Portability and privacy | Independently loadable selected releases and verified operation within the declared data policy |

## Work to defer

Defer broad multimodal expansion, many GPU providers, multi-node training, universal accelerator parity, a plugin marketplace, and additional clients until the core workflow has repeat users. Continue maintaining existing supported behavior. Add model families because they improve the chosen task or fit customer hardware. Qualify one efficient adapter path before broad quantization and algorithm expansion.

Scratch pretraining, complete RLHF, verifier RL, context/RAG, and other original R1 requirements remain in the [PRD](PRD.md) and [delivery roadmap](ROADMAP.md). This plan sequences an intermediate product beta and commercial validation. It does not remove those commitments or relabel the beta as complete R1. Any release-scope amendment must update the PRD and engineering plan together.

## First two weeks of work

1. Product: recruit the first five design partners and choose one task from observed workflows.
2. Product and engineering: record a fresh installation-to-decision baseline on actual pilot hardware.
3. Applied ML: design protected evaluation splits, measure realistic example lengths, and size the first expanded runtime profile.
4. Engineering: reconcile newer local evidence with older Aftur descriptions and identify the remaining acceptance work in existing tickets.
5. Product engineering: instrument the local funnel and make setup failures actionable using the existing onboarding and run-detail surfaces.
6. Founder: prepare the pilot offer, interview guide, comparison rubric, and a weekly evidence review.

## Aftur execution map

The map below is populated from verified Aftur writes. Existing tasks retain their statuses and approvals; roadmap comments propose sequencing and acceptance emphasis without changing approved scope. New tickets are proposed work with dependencies and explicit acceptance criteria.

### New tickets

| Ticket | Priority | Planning window | Work |
| --- | --- | --- | --- |
| TASK-43 (CL01) | P0 | Weeks 1–2 | Validate the first private AI use case and recruit design partners |
| TASK-44 (CL02) | P0 | Weeks 1–2 | Measure activation and reconcile the supported capability baseline |
| TASK-45 (CL03) | P0 | Weeks 3–6 | Expand guided training beyond 128 tokens and 1000 examples |
| TASK-46 (CL04) | P0 | Weeks 7–10 | Evaluate exact guided adapters with their native model templates |
| TASK-47 (CL05) | P0 | Weeks 7–10 | Show a reproducible improvement decision report |
| TASK-48 (CL06) | P0 | Weeks 3–10 | Enforce a private data policy across the improvement workflow |
| TASK-49 (CL07) | P1 | Weeks 11–16 | Onboard a private team with invitations and reviewer permissions |
| TASK-50 (CL08) | P0 | Weeks 17–24 | Qualify the complete private beta deployment and recovery journey |
| TASK-51 (CL09) | P1 | Weeks 3–10 | Ship three reproducible task playbooks with independent evaluations |
| TASK-52 (CL10) | P1 | Weeks 11–16 | Compare prompt changes retrieval and fine tuning on one task |
| TASK-53 (CL11) | P1 | Weeks 11–16 | Import private application feedback into reviewed development data |
| TASK-54 (CL12) | P1 | Weeks 17–24 | Replay evaluations and enforce regression gates from CI |
| TASK-55 (CL13) | P1 | Weeks 17–24 | Monitor quality and latency with budgeted recurring evaluations |
| TASK-56 (CL14) | P1 | Weeks 3–24 | Validate paid pilot packaging and the cost of supporting teams |
| TASK-57 (CL15) | P2 | Months 7–9 | Benchmark the complete workflow against realistic alternatives |
| TASK-58 (CL16) | P1 | Weeks 17–24, with benchmark follow-up in months 7–9 | Review private beta retention and make the launch decision |
| TASK-59 (CL17) | P2 | Months 7–9, demand gated | Qualify private remote workers and managed artifact transfer |
| TASK-60 (CL18) | P2 | After remote-worker qualification and demonstrated demand | Add one demand selected customer owned compute provider |

### Existing tickets reused

| Ticket | Planning window | Contribution |
| --- | --- | --- |
| TASK-3 | Weeks 1–6 | Guided onboarding |
| TASK-5 | Weeks 3–6 | Preflight and honest estimates |
| TASK-6 | Weeks 7–10 | Independent evaluation foundation |
| TASK-7 | Weeks 7–24 | Release evidence and independent export |
| TASK-8 | Weeks 3–24 | Run progress and recovery |
| TASK-10 | Weeks 11–16 | Reviewed improvement cycles |
| TASK-11 | Weeks 11–16 | Retrieval for knowledge tasks |
| TASK-12 | Weeks 11–16 | Measured prompt and context changes |
| TASK-14 | Weeks 3–6 | Pinned model acquisition |
| TASK-15 | Weeks 3–6 | Useful guided adapter training |
| TASK-16 | Weeks 3–10 | Measured memory and throughput |
| TASK-18 | Weeks 3–24 | Executable local models |
| TASK-19 | Weeks 7–10 | Inspectable candidate comparison |
| TASK-20 | Weeks 17–24 | One real application serving path |
| TASK-21 | Weeks 3–16 | Reviewed data preparation |
| TASK-27 | Weeks 7–24 | Portable weights and adapters |
| TASK-34 | Weeks 3–24 | One supported installation and upgrade path |
| TASK-40 | Weeks 3–10 | Reference Apple hardware qualification |
| TASK-42 | Weeks 3–6 | Actual device admission |

New ticket source: `PRD-727037b1`, which preserves the user request and audience selection. Roadmap recommendations and ticket criteria are planning proposals. Start with TASK-43 and TASK-44; verify current evidence on the existing onboarding, training and evaluation tickets before scheduling their remaining work.

TASK-44 implementation and local verification are recorded in the [activation baseline review](engineering/verification/task44-activation-2026-10-21/report.md). Customer discovery and representative user measurements in TASK-43 remain separate from this automated operational baseline.
