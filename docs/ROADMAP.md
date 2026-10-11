# ModelAnvil delivery roadmap

This is a dependency-based planning outline. Dates, owners, staffing, and budgets are not assigned. Both scratch training and fine-tuning are required for the first complete release.

## Milestone 1 — Foundation and feasibility

- Define organization isolation and project permissions.
- Define assets, normalized samples, versioned dataset manifests, run inputs, and lineage.
- Specify the worker protocol and backend capability registry.
- Pin the API and client dependencies from decision 002; qualify the S3 contract with SeaweedFS and a selected managed provider.
- Qualify Scrapling acquisition, durable crawl checkpoints, source provenance, and cancellation with controlled fixtures.
- Pilot scratch training, fine-tuning, distributed recovery, custom-format conversion, and a candidate multimodal recipe.
- Pilot PostgreSQL full-text/pgvector retrieval, hand-scored relevance metrics, exact context traces, and a saved projection.
- Record the hardware profile, integration versions, and unresolved limitations.

Exit evidence: measured feasibility reports and an agreed initial compatibility matrix.

## Milestone 2 — Both training journeys

- Build source import, extraction, cleaning, deduplication, and dataset versioning.
- Add tokenizer and model registration, preflight, job submission, and monitoring.
- Connect scratch pretraining, continued pretraining, full fine-tuning, and supported adapters.
- Connect baseline evaluation, comparison, and independently loadable exports.
- Build the Vite/React workspace and define the SwiftUI client coverage against the common API.
- Package the core workflows for managed and self-hosted environments with Docker images and a Compose installation.

Exit evidence: PRD acceptance scenarios 1 and 2 pass on the reference configuration.

## Milestone 3 — Data collaboration and alignment

- Add controlled scraping, annotation campaigns, quality review, and blind ranking.
- Connect synthetic generation, preference optimization, and reward-model training.
- Qualify one complete learned-reward RLHF recipe, from human preferences and reward training to rollout generation and policy optimization.
- Qualify a verifiable-reward RL recipe and independent evaluations.
- Implement supported media adapters and the versioned extension SDK.
- Turn evaluation failures into reviewed annotation candidates.
- Build iterative campaigns with manual/model-assisted seeds, review diffs, cumulative approved snapshots, model qualification, and fixed next-batch assignments.
- Qualify two train-and-next-batch cycles per entry mode, including independent audits, failed candidates, pause/resume, rollback, duplicate-job recovery, and budget/cycle limits.

Exit evidence: PRD acceptance scenarios 3 through 6, 13, and 17 pass.

## Milestone 4 — RAG and context workbenches

- Build knowledge-base/index versions, lexical/dense/hybrid retrieval, reranking, and authenticated query serving.
- Add relevance annotation, independent retrieval/answer metrics, protected suites, comparisons, and release gates.
- Build the cluster explorer with saved coordinates, original-space neighbors, sampling disclosure, and linked failure review.
- Build context composition, exact input previews, token budgets, history/memory strategies, frozen tool replay, and controlled ablations.
- Qualify evidence position/length, distractors, contradictions, injection, missing evidence, overflow, and multi-turn isolation.
- Validate permission revocation, deletion, cache invalidation, recovery, and rollback across corpus versions.

Exit evidence: PRD scenarios 14–16 pass on the named text recipe, including local self-hosted models and judges.

## Milestone 5 — Multi-team qualification

- Enforce quotas, scheduling policies, cost attribution, and budgets.
- Validate hybrid worker access and data egress policies.
- Complete identity integrations, backups, restore, migrations, and upgrade procedures.
- Qualify distributed recovery, API/CLI automation, serving, quantization, and rollback.
- Qualify the Kubernetes/Helm production reference and declared database, broker, and artifact recovery guarantees.
- Publish the tested support matrix and operational documentation.

Exit evidence: all R1 acceptance scenarios and the agreed load and recovery profiles pass. Target features are labeled supported only after separate qualification.

## Later expansion

Additional architectures, audio/video training recipes, multimodal RLHF and additional RL algorithms, more providers and schedulers, larger clusters, active learning, distillation, and model merging follow the same versioning and compatibility contracts.

## Dataset Bank and job dispatch qualification

PRD 0.2 adds BANK01-BANK07 and OPS07. Qualify the SVG Git connector and starter preset before enabling downloads; additional source candidates require their own license, sample, and transport checks. Test RabbitMQ dispatch with the database outbox, capacity admission, durable claims, leases, fencing, and distributed allocation before committing to the production topology. See the Dataset Bank specification and architecture decision 001.

PRD 0.3 makes complete RLHF an R1 requirement through ALN05 and acceptance scenario 13. Select and pin a qualified learned-reward policy-optimization algorithm and backend during feasibility; PPO and RLOO are candidates. Budget and checkpoint the rollout, scoring, and update stages through the shared worker protocol.

## Stack qualification baseline

PRD 0.5 and architecture decision 002 record the application choices and S3 provider direction. SeaweedFS, Scrapling, and the cluster package become supported only after their qualification evidence passes. The identity provider, cloud vendor, Mac feature matrix, and training engine combinations remain open.

## RAG and context qualification

PRD 0.6 adds RAG01–RAG08 and CTX01–CTX04. See [the workbench specification](rag-context-workbench.md). Qualify the candidate retrieval, embedding, evaluator, projection, and renderer versions against the corpus scale and tested context envelope. RAG/context work adds release scope and must be included before dates or staffing are estimated. Multimodal retrieval, GraphRAG, and autonomous agent orchestration remain later targets.

## Iterative labeling qualification

PRD 0.7 adds ANN04–ANN07 and scenario 17. See [the iterative labeling specification](iterative-labeling.md). Qualify at least one text task with both seed modes; each additional annotation schema/modality needs its own correction UI, trainer, and evaluator. Automatic uncertainty/disagreement/diversity selection remains a Target; the reviewed batch/train/review loop is R1.

## Engineering implementation breakdown

The [engineering pack](engineering/README.md), derived from PRD 0.7, expands this roadmap into technical contracts, 12 application flows, design direction, a relational schema, and [17 work packages](engineering/implementation-plan.md). Each package records owner roles, dependencies, deliverables, and exit evidence; every PRD requirement and all 17 acceptance scenarios are mapped. The work-package plan is the detailed implementation breakdown; this roadmap remains its product milestone summary. Dates, budgets, and named staffing remain uncommitted pending WP-01 measurements.
