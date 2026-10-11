# Current evidence notice

11 October 2026: the frontend supports real pinned worker training, bounded CPU character evaluation, document ingestion/retrieval, saved context compilation, durable data/annotation/job workflows and artifact-backed SPDX/export. Alignment optimization and production promotion remain unavailable. See the [backend support report](backend-frontend-support.md) and [capability evidence audit](capability-evidence.md).

# Frontend workspace

The React workspace runs through the existing Compose `web` service at
`http://localhost:5173`. Vite proxies `/api/v1/` to the API container.

Navigation uses hash routes such as `#workflows` and `#context-lab`, so reload
and browser back/forward retain the selected area. The header's Connect action
applies the edited key; Refresh reloads the current area's data and the health
probe without discarding form drafts. Changing the applied key resets the area's
state. The existing local development key behavior is retained.

## Available interactions

- Overview loads dataset, model, training, and job summaries with shortcuts.
  Counts describe the loaded page unless the API provides a total count.
- Workflows creates durable jobs with a discovered tenant worker pool, JSON payload, slots,
  accelerator, priority, and an enabled budget policy when required. Creation
  uses a stable idempotency key for retries of the same submission. Search and
  state filters operate on loaded rows and are written to the address, so a
  reload or browser back/forward restores them. Load more follows cursor
  parameters on the fixed local endpoint. Inline details show observed and
  desired state separately, payload, requirements, and attempts in the loaded
  history page. Cancellation submits the existing API action and displays its
  returned state.
- Every job, training run and evaluation row links to a durable run URL of the
  form `#runs/{job|training|evaluation}/{id}`, rendered by one run-detail view.
  That view reads the read-only `/api/v1/run-details/{kind}/{id}/` projection
  and its cursor-paged `/attempts/` history, which joins the durable job,
  worker attempts, pinned inputs, checkpoints, recorded metrics, budget
  reservations/usage, linked dataset/model/evaluation records and the recorded
  evidence level. The projection is built from stored rows only; it does not
  execute, resume or replay work. Polling is bounded (5s, backing off to 30s on
  failure, paused in background tabs, stopped on terminal state) and shows the
  time of the last successful update and any interrupted connection while
  keeping the selected run and the private recovery-note draft. Observed state,
  desired action, worker acknowledgement and job ownership (`held`, `released`,
  `lost`, `unknown`) are reported separately. Cancellation stays visibly
  requested until the backend acknowledges it, and uses the existing
  cancel actions. The view reports why a resume or retry is blocked —
  caller role, checkpoint validity against the pinned runtime contract and the
  training cursor, and budget reservation state — but offers no retry control:
  no API re-reserves budget and re-queues a job, and the accounting ledger
  refuses a second charge per job, so recovery remains the operator path
  (lease reconciliation, then a new run from the same pinned inputs).
- Annotation supports campaign setup (classification, text responses, preferences,
  and structured JSON labels), immutable schema and guidelines per campaign,
  declared protected audit IDs, bounded JSON source-batch imports, manual labels
  and imported model predictions pinned to a registered version, accept/correct/
  reject/skip decisions, review history, optimistic revision conflicts, pause/
  resume, complete-review closure, and immutable cumulative snapshot JSON export.
  Review identity comes from the authenticated principal. Closed batches cannot
  be changed through the API. Rejected/skipped labels are excluded. Identical
  imported input fields and previously used IDs cannot enter another cycle.
  Sample IDs declared as audit and samples explicitly marked protected or with
  recognized evaluation splits are rejected. This is not a source-group-aware
  reservation of all external protected datasets.
- Evaluation supports pinned-suite/candidate/baseline configuration, recorded
  slice metrics and uncertainty, case-level outputs/failures, and cursor loading.
  Suite registration saves validated immutable cases. Creating an evaluation leaves it
  pending; Execute CPU evaluation performs actual bounded character inference against
  committed, checksum-verified candidate and optional baseline artifacts.
- Alignment supports pending DPO/reward-model/PPO-RLHF/verifier-RL configurations,
  tenant-scoped model selections, separate training/validation manifest digests,
  hyperparameters, verifier specification, and recorded progress/metrics. This
  does not dispatch an executor or prove disjointness from digests alone.
- Infrastructure exposes tenant pool IDs, worker status/heartbeat/capabilities,
  and runner manifests. It never exposes worker credentials. Inventory is
  read-only; registration status alone is not a live health guarantee.
- Models supports registration, search, cursor loading, and completed evaluation
  metrics from the loaded run page, including recorded slices and uncertainty.
- Training selects tokenizer and model versions explicitly, preserves seed zero,
  configures total steps, and creates a pending run. Registry responses expose
  read-only integer `id` fields for these foreign keys; business UUIDs still
  identify resource URLs. The API validates training inputs in tenant scope.
  Existing runs show progress, loss, pinned inputs, and checkpoints.
- RAG imports pasted/local text into source revisions and builds immutable lexical
  index snapshots. Queries return real scores, spans, source IDs and content hashes.
  No external URI fetches, generated answers or embedding projections are added.
- Context Lab saves a recipe and ordered blocks atomically, then compiles immutable
  versions. JSON properties override saved block content; output includes exact prompt
  text, wrapper-inclusive token estimates, per-block allocations, omissions and
  content-cap truncation. Compilation does not execute model inference.
- Releases reads SPDX inventory, saves a protected SPDX artifact, and exports actual
  committed CPU weight bundles when available. Metadata-only candidates retain an
  explicitly unverified preview. Endpoint badges distinguish a recorded deployment from an empty
  endpoint. Creating an endpoint does not deploy a model.
