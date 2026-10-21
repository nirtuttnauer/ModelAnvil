# P0 implementation progress

12 October 2026. This follows the [implementation backlog](../product-implementation-backlog.md) in dependency order. The requested delivery scope is **all local**. Production qualification remains unavailable.

| Task | Local implementation | Evidence / boundary |
| --- | --- | --- |
| PM001 Compute setup | Administrator registration for shipped CPU character, CPU transformer, model acquisition, CPU evaluation, Dataset Bank acquisition and CPU data recipe profiles; one-time masked credential, startup command, heartbeat, reconnect and revocation | Real worker execution and browser setup passed. Trusted service environment with shared database/artifact access; no remote gateway claim |
| PM002 Budget management | Administrator quantity-policy editor; settled/reserved/remaining allowance; protected edits; enabled compatible selectors for training and evaluation | SQLite/API/browser checks and 17 PostgreSQL accounting/concurrency tests passed. No invented monetary prices |
| PM003 Executable model compatibility | Verified input eligibility, supported recipes/devices/limits, CPU transformer initialization, acquisition-worker setup and compatible Chat selection | Actual imported tiny Safetensors inference and worker publication passed; CPU candidate Chat passed. Live Hub transfer was not exercised |
| PM004 Actionable onboarding | Setup links, accurate evidence labels, exact run links, readiness across all pages of prerequisites, and project scope established before page loads | Fresh-project packaged browser reached seven prerequisites and approved preflight. Keyboard preflight passed in 8.3 seconds with 330 Tab movements; modal IDs and team-loading races corrected |
| PM005 Durable transformer evaluation | Frozen candidate/baseline/suite/scorer/tokenizer/runtime/decoding pins; known training-source overlap rejection; fenced case commits, progress, cancellation, recovery and case accounting | Actual trained transformer and baseline executed. Partial cases cannot pass a complete evaluation; interruption/replay did not duplicate cases or charges. Legacy character execution retained |
| PM006 Candidate review and export | Browser-created immutable review, exact evaluation/provenance/license record, thresholds and failures; authenticated archive with actual weights, configuration, tokenizer, manifests, notices and standalone consumer | A failing quality review remained failing. Clean consumer matched the frozen output and checksum; local review never sets production qualification |
| PM009 Packaged local journey | Build revision/API source digest/protocol/import capability display; complete fresh-project data → training → Chat → evaluation → review → download journey | Packaged browser completed in 44 seconds, committed two actual steps, retained a failed case, survived reload and passed a 390-pixel layout check |
| PM007 Local serving lifecycle | Authenticated on-demand CPU serving in the application process; actual startup probe before activation; retained failures, previous pointer preservation, current access/byte checks and reprobed rollback | Live browser serving passed. Tests cover startup failure, rollback failure, runtime drift, permissions and component tombstones. Production serving gate remains deferred |
| PM008 Local installation and recovery | Serialized SQLite write transactions; actual isolated database/artifact restore drill; clean temporary environment installation using base dependencies | Fresh database migrated and CPU training/evaluation/export/serving tests passed. Restore verified artifacts, accessible reviews, endpoint loading and ledger consistency. Production TLS, broker/provider and distributed recovery qualification remain deferred |

## Start local compute

In Infrastructure, choose **Register local worker**. Run the displayed command in the application's trusted service environment, using the same database and artifact storage:

```sh
python manage.py run_worker --worker-id WORKER_ID --profile cpu-transformer
```

The command asks for its scoped credential at a hidden prompt; `MODELANVIL_WORKER_TOKEN` is an operator-provisioned alternative. Credentials never appear in startup commands, inventory, browser preferences or audit snapshots. Registration is `Cache-Control: no-store`; dismissal/navigation clears the displayed credential. An administrator can revoke it.

New setup workers require an observed heartbeat within 60 seconds and an active credential. Registration alone does not report compute readiness. Existing operator registrations retain their prior admission contract. CPU evaluation uses `--profile cpu-evaluation`; model acquisition uses `--profile model-import` and requires optional runtime packages.

