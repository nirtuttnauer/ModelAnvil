# Developer and execution reference

The [project README](../../README.md) has the quickstart and capability overview. This guide keeps the detailed runtime scope, UI verification procedures and integration-test coverage available alongside the [worker and artifact contracts](worker-operations.md).

## Control plane and runtime scope

The control plane includes tenant identity/RBAC, worker job protocol with lease fencing and reconciliation, a tenant-scoped RabbitMQ worker consumer, tenant-aware artifact and dataset metadata, source snapshots with canonical sample-envelope validation, runner/adapter registries, budget reservations/usage events, a React/Vite browser shell, and a local Compose reference.

Worker fine-tuning has separate bounded CPU reference runtimes and a pinned SmolLM2-135M GPU full-SFT runtime. These load verified base weights/tokenizers and published training samples, commit fenced checkpoints and produce independently loadable candidates. The [GPU pilot](verification/task13-gpu-2026-10-11.md) covers one Apple MPS environment; other vendors and production serving need their own qualification. Alignment executes real bounded CPU character DPO, Bradley–Terry reward training, PPO RLHF and verifier RL. See the [alignment guide](cpu-character-alignment.md) for supported models, preference inputs and execution limits. Other recipes retain their recorded fixture/integration scope. Bounded local evaluation, bundle exports and simulated quantization cannot authorize production qualification or promotion. See the [capability evidence audit](capability-evidence.md) and [status ledger](status.md).

The complete R1 platform remains unfinished. Managed-S3 transfer qualification, private-worker boundaries and operational qualification remain pending. Resumable artifact upload sessions now support checksummed parts, status/resume, idempotent completion/abort, and explicit-retention cleanup; they have not yet been qualified against a managed S3 provider. Job creation writes a transactional outbox event; the Compose publisher sends persistent, confirmed notifications to RabbitMQ with at-least-once delivery semantics. Expired worker leases are reconciled by a separate periodic Compose service; `make reconcile` runs one pass locally. SQLite is the default for fast local tests; PostgreSQL, RabbitMQ, and SeaweedFS S3-compatible storage are available in Compose. Compose credentials are insecure development defaults and must be replaced for any non-local use.

Compose declares named data volumes for PostgreSQL and SeaweedFS. RabbitMQ does not declare a named data volume in `compose.yaml`; broker persistence needs a separate operational plan.

## Local setup and development identity

The local setup pins Python 3.12 and Node.js 24 (`.nvmrc` and `web/package.json` `engines`). CI verifies those same versions. `make premerge` runs the backend, frontend, and pgvector suites on them and writes the local evidence record.

The bootstrap command creates a local tenant, admin user, empty project and a development API key for optional API-key connections. The guided browser flow starts with account creation instead. Use it only in a local development database. Use Storybook for populated demo screens; create datasets and models through the app for real execution.

The API runs with `.venv/bin/python manage.py runserver`; the frontend runs with `cd web && npm ci && npm run dev`. The browser dev server proxies `/api` to `http://127.0.0.1:8000`. The README shows explicit loopback binds and separate terminals for these same services.

## Storybook and browser verification

For visual verification, run `cd web && npm run storybook` and open `http://127.0.0.1:6006`. Storybook renders the real app shell with synthetic fixtures. The Screens group has 18 numbered screens plus additional authoring stories. Its API proxy is disabled; MSW handles demo reads and writes, resets fixtures between stories, and returns HTTP 501 for missing fixtures. The mock worker is shipped only with Storybook, never with the production app.

The Screens group covers populated charts, records and inspectors. The States group adds empty, loading, error, dark and mobile examples. Each story runs browser assertions; additional action stories exercise document indexing, context authoring, CPU base initialization, suite registration, evaluation, preference registration, alignment execution and cancellation controls. Use the Accessibility panel for axe results and the viewport toolbar for responsive review. `npm run build-storybook` builds the standalone demo. `npm test` checks chart contracts and mock isolation. These checks verify UI behavior with demo responses; they do not execute model training, qualify releases or validate backend integrations.

The [backend/frontend support report](backend-frontend-support.md) documents the real authoring, CPU evaluation, accounting and artifact paths, their API contracts and the remaining executor limits.

The [frontend workspace](frontend-workspace.md) documents the browser interactions, current API boundaries, and verification commands.

## Automated checks and integration boundaries

`make premerge` runs the backend suite, the Node.js 24 frontend test, production build, and Storybook build, and the Docker `--tag=pg` suite, then writes one local evidence record. `make check`, `make test`, `make test-pg`, `make migration-check`, and `make web-build` remain available on their own. `make test` passes `--exclude-tag=pg`. `make test-pg` passes `--tag=pg` and is the required local PostgreSQL run (set `DATABASE_ENGINE=postgresql` and `RABBITMQ_URL`). A skip, xfail, or timeout at runtime fails that gate. The five optional skips recorded in the [status ledger](status.md) are `pg` tag exclusions in that PostgreSQL run, or they run only with their verified local fixture. [Local evidence records](schemas/local-evidence.v1.json) are written by `scripts/local_evidence.py` and by `make premerge`. Each record lists collected, excluded-by-tag, and passed counts for every run. `make test-broker-integration` runs the broker callback and long-running consume-loop tests against isolated PostgreSQL and RabbitMQ containers, then removes that test stack and its volumes. `make test-worker-integration` rebuilds the API image and exercises the standalone worker against the real HTTP API backed by isolated PostgreSQL. `make test-accounting-integration` covers priced usage, adjustments and concurrent callback deduplication on PostgreSQL. These targets remove their test stacks and volumes. `make smoke` exercises identity and worker protocol behavior. Managed S3, automated transfer-cleanup scheduling, distributed worker allocation, broader operational recovery, and production readiness remain unqualified.

`make isolated-eval` is the network proof for the default golden path and the PostgreSQL eval. It calls `cache_pinned_model()`, `cache_corpus()`, and `cache_rag_decoder` while the host can still reach the network, then runs `manage.py test --exclude-tag=pg` and `manage.py test --tag=pg` in a container attached only to a Compose network with `internal: true`. Postgres and RabbitMQ are on that network. `curl https://huggingface.co` from the eval container must fail. The same `--tag=pg` command with an empty cache must fail and leave that cache empty. `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` are not set for that run.

## Product and engineering plans

The authoritative product and engineering scope remains in `docs/`: see the [implementation plan](implementation-plan.md), [technical requirements](technical-requirements.md), and [backend schema](backend-schema.md).

Planning requirements describe intended scope. Runtime-specific evidence and the status ledger identify which paths have been implemented and the bounds of their verification.
