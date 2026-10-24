# ModelAnvil Engineering Planning Pack

Version 0.1 | 8 October 2026 | Derived from PRD 0.7 | Proposed implementation baseline

This pack turns the product scope into engineering contracts, user journeys, interface direction, a relational data model, and a dependency-based delivery plan. It is ready for architecture review and issue breakdown. It does not establish an implemented or qualified integration, a delivery date, or an approved budget.

Read the [PRD](../PRD.md) for product intent and release requirements. When a technical proposal changes product behavior, update the PRD and this pack together before accepting the change.

| Document | Purpose | Main review owner |
| --- | --- | --- |
| [Technical requirements](technical-requirements.md) | System boundaries, testable contracts, APIs, worker lifecycle, nonfunctional targets, and complete PRD traceability | Engineering lead |
| [Application flows](app-flows.md) | Navigation, screens, user actions, permissions, states, and recovery paths | Product and UX leads |
| [Design brief](design-brief.md) | Audience, visual direction, components, interaction rules, accessibility, and design handoff | Design lead |
| [Backend and data schema](backend-schema.md) | Services, entity relationships, fields, integrity rules, storage layouts, and critical transactions | Backend and platform leads |
| [Implementation plan](implementation-plan.md) | Deliverable work packages, dependencies, qualification gates, proposed staffing, and release evidence | Engineering and product leads |

## Decisions carried forward

React, TypeScript, and Vite power the browser. SwiftUI is the Mac API client. Python, Django, DRF, and ASGI form the control plane. PostgreSQL owns metadata and durable workflow state. RabbitMQ carries dispatch notifications. S3 is the artifact contract, with SeaweedFS qualification for self-hosting and managed S3 for cloud. Scrapling is the first web acquisition adapter to qualify. Docker Compose covers development and a single-server reference; Kubernetes and Helm cover the proposed multi-node production reference.

The proposed implementation begins with a modular Django application, separate platform processes, isolated execution workers, and a separate interactive inference/query runtime. Service extraction follows measured needs. Kafka is optional later scope; it is not required by this pack.

Both scratch pretraining and fine-tuning remain required for the first complete release. R1 also retains complete learned-reward RLHF, verifier-based RL, the reviewed labeling loop, text RAG, cluster exploration, Context Lab, programmatic access, export/serving, and deployment qualification. Intermediate milestones are development increments, not a reduced R1 promise. Multimodal training and advanced active-learning selection retain the status recorded in the PRD.

## Supporting contracts

- [Private AI customer discovery](../product/customer-discovery.md) provides the TASK-43 interview guide, use-case comparison rubric, pilot scope records and discovery gates. The customer evidence and use-case selection remain open.

- [Supported capability baseline and local activation measurements](supported-capabilities.md) indexes operation-specific evidence, remaining limits, and the explicit improvement-decision metric.

- [Guided local LLM fine-tuning](guided-fine-tuning.md) covers fresh accounts, ordinary training datasets and installation-managed local GPU execution.

- [Canonical sample JSON Schema](schemas/sample-envelope.schema.json) describes the shared interchange envelope. Task-specific schemas refine its content and annotations.
- [Adapter manifest JSON Schema](schemas/adapter-manifest.schema.json) describes capability and permission declarations. Qualification records determine actual support.
- [External API providers and custom plugins](external-providers-and-plugins.md) maps GPU rental, managed execution, inference, storage, and proposed extension contracts and delivery priorities.
- [Existing iterative labeling specification](../iterative-labeling.md), [RAG and context specification](../rag-context-workbench.md), and [architecture decisions](../decisions/README.md) provide the detailed domain contracts.

Requirement references use PRD IDs such as ANN04 and OPS07. Technical IDs use TECH-001 onward. Flow IDs use FLOW-01 onward. Work packages use WP-01 onward. The implementation plan links these systems together.

## Review decisions still needed

Name the reference GPU and two-node topology; select and pin training, inference, RLHF, embedding, judge, and annotation integrations; settle the Mac feature matrix; choose the identity provider and managed cloud; set retention and regional policy; assign owners and measured estimates. These decisions have assigned work packages and do not justify dropping required release paths.

- [Runpod and custom plugin setup](runpod-and-custom-plugins.md) documents opt-in provider control and trusted task execution; live provider/GPU qualification remains separate.