Budgets supports `training_steps`, `evaluation_cases` and `bank_acquisition_records` quantity policies. Limits must be positive; policies with reservations retain their period, unit and currency. Editing a limit uses the same lock as admission and cannot reduce it below current commitments. Costs remain unpriced unless rates were recorded.

## Evaluation and reviewed release

Register a suite in Evaluation, select the exact candidate and its pinned baseline, then select an evaluation worker pool and case budget. Queueing freezes inputs, reserves one unit per suite case and exposes progress/cancel through Run Detail. Known source/sample/prompt overlap blocks allocation; unknown external training history is not certified clean.

In Releases, **New candidate release** freezes a completed worker candidate and a complete durable evaluation. The review shows required thresholds, actual measurements, baseline regression, recorded license and training provenance. Another candidate's evaluation cannot satisfy it. A changed review creates a new revision; an identical uncertain retry returns the same revision.

The reviewed archive includes `model.safetensors`, configuration/tokenizer, hashes, provenance, notices, the frozen review and `infer.py`. Its independent consumer uses the standard library:

```sh
python -I infer.py . --prompt x --max-tokens 2
```

Only an approved local review can deploy locally. A deployment runs a real inference probe before switching the endpoint. Failed attempts remain in history; failure preserves the prior active deployment. **Check live health**, **Test authenticated inference** and **Rollback locally** use current permissions and verified bytes. Startup readiness is a recorded probe, not continuous uptime monitoring.

The serving pilot used an explicitly declared accuracy threshold of zero to test infrastructure. The original review at 0.8 retained its measured failure; no model quality or production claim follows from the infrastructure test.

## Reproduce a local restore drill

Use an isolated SQLite database and filesystem artifact store. The destination must not exist; the source is never mutated, no worker is launched and no external provider is contacted:

```sh
python scripts/local_restore_drill.py \
  --database /absolute/path/local.db \
  --artifacts /absolute/path/artifacts \
  --destination /absolute/path/new-restore-directory
```

The drill creates a real SQLite backup, copies artifact bytes, checks database integrity and committed artifact checksums, opens authorized release records, loads reviewed exports and reopens local serving. It replays terminal completion attempts and verifies unchanged usage/reservations. Unknown running ownership and queued jobs remain explicitly reported; they are never silently executed.

## Verification and support envelope

The complete backend regression finished **766 tests with eight skips and no failures** after the SQLite transaction change. A subsequent tombstone-serving check passed the four local serving tests. Keyboard onboarding completed with native keyboard controls and a controlled file input. The frontend suite passed **143 tests**; TypeScript/Vite build, Django checks and migration-drift checks passed. The existing bundle-size warning remains.

An isolated PostgreSQL accounting run passed 17 tests, including concurrent admission/settlement. A clean temporary virtual environment installed `requirements.txt`, migrated a fresh database and passed 13 actual CPU training/evaluation/review/export/serving tests in approximately 26 seconds. Optional Hub/GPU/specialist packages were excluded from that install.

The local restore drill verified 49 artifacts, three accessible reviewed releases, one reloaded endpoint and 12 refused duplicate completions, with unchanged usage and reservations and no unresolved running ownership. Its queued job remained queued. The packaged export's independent consumer produced token IDs `[36, 36]`, matching the frozen case output and weights checksum.

Tests use temporary projects, databases and artifact directories. The workspace's existing SQLite database was backed up privately before applying its pending compatible migrations; existing resources were retained. No existing workspace compute was launched.

Qualified evidence here is limited to a single local POSIX application service, CPU reference models, trusted database-polling workers and filesystem storage on the tested Mac environment. It does not establish TLS/production-server deployment, broker recovery, remote/distributed workers, cloud storage, production throughput or hardware qualification. Original production acceptance criteria for PM007/PM008 remain deferred under the user's local-only instruction.

Sanitized reports are in [verification/p0-local](verification/p0-local/). Older unrelated qualifications and completed task mappings are preserved.

Dataset Bank acquisition uses `--profile dataset-bank`; deterministic CPU recipes use `--profile cpu-recipes`. Both can be provisioned through Infrastructure and require an active envelope pool. Observed local workers cannot admit new bank, recipe or specialist jobs when stale or draining.