- Audit lists tenant events, filters loaded rows, loads cursor pages, and expands
  recorded details.
- Dataset Bank admits budget before upstream access, downloads qualified source
  bytes through registered workers, verifies hashes, prepares and publishes revisions.
  Cancellation/resume retain consumed-record accounting and project scope. Datasets
  also retains its upload/preparation flow. Budget summaries separate units/currencies
  and preserve unpriced costs as unknown.

Training, RAG indexes, context recipes, and releases currently load the first
registry page. Worker registration/execution retains its operator entry point.
Document indexing and recipe block creation have browser authoring controls;
production deployment promotion and rollback remain gated.

## Planned surfaces still missing

Backend fixture tests and domain methods are not proof of a completed UI journey.
The following planned features remain incomplete:

- Automatic labeling inference, retraining, held-out qualification, promotion,
  rollback, source-pool selection, source-group reservations, review escalation,
  and adjudication. The UI explicitly identifies the executor gap. It does not
  call the heuristic drafter or registry-only candidate creator as real ML.
- Dedicated graphical span/rubric editors and blind randomized preference review.
  Structured JSON and explicit A/B/tie/abstain review are available.
- Organization/team/project/permission administration, storage and integration
  setup, extension installation, and full artifact/lineage navigation.
- Synthetic generation, sweep orchestration, embedding projection, model-driven
  context experiments, and production release gate/promotion/rollback flows.
- A resume/retry control in the run-detail view. The view evaluates the
  recorded blockers (role, verified checkpoint compatibility, budget state) and
  reports them, but no write path re-reserves budget and re-queues a job, so
  recovery is still an operator action. Prior attempts, checkpoints and usage
  events are append-only and stay readable in every case.

The campaign budget ceiling records configuration intent. Manual review does not
reserve executor spend; automated execution must integrate real budget policy
reservations before it is exposed as an actionable stage.

## Verification

From `web`, run `npm test` for the shared API client, dataset client, shell, and
OpenAPI checks. These tests need the repository's `contracts` directory, which
the current web-only Compose bind mount does not include. Run them from the host
checkout. `docker compose exec -T web npm run build` checks TypeScript and builds
the Docker-served frontend.

Targeted backend regression checks:

```sh
.venv/bin/python manage.py test \
  modelanvil.api.test_annotation \
  modelanvil.api.test_expanded_apis \
  modelanvil.api.test_registries \
  modelanvil.api.test_run_detail \
  modelanvil.api.test_workers \
  modelanvil.context_lab --noinput
```

Codex browser checks cover navigation/reload, job creation, model metrics,
training selectors, empty retrieval indexes, saved context compilation, live
SPDX reports, audit filtering, and the responsive shell. Queued cancellation and accepted running cancellation are covered by isolated
API tests, including release of budget reservations and worker acknowledgement.
The run-detail view is covered by `modelanvil.api.test_run_detail` (tenant
isolation, observed/desired separation, unknown and lost ownership, blocked
resume reasons, and cursor paging of long attempt histories) and by
`web/tests/run-detail.test.mjs` (deep-link round-trip, shell mounting, bounded
polling, no invented resume endpoint, narrow-width layout). These are fixture
and seam checks; no browser pilot has confirmed the run-detail journey.


Labeling browser verification uses a separate temporary SQLite database and local
API/Vite servers for sample creation, review, closure and download, so it does not
create campaigns in the Docker tenant. The Docker-served navigation, campaign
setup, evaluation details, alignment setup, and worker inventory are verified in
Codex browser. Annotation/API tests also run in the Docker API's separate
PostgreSQL test database to exercise transactional locking.

## Workspace design

The browser applies the [design brief](design-brief.md) through a shared semantic
token system in `web/src/style.css`. Light is the default; Light, Dark, and System
preferences persist locally. Dataset forms, catalog cards, release views, and
budget tables share surface, text, action, and status tokens.

Navigation groups are Workspace, Data, Develop, Context & release, and Operations.
The shell reads the actual API-key-scoped tenant name from `/api/v1/tenants/`;
the sidebar tenant display is informational. The top bar organization dropdown
lists verified connections from this browser session. Connect organization opens
a native dialog to verify another API key before changing scope. Additional keys
stay in memory; the existing active-key preference is retained. Switching uses
the selected organization’s key, resets resource views, and preserves the route. Refresh
remains available for every area. The full rail collapses to labeled icon buttons
at 1024 px and a toggleable menu at 768 px. Tables scroll inside their panels.

Overview places workflow choices and prerequisites first, followed by inventory,
actual job activity, completed evaluation evidence, and measured usage access.
Inventory identifies whether counts are totals or loaded-page counts. Completed
evaluations are not presented as qualified releases. Evaluation and usage fail
independently of the inventory request. Missing budget values appear as a dash.

Shared controls provide visible focus, a skip link that preserves the route,
text status badges, sticky table headings, reduced-motion behavior, and an
Escape-dismissable connection dialog with native focus restoration. Token
contrast checks pass 4.5:1 for tested text pairs and 3:1 for input borders in both
themes. This is not a full WCAG certification or a replacement for pilot testing.

Validation covers the TypeScript/production build, 84 existing frontend tests,
and browser checks at 1440, 1024, 768, and 390 px. Browser checks covered route
rendering, panel overflow, light/dark display, theme persistence, responsive
navigation, and connection dialog dismissal. Advanced builders, full lineage,
project switching, and release gates retain the limitations documented above.
