# Packaged self-hosted install

Scope and plan for the packaged install. Written against `main` `4dd5060e632bae598003bf3a51a474709fe8c7ac` on 11 November 2026.

This document records what is in the tree and splits the remaining work into ANVIL-024, ANVIL-025, ANVIL-026, ANVIL-027, and ANVIL-028. Each child is limited to the files and commands listed under it. That limit is what keeps the child inside two days. This pull request does not add the version file, the install script, the drills, the customer page, or a published tag.

The installation path named in [self-host.md](self-host.md) is the provisioned Linux arm64 Docker package in [deploy/selfhost](../../deploy/selfhost/README.md). `deploy/helm` is unsupported. See [deploy/helm/README.md](../../deploy/helm/README.md).

## What is in the tree

### `deploy/selfhost`

The controller is `deploy/selfhost/modelanvil.py`. Its subcommands are `install`, `initialize`, `start`, `stop`, `status`, `diagnostics`, `backup`, `uninstall`, `example`, `import-reference`, `upgrade`, and `restore`. There is no `rollback` subcommand.

`install` copies a verified release into a new directory, loads the release's local images, and initializes an empty workspace. It refuses an existing directory. `backup` stops `web`, `api`, `worker`, and `reconciler`, requires a queue with no `queued`, `running`, or `interrupted` job, and writes `database.dump`, `artifacts.tar`, `.env`, `instance.json`, and `backup.json` into a new directory. `upgrade` refuses a release whose version equals the installed version, keeps the previous release under `release-history/`, takes that backup with restart left off, runs `migrate`, and starts the instance. `restore` requires a new directory and a backup whose `release` field equals the release manifest version. It loads the dump and the artifact archive, runs `migrate`, and starts a new Compose project. It does not write into an existing instance.

A release directory must contain `modelanvil.py`, `compose.yaml`, `reference.json`, `README.md`, `LICENSE`, `requirements.selfhost.lock.txt`, `images.tar`, and `release.json`. `release()` checks `schema_version` `modelanvil.selfhost-release.v1`, the file set, sha256 image ids for `api`, `web`, and `db`, and the version regex `[a-z0-9][a-z0-9.-]{0,79}`.

`scripts/build_selfhost_release.py` builds that directory. It takes `--output` and an optional `--version`. With `--version` omitted, the version is `cpu-` plus the leading 12 hex characters of `HEAD`. It refuses a dirty worktree, an existing output directory, a Docker engine that is not Linux arm64, and an image tag that already exists (`modelanvil-selfhost-api:<version>` and `modelanvil-selfhost-web:<version>`). The manifest field `production_qualified` is `false`. `diagnostics()` also reports `production_qualified: false`.

`scripts/qualify_selfhost.py` runs `install`, the example import, a four-step `full_sft` recipe, `backup`, `restore`, optional `upgrade` when `--upgrade-release` is set, `uninstall`, and `start` on synthetic projects. Its proof sets `production_qualified` to `false`. The qualification scope string in that script names a small numerical CPU reference pipeline and a local-CA Docker package, and it states that the run does not cover a physical second host, public DNS, ACME, or native signing. The measured record is [self-host.md](self-host.md), dated 24 October 2026, on one Apple M5 Pro with a Linux arm64 Docker engine.

The package guide is [deploy/selfhost/README.md](../../deploy/selfhost/README.md). It documents the same controller commands, loopback bind by default, a local CA, and the upgrade rule that a failed schema change is handled by diagnosis or by an isolated restore of the matching old release. Code rollback does not reverse database migrations.

No file in the repository stores a self-host package version. `git tag -l` on this `main` lists `ui/phase-0`, `ui/phase-0-base`, and `ui/phase-1` through `ui/phase-5`.

### `deploy/production`

[deploy/production/README.md](../../deploy/production/README.md) is a Compose procedure for one Docker host: PostgreSQL, Gunicorn, and Caddy, with the API and the compiled frontend. `deploy/production/compose.yaml` defines `db`, `migrate`, `api`, and `web`. It does not define a worker. The image tag is `MODELANVIL_IMAGE_TAG` in an untracked `.env`. The README's start, backup, upgrade, and rollback text is a sequence of shell commands. Backup is `pg_dump` plus a tar of `/app/storage/artifacts` after `web` and `api` are stopped. Rollback, when the previous code supports the migrated schema, is `docker compose up` of the retained image tag without `--build`. An incompatible migration is a restore of the paired backup into a separate stack.

`make test-production` runs `scripts/production_integration.py`. `scripts/production_smoke.py` checks one deployed origin. `scripts/rehearse_restore_copy.py` copies a directory and checks file hashes. Its report field `production_qualified` is `false`.

[installation-qualification.md](installation-qualification.md) (28 October 2026) lists gates that are still open: an off-host restore of PostgreSQL plus artifacts checked against a real trained release; a worker on the production host; an upgrade and rollback rehearsal that does not rebuild the old image tag; a clean external consumer of a guided export; a recovery-time or recovery-point claim. Those gates stay open in this plan.

### `deploy/helm`

`deploy/helm` contains `Chart.yaml`, `values.yaml`, `templates/api-deployment.yaml`, and `templates/worker-deployment.yaml`. `Chart.yaml` says `version: 0.1.0` and `appVersion: "1.0.0"`. The description string in `Chart.yaml` is unchanged by this plan and is not a support statement. `values.yaml` sets `replicaCount: 2`, image `modelanvil/control-plane:1.0.0`, `ingress.enabled: true`, `postgresql.enabled: false`, and `rabbitmq.enabled: false`. The templates directory has no Ingress manifest. The API template and the worker template both use that same image. The worker command is `python manage.py run_executor`. Nothing in this directory builds or publishes `modelanvil/control-plane`.

