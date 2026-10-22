# ModelAnvil architecture decisions

Record consequential implementation choices here after evaluating alternatives. Product constraints are established in the PRD. Decision 002 records the application stack baseline; exact versions, training engines, and provider qualification remain open.

## Record format

Create one numbered Markdown file per decision, such as `0001-artifact-manifests.md`.

Each record should contain:

- Title, date, status, and responsible owner.
- Problem and applicable PRD requirement IDs.
- Options considered and evidence from pilots.
- Selected approach and its consequences.
- Compatibility, security, migration, and operational implications.
- Verification evidence and conditions for revisiting the decision.

## Initial decisions to investigate

1. Artifact and normalized sample schemas.
2. Organization isolation and job-scoped credentials.
3. Worker protocol, scheduler integration, and distributed recovery.
4. Scratch and post-training backend adapters.
5. Storage, metadata database, and workflow durability.
6. Managed, self-hosted, and hybrid packaging.
7. Extension SDK and executable-code isolation.

- [001 Job queue recommendation](001-job-queue.md) — proposed RabbitMQ dispatch with durable database claims and recovery; Kafka considered.

- [002 Technology stack](002-technology-stack.md) — Vite/React, SwiftUI, Django, PostgreSQL, S3 providers, Scrapling, worker boundaries, deployment qualification, and the PRD 0.6 RAG/context extension.

- [003 Fine-tune decision loop](003-fine-tune-decision-loop.md) — the next product slice is private fine-tune and decide; broader R1 surfaces stay later.
