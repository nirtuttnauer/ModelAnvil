# ModelAnvil

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="web/public/brand/modelanvil-logo-reversed.svg">
  <source media="(prefers-color-scheme: light)" srcset="web/public/brand/modelanvil-logo.svg">
  <img src="web/public/brand/modelanvil-logo.svg" alt="ModelAnvil logo" width="420">
</picture>

[![CI](https://github.com/nirtuttnauer/ModelAnvil/actions/workflows/ci.yml/badge.svg)](https://github.com/nirtuttnauer/ModelAnvil/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A self-hosted workspace for dataset preparation, team labeling, and bounded model post-training and evaluation. A Django API records the data, runs, permissions and artifacts; a React app lets you inspect and operate those workflows.

ModelAnvil is a work in progress. Several local execution paths run real computations, while other screens and domain tests use explicit fixtures. Execution evidence, model quality, hardware support and production readiness are separate questions. The [capability ledger](docs/engineering/capability-ledger.md) is the current support surface. The [capability audit](docs/engineering/capability-evidence.md) and [status ledger](docs/engineering/status.md) keep their historical reviews.

See the [supported capability baseline](docs/engineering/supported-capabilities.md) for current operation-specific evidence and limits. Overview exposes local workflow measurements; Evaluation records explicit accept/reject decisions after verified candidate/baseline comparisons. These measurements stay in the installation and exclude prompts and credentials.

The [main integration inventory](docs/engineering/integration-inventory.md) maps all local/remote refs, retained checkouts, original uncommitted scopes and their merged deliveries or remaining holds. Current [MPS FP32 full-SFT/LoRA evidence](docs/engineering/verification/task40-current-mps-2026-10-23/report.md) covers a bounded three-step correctness/recovery check. Other GPU/runtime profiles retain separate qualification gates.

[Start locally](#local-development) · [Current capabilities](#current-capabilities) · [Architecture](#architecture) · [Checks](#checks) · [Limits and work in progress](#limits-and-work-in-progress) · [Contributing](CONTRIBUTING.md)

## Measured RAG reference

<!-- rag-results:start -->
| Measured CPU reference | Result | Scope |
| --- | --- | --- |
| MiniLM relevance nDCG@5 | 1.0000 | 20 judged queries; closed 200-document SciFact subset |
| Seeded random-vector nDCG@5 | 0.0215 | 20 judged queries; closed 200-document SciFact subset |
| Strict SQL full-text AND nDCG@5 | 0.0000 | 20 judged queries; closed 200-document SciFact subset |
| Generation conditions with accepted citations | 1/3 | No evidence / retrieved / human evidence; membership validation only |
| Known-unanswerable outcomes | 0 model abstentions, 1 policy abstentions, 1 format refusals | 2 authored cases; separate from retrieval relevance |
| Start position code-only exact match | 0.0000 (0/6) | Code-only format required; descriptive middle dip not observed |
| Middle position code-only exact match | 0.0000 (0/6) | Code-only format required; descriptive middle dip not observed |
| End position code-only exact match | 0.0000 (0/6) | Code-only format required; descriptive middle dip not observed |

Source measurement: `04916ee723f894ab0b3cec50b2ccc43596bceae0`. [Complete report and reproduction limits](docs/engineering/verification/task73-end-to-end-2026-10-23/report.md). This table is generated only from its saved JSON.
<!-- rag-results:end -->

## Current capabilities

| Area | Implemented scope | Guide |
| --- | --- | --- |
| Dataset preparation | Source snapshots, canonical sample validation, verified artifacts, protected source groups, and versioned dataset publication | [Source import](docs/engineering/source-import.md), [Dataset Bank](docs/open-dataset-bank.md) |
| Team labeling | Reviewed snapshots plus an opt-in bounded CPU retraining/evaluation cycle, explicit advance/rollback and protected-suite gates; draft predictions remain imported | [Labeling workflow](docs/iterative-labeling.md), [actual cycle evidence](docs/engineering/verification/task10-labeling-2026-10-23/report.md) |
| Post-training | Bounded CPU reference runtimes and pinned SmolLM2 GPU training profiles; committed checkpoints and candidate weight exports | [CPU runtime](docs/engineering/qualification-reports/text-finetuning-runtime.md), [GPU setup](docs/engineering/smollm2-gpu-training.md), [Apple adapters](docs/engineering/native-apple-adapter-training.md) |
| Evaluation and alignment | Versioned suites, actual bounded CPU character-model evaluation, and bounded character-model DPO, reward training, PPO and verifier-RL paths | [Backend/frontend support](docs/engineering/backend-frontend-support.md), [CPU alignment](docs/engineering/cpu-character-alignment.md) |
| Document and recipe jobs | Actual text/PDF/DOCX/CSV parsers and durable recipe/specialist control-plane jobs; current OCR/layout model qualification remains open | [Specialists](docs/engineering/local-specialists.md), [Recipes and recovery](docs/engineering/resumable-pages-and-data-recipes.md) |
| RAG, embeddings and context | Token-aware source chunks, actual pinned CPU embedding serving/builds/fine-tuning, SQL retrieval, local cited generation and measured context protocols | [Embedding indexes](docs/engineering/embedding-indexes.md), [SQL retrieval](docs/engineering/sql-retrieval.md), [grounded generation](docs/engineering/grounded-generation.md), [reproducible report](docs/engineering/verification/task73-end-to-end-2026-10-23/report.md) |
| Control plane | Tenant identity/roles, private-team invitations, current project access, worker leases/fencing, artifact integrity and budget accounting | [Worker and artifact operations](docs/engineering/worker-operations.md) |

A labeling campaign can use the opt-in bounded reviewed-label CPU training/evaluation cycle. Closing a reviewed batch queues training; **Check cycle and advance** explicitly evaluates and records promotion/rejection before the next batch. Draft predictions remain imported. The broader [iterative-labeling specification](docs/iterative-labeling.md) retains its separate general-model goals and acceptance criteria.

The [developer and execution reference](docs/engineering/development-and-evidence.md) retains the detailed control-plane contracts, runtime evidence, Storybook coverage and integration-test procedures.

GPU detection does not establish that a device can run a particular recipe. The checked-in SmolLM2 pilot covers one Apple MPS environment; CUDA, ROCm, Intel XPU and other configurations need their own qualification. The native Apple adapter report also records a bounded candidate's quality failure. Training completion alone does not authorize production promotion.

## Guided fine-tuning

New users can create an account and use **Training → Model → Dataset → Review → Train**. The guided path prepares pretrained SmolLM2-135M and its local execution resources automatically, accepts ordinary chat JSONL and prompt/response CSV, and provides progress, a trained-model download and a chat link.

For the installation owner, start the API and managed training service together with `.venv-gpu/bin/python manage.py run_local` in the installed GPU environment, then start the existing web development server. Users need only the browser. See the [guided local fine-tuning guide](docs/engineering/guided-fine-tuning.md) for setup, account behavior, supported input limits and verification.

## Guided fine-tuning

New users can create an account and use **Training → Model → Dataset → Review → Train → Evaluate against base**. The guided classification path prepares the supported SmolLM2-1.7B Apple adapter and local execution resources automatically, accepts ordinary chat JSONL and prompt/response CSV, and provides progress, a protected comparison, an explicit decision and a reviewed export. A classification starter explains source groups and separate train/validation/test splits. The existing bounded 135M and CPU profiles remain available through their supported paths.

For the installation owner, start the API and managed training service together with `.venv-gpu/bin/python manage.py run_local` in the installed GPU environment, then start the existing web development server. Users need only the browser. See the [guided local fine-tuning guide](docs/engineering/guided-fine-tuning.md) for setup, account behavior, supported input limits and verification.

## Local development

Use Python 3.12, Node.js 24 and npm to match CI. Docker with Compose is optional for the local SQLite setup and required for the multi-service reference and container integration checks. Model execution needs the optional dependencies and hardware described by its runtime guide; installing the control plane does not provision a training worker or download model weights.

From a new checkout:

```sh
git clone https://github.com/nirtuttnauer/ModelAnvil.git
cd ModelAnvil
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make migrate
.venv/bin/python manage.py bootstrap_dev
make check
```

`bootstrap_dev` creates a local tenant, an admin user, an empty project and a development API key for optional API-key connections. The guided browser flow starts with account creation instead. Run bootstrap only against a local development database; its shared defaults are deliberately insecure for public hosting. It does not create datasets, trained models or execution evidence. Use Storybook for populated demo screens.

Start the API in one terminal, from the repository root:

```sh
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

In another terminal, also from the repository root:

```sh
npm --prefix web ci
npm --prefix web run dev -- --host 127.0.0.1
```

Open [localhost:5173](http://localhost:5173) and create an account for the browser workflow. Vite proxies `/api` to the local Django server. The unauthenticated health endpoint is available while the API is running:

```sh
curl --fail http://127.0.0.1:8000/api/v1/health/
```

### Development-only container

The root [Dockerfile](Dockerfile) is a development-only image. It installs the base requirements, applies migrations, runs `bootstrap_dev`, and serves the API with Django's `runserver` on `0.0.0.0`. Those defaults are for local development and are not a production deployment. Production uses [deploy/production/Dockerfile](deploy/production/Dockerfile). Self-hosting uses [deploy/selfhost/Dockerfile](deploy/selfhost/Dockerfile). Both of those stacks require real secrets.

SQLite is the local default. `DATABASE_ENGINE`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST` and `DATABASE_PORT` select a PostgreSQL connection; `MODELANVIL_ARTIFACT_ROOT` selects local artifact storage. Configuration is read in [settings.py](modelanvil/settings.py). Keep credentials and private data out of source control.

### Explore the UI with fixtures

```sh
npm --prefix web run storybook
```

Open [localhost:6006](http://localhost:6006). Storybook uses the real components with synthetic API fixtures, including populated, empty, error, dark and mobile states. Its mock API resets between stories and is separate from the application backend. Story assertions verify UI behavior; their charts and outcomes are demo data. `npm --prefix web run build-storybook` builds the standalone demo.

For the Screens/States groups, action-story coverage, MSW behavior, axe checks and viewport tools, see [Storybook and browser verification](docs/engineering/development-and-evidence.md#storybook-and-browser-verification). For API-backed interactions and their current limits, see the [frontend workspace guide](docs/engineering/frontend-workspace.md).

## Architecture

The control plane includes tenant identity/RBAC, worker job protocol with lease fencing and reconciliation, a tenant-scoped RabbitMQ worker consumer, tenant-aware artifact and dataset metadata, source snapshots with canonical sample-envelope validation, runner/adapter registries, budget reservations/usage events, a React/Vite browser shell, and a local Compose reference.

```mermaid
flowchart LR
    Browser[React workspace] --> API[Django and DRF API]
    API --> DB[(SQLite locally / PostgreSQL in Compose)]
    API --> Artifacts[Filesystem or S3-compatible artifacts]
    DB --> Outbox[Transactional outbox publisher]
    Outbox --> Broker[RabbitMQ dispatch]
    Broker --> Worker[Trusted compatible worker]
    Worker -->|Claim, heartbeat, fenced result| API
    Worker -->|Verified inputs and outputs| Artifacts
```

The database owns workflow state. Broker notifications can be delivered more than once; workers still need a valid durable claim to publish results. A separate reconciler handles expired leases. Direct database polling and an outbound HTTP worker are also implemented; their credential, cancellation and transfer boundaries are documented in [worker operations](docs/engineering/worker-operations.md).

| Location | Responsibility |
| --- | --- |
| `modelanvil/api/` | REST contracts and workspace actions |
| `modelanvil/data/`, `modelanvil/annotation/` | Source preparation, recipes and human review |
| `modelanvil/runners/` | Runtime contracts, training, evaluation and inference |
| `modelanvil/jobs/`, `modelanvil/artifacts/`, `modelanvil/budgets/` | Durable execution, stored artifacts and accounting |
| `web/` | React app, API clients, Storybook and frontend tests |
| `contracts/`, `docs/engineering/` | Schemas, implementation guides and dated evidence |

### Compose reference

```sh
docker compose -f compose.yaml up --build
```

This starts the development browser at `http://localhost:5173`, the API at `http://localhost:8000` and the SeaweedFS S3 endpoint at `http://localhost:8333`, alongside PostgreSQL, RabbitMQ, the outbox publisher and the lease reconciler. The database and object store use named volumes. `docker compose -f compose.yaml down` stops the stack; adding `-v` deletes its persisted volumes.

The Compose reference uses development credentials and Django's development server. Keep it local. TLS, production secrets, backups and availability need an operator's deployment design. Managed S3 behavior and broader operational readiness remain unqualified.

### Worker and transfer reference

<a id="controlled-local-executor"></a>
<a id="worker-credentials"></a>
<a id="outbound-http-worker"></a>
<a id="result-egress-boundary"></a>
<a id="attempt-scoped-input-artifact-downloads"></a>
<a id="resumable-artifact-uploads"></a>

Read the preserved contracts for [local executors](docs/engineering/worker-operations.md#controlled-local-executor), [worker credentials](docs/engineering/worker-operations.md#worker-credentials), [outbound HTTP workers](docs/engineering/worker-operations.md#outbound-http-worker), [result-egress restrictions](docs/engineering/worker-operations.md#result-egress-boundary), [attempt-scoped downloads](docs/engineering/worker-operations.md#attempt-scoped-input-artifact-downloads), and [resumable uploads](docs/engineering/worker-operations.md#resumable-artifact-uploads).

## External compute and custom plugins

The [Runpod and custom plugin guide](docs/engineering/runpod-and-custom-plugins.md) covers REST v2 GPU discovery, tenant-scoped allocation/worker bootstrap, verified release, expiry reconciliation, and trusted operator-installed compute and task plugins. Configure provider accounts outside the browser and run `manage.py reconcile_compute --loop` for automatic expiry cleanup. The [provider TODO](docs/engineering/provider-integration-todo.md) tracks the remaining integrations and live qualification. Remote training runtimes and managed artifact transfer require their own qualification.


## Checks

From the repository root, with the Python environment installed:

```sh
make premerge
make check migration-check smoke
make test
npm --prefix web ci
npm --prefix web test
npm --prefix web run build
npm --prefix web run build-storybook
```

`make premerge` is the local pre-merge command. It requires Python 3.12 and Node.js 24 (`.nvmrc` and `web/package.json` `engines`). On any other Node version, including Node.js 20, it exits immediately and names the version it found. It then runs the backend suite with `--exclude-tag=pg`, `npm test`, the production build, the Storybook build, and `manage.py test --tag=pg` against Docker images `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine` (the same images as `.github/workflows/ci.yml`). A failure, skip, expected failure, or timeout exits non-zero. A clean run from an empty `git status` writes one ANVIL-002 record labeled `local`. The three jobs in `.github/workflows/ci.yml` stay as they are. Branch protection remains the repository owner's optional setting.

CI uses Python 3.12 and Node.js 24. It also checks fresh migrations/bootstrap and runs the backend suite against file-backed SQLite. To use a file-backed test database locally, set `DATABASE_TEST_NAME` to a separate temporary SQLite path before `make test`; Django manages that test database independently of your development data.

The optional `make test-broker-integration`, `make test-accounting-integration`, `make test-worker-integration` and `make test-dataset-integration` targets start isolated Docker projects and remove their test stacks and volumes. They check specific PostgreSQL, broker or HTTP paths. The [test-target reference](docs/engineering/development-and-evidence.md#automated-checks-and-integration-boundaries) preserves each target's precise coverage, including broker callbacks, worker HTTP paths and concurrent accounting. None substitutes for model-quality evaluation, managed-storage qualification or production operations testing. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Production deployment

The [production deployment runbook](deploy/production/README.md) covers the separate
Gunicorn, PostgreSQL and Caddy stack, explicit migrations, HTTPS verification,
backups and rollback. Run `make test-production` to build and exercise an isolated
HTTPS deployment, including authentication and restart persistence. The test
removes only its own containers and volumes. Hosted worker execution, account
invitations, billing and recovery qualification remain separate SaaS milestones.

## Limits and work in progress

- Runtime contracts impose model, input, sequence, step and memory limits. The supported local profiles and their measured envelopes are narrower than the full product plan.
- Some domain workflows, quantization paths and evaluation fallbacks use simulation. Read the recorded execution origin before interpreting a result.
- Automatic label-review/retraining cycles, broad GPU qualification, distributed allocation, managed-S3 qualification and a complete private-worker gateway remain open work.
- Production qualification and live promotion remain unavailable through unverified execution paths. Operator-installed executor code is trusted code; the worker protocol does not sandbox it.

The [catalog additions (#10)](https://github.com/nirtuttnauer/ModelAnvil/pull/10), [guided training and reviewed releases (#11)](https://github.com/nirtuttnauer/ModelAnvil/pull/11), and [production packaging (#12)](https://github.com/nirtuttnauer/ModelAnvil/pull/12) were integrated into `main` on 21 October 2026. Their guides record the supported paths and remaining qualification limits.

<a id="planning-documents"></a>

The [engineering planning pack](docs/engineering/README.md) and [implementation plan](docs/engineering/implementation-plan.md) describe proposed scope. Use the capability guides and dated evidence for implemented behavior. [Open issues](https://github.com/nirtuttnauer/ModelAnvil/issues) and [pull requests](https://github.com/nirtuttnauer/ModelAnvil/pulls) track ongoing work.

## License and contributions

ModelAnvil is released under the [MIT license](LICENSE). Model weights, datasets and third-party packages retain their own licenses. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks and pull request guidance.