The chart is unsupported. ANVIL-024 through ANVIL-028 do not edit it, do not install it, and do not describe it as a supported path.

These files still mention Kubernetes or Helm as a multi-node reference. This ticket does not edit them:

- `docs/PRD.md`
- `docs/ROADMAP.md`
- `docs/compatibility-matrix.md`
- `docs/decisions/002-technology-stack.md`
- `docs/engineering/README.md`
- `docs/engineering/technical-requirements.md`
- `docs/engineering/implementation-plan.md`

## Children

Shared limits for every child:

- Leave `production_qualified` false in the builder, the controller diagnostics, and the qualification proof.
- Do not add a controller subcommand, a Compose service, an image, or an architecture.
- Do not edit `README.md`, anything under `web/`, `requirements.documents.txt`, the gitleaks configuration, or `.github/workflows/ci.yml`.
- Do not edit `deploy/helm`.
- Do not create a git tag, a GitHub release, or a published image. Publishing is ANVIL-028 and it needs Nir.
- Public DNS and ACME stay outside the package, as [self-host.md](self-host.md) already states.
- The builder's Linux arm64 check stays in place. The controller already refuses to emulate a different architecture.

### ANVIL-024 — Version file

Add `deploy/selfhost/VERSION`, one line, matching the regex already enforced by `scripts/build_selfhost_release.py` and by `release()`. When `--version` is omitted, the builder reads that file. When `--version` is passed, that argument still wins. Keep the refusals for a dirty worktree, an existing output directory, a non-arm64 engine, and an existing image tag.

Tests cover the file read and those refusals on paths that do not build images. Do not run the image build on a non-arm64 host. Do not run `git tag`.

Files: `deploy/selfhost/VERSION`, `scripts/build_selfhost_release.py`, and a test next to the existing installer tests in `modelanvil/core/test_selfhost.py`.

### ANVIL-025 — One install script

Add `scripts/install_selfhost.py`. It accepts `--directory`, `--release`, and the install flags the controller already accepts (`--host`, `--bind`, `--http-port`, `--https-port`, `--credentials-stdin`). It executes `<release>/modelanvil.py` with those arguments. The release copy of the controller remains the installer. The script does not build images, does not pull images, and does not call `deploy/production`.

Tests, without Docker, check a missing release directory and check that the argument list passed to the controller matches the flags above.

Files: `scripts/install_selfhost.py` and `scripts/test_install_selfhost.py`.

### ANVIL-026 — Backup, upgrade, and rollback drills

Add `docs/engineering/self-host-drills.md` and `scripts/drill_selfhost.py`.

The drill calls the existing controller, in this order, on directories the operator passes:

1. `backup` of the installed directory into a new backup directory.
2. `upgrade` with a second verified release and a second new backup directory. `upgrade` already takes its own backup before it swaps the release.
3. Rollback is `restore` of the backup directory passed to `upgrade`, using the previous release, into a new directory. `restore` accepts that pair because the backup records the previous version. There is no in-place rollback, and this drill does not add one. It does not reverse a migration inside the upgraded directory.

`scripts/qualify_selfhost.py` already runs backup, restore, and optional upgrade on synthetic projects. The drill script is the operator entry for the three steps above. It does not grow a second lifecycle.

Unit tests mock the controller process. A live run needs two Linux arm64 releases built by `scripts/build_selfhost_release.py`. On any other engine, the child records that the live drill did not run. It does not build a release there, and it does not mark the open rehearsal in [installation-qualification.md](installation-qualification.md) as done.

Files: `docs/engineering/self-host-drills.md`, `scripts/drill_selfhost.py`, and `scripts/test_drill_selfhost.py`.

### ANVIL-027 — Customer page

Add `docs/self-host-install.md`. Source it from the commands and limits already written in [deploy/selfhost/README.md](../../deploy/selfhost/README.md) and from the version, script, and drill landed by ANVIL-024, ANVIL-025, and ANVIL-026. State that `deploy/helm` is unsupported and link [deploy/helm/README.md](../../deploy/helm/README.md). State that the release manifest sets `production_qualified` to false. State that `deploy/production` is a separate Compose procedure and that `scripts/install_selfhost.py` does not call it.

Do not edit `docs/engineering/self-host.md` or `README.md`. Do not add a command the controller does not already implement.

Files: `docs/self-host-install.md`.

### ANVIL-028 — Publishing and a second-machine install

This child needs Nir. An agent stops when the tag, the Linux arm64 build host, or the second machine is missing, and says so in the pull request.

Nir tags the version in `deploy/selfhost/VERSION` and builds it with `scripts/build_selfhost_release.py` on a Linux arm64 Docker engine. The second machine is a second Linux arm64 host, distinct from the Apple M5 Pro host recorded on 24 October 2026. On that host, run `scripts/install_selfhost.py` against the tagged release, then run `scripts/drill_selfhost.py`. Record the commands, the exit codes, and the release version under `docs/engineering/verification/`. Leave `production_qualified` false. Do not configure public DNS or ACME. Do not emulate another architecture. Do not publish a registry image from an agent session.

## Out of scope

ANVIL-024 through ANVIL-028 do not port the package to amd64 or Windows, do not add a GPU worker to the package, and do not sign or notarize the macOS or Linux launchers. Those limits are already stated in [deploy/selfhost/README.md](../../deploy/selfhost/README.md) and in [self-host.md](self-host.md).
