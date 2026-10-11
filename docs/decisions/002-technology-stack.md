# ModelAnvil technology stack

Architecture decision 002 | 8 October 2026 | Status: Selected planning baseline with qualification work remaining

Owner: project maintainer; implementation owners are not assigned.

We will use React and TypeScript with Vite for the browser, SwiftUI for the native Mac client, and Python with Django and Django REST framework for the application API. PostgreSQL holds metadata and durable job state. RabbitMQ dispatches work to separate CPU and GPU workers. Artifact storage uses an S3-compatible contract, with SeaweedFS to qualify for self-hosting and managed S3 for cloud deployments. Scrapling is the first web acquisition engine to qualify.

The user proposed Vite, SwiftUI, Django, PostgreSQL, MinIO, and Docker, then selected the S3 interface with SeaweedFS qualification and managed S3 after reviewing MinIO's repository status. React, REST framework, and the Kubernetes production reference are engineering recommendations in this baseline. No application or deployment has been implemented or benchmarked.

## Decision and reasons

| Layer | Baseline | Reason and boundary |
| --- | --- | --- |
| Browser | React, TypeScript, Vite | Interactive dataset, annotation, experiment, and infrastructure workspace; Vite supplies the build tooling |
| Mac | SwiftUI | Native navigation, local file access, transfers, and job monitoring through the common API |
| API | Django and Django REST framework under ASGI | Shared permission rules, relational records, migrations, admin operations, and versioned endpoints |
| Database | PostgreSQL | Transactions for job claims, leases, outbox records, metadata, and lineage |
| Retrieval | PostgreSQL full-text search and pgvector to qualify | First lexical/vector/hybrid backend; enforce access filters and compare against exact search |
| Artifacts | S3 interface; SeaweedFS and managed S3 providers | Keep storage provider choice separate from model and dataset records |
| Dispatch | RabbitMQ | Capacity-aware notifications; database state governs execution and recovery |
| Scraping | Scrapling | Reuse HTTP, browser, parsing, and crawl components behind our acquisition adapter |
| Workers | Separate Python CPU and GPU images | Keep browser and ML dependencies out of the API process and isolate resource use |
| Packaging | Docker images and Compose | Reproducible development and a documented single-server installation |
| Production cluster | Kubernetes with Helm, pending qualification | Multi-node application deployment and an execution adapter for GPU workloads |

Vite is a build tool. React supplies the UI framework, and TypeScript supplies the client types. Production serves the built assets through the deployment's ingress or static web server. The Vite development server is used during development. [Vite guide](https://vite.dev/guide/), [React guidance](https://react.dev/learn/build-a-react-app-from-scratch).

Prefer Django 5.2 LTS for the first API qualification target. Django lists extended support through April 2028, and REST framework currently lists Django 5.2 among its supported versions. Pin a supported Python version, Django patch, REST framework release, and ASGI server together before implementation. Worker images can use different qualified Python and accelerator dependencies. [Django support table](https://www.djangoproject.com/download/), [REST framework requirements](https://www.django-rest-framework.org/), [Django ASGI deployment](https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/).

## Application and client boundaries

Begin with one Django application divided into domain modules for organizations, projects, sources, datasets, annotation, experiments, evaluations, knowledge bases, retrieval pipelines, context recipes, releases, and infrastructure. Independently deploy the outbox publisher, recovery scheduler, and worker pools where their resource or availability needs differ. Split application services further only when ownership or measured scaling needs justify it.

Both clients use the same versioned API and permission rules. Publish an OpenAPI contract and validate client models against it. Browser authentication must account for CSRF and cookie policy; native authentication uses an appropriate public-client flow with secure local credential storage. The identity provider and minimum macOS version remain decisions for qualification. SwiftUI establishes the native UI choice; it does not make backend logic portable into the app. [SwiftUI documentation](https://developer.apple.com/documentation/swiftui).

Use polling for initial job progress and add authenticated server-sent events when useful. Reconnection always reconciles against durable job state. Define a Mac feature matrix before promising full browser parity. Prioritize project access, imports and exports, run submission, monitoring, and result review; advanced annotation coverage needs its own UI qualification. A local Mac training backend, including accelerator support, is a separate capability.

## Data and artifact contract

PostgreSQL stores organizations, permissions, artifact metadata, dataset manifests or manifest references, annotations, recipes, run inputs, evaluations, budgets, job attempts, and the transactional outbox. Index and constrain organization/project ownership explicitly. Every endpoint, worker action, search, export, and transfer authorization must enforce tenancy. The database choice does not supply tenant isolation automatically. [PostgreSQL version support](https://www.postgresql.org/support/versioning/).

Store original assets, large manifests, Parquet or other dataset shards, model weights, checkpoints, and log archives in object storage. Use the common S3 SDK contract with configurable endpoints and scoped credentials. Django authorizes access before issuing short-lived transfer access. Workers stream data and use bounded local scratch space; models are not loaded into API request processes. Hash artifacts and commit immutable manifests only after transfer validation. [Boto3 transfer documentation](https://docs.aws.amazon.com/boto3/latest/guide/s3.html).

The user selected SeaweedFS as the self-hosted qualification candidate and managed S3 for cloud. SeaweedFS publishes an S3 interface and an Apache 2.0 license. Test the actual operations used by ModelAnvil, including multipart upload/resume/abort, range reads, presigned requests, tenant-scoped authorization, object overwrite policy, lifecycle behavior, and recovery. API compatibility alone does not establish identical durability or access semantics across providers. The cloud vendor is still open. [SeaweedFS repository](https://github.com/seaweedfs/seaweedfs).

MinIO's community repository was archived on April 25, 2026 and states that it is no longer maintained. It is therefore not the new-installation default. Existing endpoints can be considered through the same S3 adapter and qualification suite. MinIO AIStor is a separate offering requiring its own terms and support evaluation. [MinIO repository](https://github.com/minio/minio).

## Queue and execution contract

Keep architecture decision 001's durable job record, transactional outbox, RabbitMQ delivery, atomic claim, renewable lease, fencing, and recovery contract. PostgreSQL is now the selected database for this design. Acknowledging a dispatch message records acceptance of the durable claim; it does not mean training finished. Workers admit jobs only when compatible capacity is available.

Use a Python worker supervisor with a qualified AMQP client and execution adapters. The supervisor launches a task in its declared environment and reports heartbeats and state. No additional task framework is selected here; any later framework must preserve the same claim and cancellation semantics. Hybrid workers use the outbound authenticated gateway contract instead of requiring public broker or database access.

Separate acquisition, CPU preparation, GPU training, and evaluation pools. Distributed training reserves the complete resource group through a qualified scheduler adapter. Kubernetes is the initial production deployment recommendation; Slurm can remain an execution adapter for customer GPU clusters. Kubernetes Jobs and device plugins are useful primitives, but multi-node training coordination, group allocation, checkpointing, and budget enforcement still require integration. [Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/), [GPU scheduling](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/).

The training stack remains a compatibility decision per recipe. Qualify the PRD's candidate engines for scratch training, supervised fine-tuning, DPO, reward modeling, complete learned-reward RLHF, evaluation, and serving. Pin model, tokenizer, backend, CUDA/driver where applicable, and checkpoint format. The application stack does not imply that every model or GPU combination works.

## Scrapling integration

Use Scrapling inside the acquisition worker through a versioned connector interface. Its documentation covers HTTP and browser fetching, selectors, crawl checkpoints, throttling, and streaming. The project declares a BSD 3-Clause license. Begin with HTTP; add browser fetching for sources requiring rendered content. Pin fetcher extras and browser dependencies in the acquisition image. [Scrapling introduction](https://scrapling.readthedocs.io/en/latest/index.html).

The adapter receives an authorized source specification and emits raw content, acquisition metadata, extracted records, and durable checkpoint references. Store worker-generated checkpoints privately and restore only trusted job state. Scrapling documents disk-based crawl persistence; the adapter must make it survive worker replacement. A restored crawl may repeat work, so content hashes and committed manifests handle deduplication. [Scrapling architecture](https://scrapling.readthedocs.io/en/latest/spiders/architecture.html).

Ship robots compliance enabled, bounded per-domain concurrency, crawl budgets, and retry limits. Scrapling documents `robots_txt_obey=False` as its default, so our recipe must override it explicitly. Record extraction changes and review uncertain adaptive matches instead of silently treating changed content as equivalent. Browser workers receive scoped source access and isolated network/resource policies. Publicly reachable content must pass the separate Dataset Bank license requirements before it becomes an eligible open preset. Git, dataset repositories, APIs, and object storage retain dedicated connectors. [Scrapling crawl configuration](https://scrapling.readthedocs.io/en/latest/spiders/advanced.html).

## Deployment and operations

Provide a Docker Compose package for local development and a documented single-server installation with persistent volumes. A host failure can stop that installation. Docker also offers Swarm for clustering, but supporting a second cluster orchestrator increases packaging and recovery work. Choose Kubernetes with Helm as the first multi-node production reference and revisit Swarm when a customer requirement justifies qualification. Kubernetes may use a runtime such as containerd; Docker-built OCI images do not require Docker Engine on every production node. [Compose deployment](https://docs.docker.com/compose/how-tos/production/), [Swarm](https://docs.docker.com/engine/swarm/), [Helm charts](https://helm.sh/docs/topics/charts/).

Production design must explicitly cover PostgreSQL recovery, artifact replication and backups, RabbitMQ quorum queues, persistent volumes, failure domains, migrations, and upgrades. App replicas alone do not protect stateful data. Managed database and artifact services can be outside the cluster. Native Mac builds are distributed separately and connect to a selected installation.

Collect structured logs, metrics, and traces correlated by organization, job, and attempt, without exposing private dataset content in telemetry. OpenTelemetry is the instrumentation candidate; select the monitoring backend during deployment qualification. The RAG baseline adds pgvector to PostgreSQL and uses PostgreSQL full-text search. Redis, Kafka, a separate vector database service, and a separate search cluster are not required initially. Add them when workload evidence establishes the need. [OpenTelemetry overview](https://opentelemetry.io/docs/what-is-opentelemetry/).

## RAG and context engineering extension

PRD 0.6 adds retrieval pipelines, answer evaluation, embedding exploration, and context experiments. Qualify PostgreSQL full-text search and pgvector behind the retrieval interface, including exact-search references, approximate-index/filter behavior, embedding dimensions, tenant access, and update/deletion handling. Separate high-load retrieval storage from control-plane PostgreSQL if measured contention requires it. Source content and manifests remain in S3-compatible storage. [pgvector documentation](https://github.com/pgvector/pgvector).

LlamaIndex is a candidate orchestration adapter, Sentence Transformers a candidate for embeddings and reranking, ir-measures a candidate for deterministic retrieval scoring, and Ragas a candidate for context/answer judges. ModelAnvil owns identity, versioning, jobs, and release policies. Qualify local embedding, reranking, generation, and judge models for self-hosted operation; remote services require configured egress permission. Each model has its own revision and license checks. [LlamaIndex](https://developers.llamaindex.ai/python/framework/), [Sentence Transformers](https://sbert.net/docs/sentence_transformer/usage/usage.html), [ir-measures](https://ir-measur.es/en/latest/measures.html), [Ragas](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/).

Run indexing, embedding, batch evaluation, projection, and clustering as worker jobs. Interactive query serving uses separately sized execution capacity and must not wait in the training queue. A shared context assembly stage records the exact input, block provenance, token allocation, output reserve, and memory/tool snapshots for direct model and RAG experiments. Model-serving and tool adapters remain qualified per recipe rather than prescribed by the web framework.

Qualify UMAP and PCA for saved projections, HDBSCAN or K-means for optional cluster labels, and Plotly scattergl for the first browser explorer. Record the clustering input space separately from display coordinates; use original-space neighbors and disclose sampling. Context views include token bars, block diffs, position/length heatmaps, and quality/cost comparisons. These libraries and renderers are candidates pending tests, not implemented features. [UMAP guidance](https://umap-learn.readthedocs.io/en/latest/clustering.html), [Plotly WebGL](https://plotly.com/javascript/webgl-vs-svg/).

## Qualification and revisit conditions

Before claiming support, demonstrate:

1. Browser and Mac clients use compatible API versions and enforce the same project permissions.
2. A controlled Scrapling crawl obeys limits, saves source evidence, survives worker replacement, and produces no duplicate committed records.
3. SeaweedFS and the chosen managed provider pass the artifact contract, interrupted transfer, and cross-organization access checks.
4. Duplicate dispatch, expired leases, cancellation, and a worker crash cannot publish stale outputs or silently start duplicate chargeable attempts.
5. The Compose package installs cleanly; the cluster reference survives the declared node failures and restores its stateful backups.
6. The scratch, fine-tuning, and complete RLHF recipes pass their existing PRD acceptance scenarios on named hardware.
7. The RAG/context recipe passes PRD scenarios 14–16: metric fixtures, query serving, access/deletion overlays, safe rollback, saved projections, exact context inspection, and multi-turn stress tests.

Revisit choices when a provider fails the contract, maintenance or licensing changes, supported dependencies approach end of life, or a measured workload requires another scheduler, stream system, or deployment adapter. This record affects PRJ02-PRJ03, DAT01-DAT03, BANK02-BANK07, TRN05-TRN06, ALN05, OPS01-OPS07, EXT02, and API01.
