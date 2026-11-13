# Self-host install, upgrade, backup and restore

This page is for an operator who wants to run ModelAnvil on a machine they control. It covers the offline self-host package in [deploy/selfhost](../deploy/selfhost/README.md): getting a release, installing it, checking it, everyday commands, backup, upgrade, rollback, uninstall and restore on another machine.

## What you get

The package installs a private ModelAnvil workspace on one Docker engine: the web app over HTTPS with its own local certificate authority, the API, a PostgreSQL database, artifact storage and one CPU worker. It runs offline. By default it listens only on `127.0.0.1`. It does not download models and does not create development accounts.

Each release includes one small numerical reference model and one training recipe, `full_sft`. The model is a randomly initialized transformer with 2,424 parameters, not a pretrained language model. It shows that installation, data, training and inference work. It says nothing about language quality.

- The package's worker trains and serves on CPU only. There is no GPU worker in the package.
- Across ModelAnvil, CPU training and inference, and training with MPS on one Apple silicon Mac, are recorded at the integrated-execution level: the code ran end to end on that hardware in small, bounded checks. CUDA training code is in the repository, but no CUDA run has been verified.
- `release.json`, the manifest in every release, sets the field `production_qualified` to `false`. The install, `start`, `status` and `diagnostics` results report the same field with the same value. The package comes with no support, uptime, recovery-time or recovery-point commitment.
- There is no published release, git tag or registry image yet. You build the release yourself, as [Get a release](#get-a-release) describes.

[Limits](#limits) lists the rest.

## How to read this page

The sections run in order as one walk-through: install release 0.1.0, back up, rehearse an upgrade to 0.1.1 on a copy, upgrade, roll back, uninstall, and restore on a second machine. Skip the sections you do not need. [Roll back](#roll-back), for example, is only for an upgrade you want to undo.

Every command uses example values, so it can be run exactly as written. Replace a value with your own where this table says so, and use the same replacement in every later command.

| Example value | What it is | Replace with |
|---|---|---|
| `~/src/ModelAnvil` | The source checkout. It holds the build, install and drill scripts. | Any directory. |
| `~/modelanvil-releases/0.1.0`, `~/modelanvil-releases/0.1.1` | Release directories, named after the version the builder reports. | The versions you built. |
| `~/modelanvil` | The instance directory: private settings, secrets and the installed copy of the release. | Any new directory. |
| `~/modelanvil-backups/before-upgrade`, `~/modelanvil-backups/upgrade-to-0.1.1` | Backup directories. Every backup needs a new one. | New directories, ideally on another disk. |
| `~/modelanvil-rehearsal`, `~/modelanvil-rehearsal-drill`, `~/modelanvil-rollback` | Directories that the rehearsal and the rollback create. | New directories. |
| Ports 8080 and 8443 | The controller's default HTTP and HTTPS ports. | Unused ports from 1024 to 65535. |
| Ports 18080/18443 and 28080/28443 | Ports for the rehearsal copies, which run next to your instance. | Other unused ports. |

Run the commands as the user who owns these directories. Run one controller command at a time for a given instance.

## Requirements

On the machine you install on:

- A local Linux arm64 Docker engine, reached through a Unix socket, with Docker Compose v2 or later. Docker Desktop on an Apple silicon Mac and Docker Engine on a Linux arm64 host both provide one. The controller refuses other architectures, Windows, emulation and a remote Docker context.
- At least 4 GiB of memory assigned to Docker. The controller refuses less. In a [measurement on 12 November 2026](engineering/verification/anvil-029-2026-11-12/report.md), one instance used at most 1.24 GiB (`docker stats`) while it trained the example, and the engine and all its containers together used at most 0.76 GiB of memory other than page cache. The Compose file caps the services at 3.75 GiB together: the API, the worker and the reconciler at 1 GiB each, PostgreSQL at 512 MiB and Caddy at 256 MiB.
- Disk for each release you keep, in three places: the release directory (334 MiB, almost all of it `images.tar`), its copy in the instance directory, and the images loaded into Docker. In the [walk-through record](engineering/verification/anvil-027-2026-11-12/report.md), release 0.1.0's images took 1.48 GB in Docker, and release 0.1.1 added about 25 MB because the two share most image layers. Each upgrade keeps the previous release under the instance directory, which held 667 MiB after one upgrade. The volumes of an instance with only the example model took about 60 MB, and each backup of it was under 1 MiB. Add room for your own data and backups.
- Python 3.9 or later for the controller and the scripts. They use the standard library only.
- `curl` for the health checks and `git` for the source checkout.

Install missing tools with your system's package manager. On Alpine Linux, for example: `apk add python3 curl git`. On Debian or Ubuntu: `sudo apt-get install python3 curl git`.

Check the engine and Python:

```sh
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
docker compose version
docker info --format '{{.MemTotal}}'
python3 --version
```

You need `linux/arm64`, Compose version 2 or later, a memory total of at least 4294967296 bytes, and Python 3.9 or later.

To build a release, until a published one exists, you also need the same kind of Docker engine (the builder refuses anything other than Linux arm64), Python 3.12, and network access for the pinned base images and packages. This can be the machine you install on. Installing and running the package needs no network access.

## Get a release

There is no published release or tag yet, so build the release from the source. Clone the repository:

```sh
git clone https://github.com/nirtuttnauer/ModelAnvil.git ~/src/ModelAnvil
```

Build the release in a Python 3.12 environment inside the checkout:

```sh
python3.12 -m venv ~/src/ModelAnvil/.venv
~/src/ModelAnvil/.venv/bin/python -m pip install -r ~/src/ModelAnvil/requirements.txt
~/src/ModelAnvil/.venv/bin/python ~/src/ModelAnvil/scripts/build_selfhost_release.py --output ~/modelanvil-releases/0.1.0
```

- The builder takes the version from `deploy/selfhost/VERSION`, which says `0.1.0` in this checkout. `--version <version>` overrides it.
- It refuses a checkout with uncommitted changes, an existing output directory, an engine that is not Linux arm64, and a version whose images already exist on the engine. A release is never rebuilt.
- Its last line reports the version, the source commit and the image IDs.

A release directory holds `modelanvil.py` (the controller), `compose.yaml`, `reference.json`, `README.md`, `LICENSE`, `requirements.selfhost.lock.txt`, `images.tar` and `release.json`. Before the controller uses a release, it checks every file against the sizes and sha256 values in `release.json`, and it refuses a directory that contains any other file. These checksums detect corruption. Releases are not signed.

Keep every release directory you install. A rollback or a restore needs the release that matches the backup.

## Install

```sh
python3 ~/src/ModelAnvil/scripts/install_selfhost.py --directory ~/modelanvil --release ~/modelanvil-releases/0.1.0
```

The installer asks for the owner's email, a workspace name and a new password of at least 12 characters. Type your own. The password is not shown as you type it.

`scripts/install_selfhost.py` runs the release's own controller, `~/modelanvil-releases/0.1.0/modelanvil.py install`. It builds nothing, pulls nothing and does not use `deploy/production`. The controller refuses a directory that already exists. It copies the release into `~/modelanvil/release`, generates the instance secrets, loads the images from `images.tar`, creates the database and the owner account, registers the CPU worker and starts every service. Then it prints a result like this one:

```json
{
  "origin": "https://localhost:8443",
  "ready": true,
  "ca": "/home/operator/modelanvil/ca.crt",
  "version": "0.1.0",
  "production_qualified": false
}
```

- If setup stops before the owner account exists, fix the reported problem and resume with `python3 ~/modelanvil/release/modelanvil.py initialize --directory ~/modelanvil`. It refuses to replace an existing account.
- To install without prompts, add `--credentials-stdin` and pass the owner on standard input as JSON with the keys `email`, `name` and `password`. Keep that input private.
- For access from other machines on your network, choose the hostname, bind address and ports with `--host`, `--bind`, `--http-port` and `--https-port`, and give clients the instance's `ca.crt` through a channel you trust. Public DNS, ACME certificates and internet hosting are not part of the package.

Keep `~/modelanvil` private:

- `.env` holds the instance secrets.
- `ca.crt` is the public certificate of the instance's local certificate authority. Its private key stays in a Docker volume.
- `controller-private.log` collects detailed Docker errors.
- `ModelAnvil.app` (macOS) and `ModelAnvil.desktop` (Linux) are shortcuts that run `start --open`. Both are unsigned and experimental.

## Check that it runs

```sh
curl --fail --silent --show-error --cacert ~/modelanvil/ca.crt https://localhost:8443/api/v1/health/
curl --fail --silent --show-error --cacert ~/modelanvil/ca.crt https://localhost:8443/api/v1/ready/
```

The two commands print `{"status": "ok"}` and `{"status": "ready"}`. Always pass the instance's `ca.crt`, and do not turn certificate checks off.

To use the web app, open `https://localhost:8443` in a browser and sign in as the owner. The browser must trust `ca.crt` first. The installer does not change the browser's or the system's trusted certificates; importing `ca.crt` there is your step.

## Everyday commands

Use the controller inside the instance directory. An upgrade replaces it with the new one, so this path keeps working.

```sh
python3 ~/modelanvil/release/modelanvil.py status --directory ~/modelanvil
python3 ~/modelanvil/release/modelanvil.py stop --directory ~/modelanvil
python3 ~/modelanvil/release/modelanvil.py start --directory ~/modelanvil
python3 ~/modelanvil/release/modelanvil.py diagnostics --directory ~/modelanvil
```

- `stop` stops the containers and keeps all data.
- `start` starts them, waits until the instance is ready and prints the same result as the install. `start --open` also opens the web app in your browser.
- `status` and `diagnostics` print the same report: the Compose project, version and origin, each container's state, the release image IDs, `offline: true` and `production_qualified: false`. It holds no passwords, keys, model content or database dumps, so you can share it when you ask for help.

## Add the example model

```sh
python3 ~/modelanvil/release/modelanvil.py example --directory ~/modelanvil --name offline-example
```

This imports the release's reference model and its byte tokenizer, prepares four short text records and sets a 16-step quota. It prints the new IDs and a 4-step `full_sft` launch request. It does not start training. Chat with the model in the web app, or train it on the Training page with `full_sft`. The package guide describes [importing another reference bundle](../deploy/selfhost/README.md#explicit-local-import-and-recipe) with `import-reference`.

The upgrade rehearsal below needs an instance that holds at least one model and one stored artifact. The example is enough.

## Back up

Let running jobs finish, or cancel them, first. `backup` refuses while a job is queued, running or interrupted.

```sh
python3 ~/modelanvil/release/modelanvil.py backup --directory ~/modelanvil --output ~/modelanvil-backups/before-upgrade
```

`backup` stops the web app, the API, the worker and the reconciler, checks the job queue, writes five files into the new directory and starts the instance again:

- `database.dump`, the PostgreSQL dump;
- `artifacts.tar`, the stored artifacts;
- `.env` and `instance.json`, the instance's settings and secrets;
- `backup.json`, which records the release version and the sha256 of the other four files.

The files are mode 0600. They include the instance secrets and the account data, so keep the directory private. Keep a copy on another machine or disk under your own retention rules. `backup` refuses an existing directory, so it never overwrites an earlier backup.

## Upgrade

An upgrade needs a release with a different version. `upgrade` takes its own backup before it changes anything and keeps the previous release in the instance directory. It cannot be undone in place: going back to old code does not reverse database migrations. Going back is a restore of the upgrade's backup, as [Roll back](#roll-back) describes.

### Build the newer release

```sh
git -C ~/src/ModelAnvil pull --ff-only
~/src/ModelAnvil/.venv/bin/python ~/src/ModelAnvil/scripts/build_selfhost_release.py --output ~/modelanvil-releases/0.1.1
```

Name the output directory after the newer version, here `0.1.1`. The checkout's `deploy/selfhost/VERSION` must name a version you have not built on this engine, or pass `--version <new version>`. The builder refuses a version whose images already exist, and `upgrade` refuses the version that is already installed.

### Rehearse the upgrade on a copy

`scripts/drill_selfhost.py` backs up an instance, upgrades it and rolls it back, and checks after each step that nothing changed. Run it on a copy restored from your latest backup, so your own instance is not touched. Two more instances run during the rehearsal, on ports 18080/18443 and 28080/28443.

Restore the backup into a new rehearsal directory, with the release the backup was taken on:

```sh
python3 ~/modelanvil-releases/0.1.0/modelanvil.py restore --directory ~/modelanvil-rehearsal \
  --backup ~/modelanvil-backups/before-upgrade --release ~/modelanvil-releases/0.1.0 \
  --http-port 18080 --https-port 18443
```

Run the drill on the copy:

```sh
python3 ~/src/ModelAnvil/scripts/drill_selfhost.py run --directory ~/modelanvil-rehearsal \
  --previous-release ~/modelanvil-releases/0.1.0 --release ~/modelanvil-releases/0.1.1 \
  --backup ~/modelanvil-rehearsal-drill/backup --upgrade-backup ~/modelanvil-rehearsal-drill/upgrade-backup \
  --rollback-directory ~/modelanvil-rehearsal-drill/rollback --record ~/modelanvil-rehearsal-drill/record \
  --rollback-http-port 28080 --rollback-https-port 28443
```

The drill runs three controller commands, each with the controller of the release it concerns:

1. `backup` of `~/modelanvil-rehearsal` into `~/modelanvil-rehearsal-drill/backup`.
2. `upgrade` of `~/modelanvil-rehearsal` to 0.1.1, with `~/modelanvil-rehearsal-drill/upgrade-backup` as the upgrade's backup.
3. The rollback: `restore` of that upgrade backup with release 0.1.0 into `~/modelanvil-rehearsal-drill/rollback`.

Before the first step, and after each one, it records the row count of every table, the sha256 of every stored artifact, the tokens each CPU reference model generates for a fixed prompt, the PostgreSQL and pgvector versions, and the health and readiness checks. It stops at the first difference.

| Exit code | Meaning |
|---:|---|
| 0 | All three steps and all checks passed. |
| 1 | A step or a check failed. Nothing after it ran. |
| 2 | Refused before the first step: a wrong argument, an existing directory, a previous release that is not the installed one, or an instance with no model or no artifact. |

The drill also writes its report to `~/modelanvil-rehearsal-drill/record/report.json`. [self-host-drills.md](engineering/self-host-drills.md) describes every check.

Then remove the rehearsal. First uninstall both copies:

```sh
python3 ~/modelanvil-rehearsal/release/modelanvil.py uninstall --directory ~/modelanvil-rehearsal
python3 ~/modelanvil-rehearsal-drill/rollback/release/modelanvil.py uninstall --directory ~/modelanvil-rehearsal-drill/rollback
```

`uninstall` keeps the data volumes. The next commands delete the two copies' volumes, directories and backups permanently. They do not touch your instance or your own backups, and they keep the drill's record.

```sh
for instance in ~/modelanvil-rehearsal ~/modelanvil-rehearsal-drill/rollback; do
  project=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["compose_project"])' "$instance/instance.json")
  docker volume rm "${project}_database" "${project}_artifacts" "${project}_certificates" "${project}_caddy_config"
done
rm -rf ~/modelanvil-rehearsal ~/modelanvil-rehearsal-drill/backup ~/modelanvil-rehearsal-drill/upgrade-backup ~/modelanvil-rehearsal-drill/rollback
```

### Upgrade your instance

Let jobs finish first, as for a backup. Run the upgrade with the new release's controller:

```sh
python3 ~/modelanvil-releases/0.1.1/modelanvil.py upgrade --directory ~/modelanvil \
  --release ~/modelanvil-releases/0.1.1 --backup ~/modelanvil-backups/upgrade-to-0.1.1
```

`upgrade` checks and loads the new release, stops writes and backs the instance up into `~/modelanvil-backups/upgrade-to-0.1.1`. That backup records version 0.1.0. Then it moves the previous release to `~/modelanvil/release-history/`, migrates the database and starts the instance. The directory, the Docker project, the data and the certificate authority stay the same.

Check the result:

```sh
python3 ~/modelanvil/release/modelanvil.py status --directory ~/modelanvil
curl --fail --silent --show-error --cacert ~/modelanvil/ca.crt https://localhost:8443/api/v1/ready/
```

## Roll back

The controller has no rollback command, and it does not reverse a migration in place. To go back to the previous version, restore the upgrade's backup with the previous release into a new directory. The restored instance holds the data as it was when the upgrade started. Anything written to the upgraded instance after that is not in it.

Stop the upgraded instance, so that the restored one can use the same ports:

```sh
python3 ~/modelanvil/release/modelanvil.py stop --directory ~/modelanvil
```

Restore the upgrade's backup with the previous release, then check the restored instance:

```sh
python3 ~/modelanvil-releases/0.1.0/modelanvil.py restore --directory ~/modelanvil-rollback \
  --backup ~/modelanvil-backups/upgrade-to-0.1.1 --release ~/modelanvil-releases/0.1.0
curl --fail --silent --show-error --cacert ~/modelanvil-rollback/ca.crt https://localhost:8443/api/v1/ready/
```

`restore` refuses a release whose version differs from the one in `backup.json`. It checks the sha256 of every backup file and refuses unsafe paths in the artifact archive. It creates a new Docker project with new volumes and never writes into an existing instance. The accounts, models, datasets, artifacts and quotas come from the backup. The restored instance has a new certificate authority of its own, so give clients `~/modelanvil-rollback/ca.crt`.

From here on, `~/modelanvil-rollback` is your instance directory. Use `python3 ~/modelanvil-rollback/release/modelanvil.py <command> --directory ~/modelanvil-rollback` for the everyday commands. Do not start `~/modelanvil` again while the restored instance uses its ports.

## Uninstall

When you no longer need an instance, for example the upgraded one you rolled back from, uninstall it:

```sh
python3 ~/modelanvil/release/modelanvil.py uninstall --directory ~/modelanvil
```

`uninstall` removes the containers and networks. It keeps the instance directory, the previous releases, your backups and the four data volumes: `<project>_database`, `<project>_artifacts`, `<project>_certificates` and `<project>_caddy_config`, where `<project>` is `compose_project` in the instance's `instance.json`. `start` brings a retained installation back.

Deleting the data is a separate step. The volume and directory commands in [Rehearse the upgrade on a copy](#rehearse-the-upgrade-on-a-copy) do it for a given instance directory. That deletion cannot be undone, so keep a backup.

## Restore on another machine

A backup directory is self-contained. To move an instance to another machine, or to recover it there:

1. Give the second machine the tools listed under [Requirements](#requirements) and check it with the same commands. It needs no source checkout and no network access.
2. Copy the backup directory and the release that the backup records to the same paths on the second machine: here `~/modelanvil-backups/before-upgrade` and `~/modelanvil-releases/0.1.0`. Use a tool that keeps file modes, such as `rsync -a` or `scp -rp`, and keep the copy private.
3. On the second machine, read which release the backup needs, restore the backup, and check the restored instance:

```sh
grep '"release"' ~/modelanvil-backups/before-upgrade/backup.json
python3 ~/modelanvil-releases/0.1.0/modelanvil.py restore --directory ~/modelanvil \
  --backup ~/modelanvil-backups/before-upgrade --release ~/modelanvil-releases/0.1.0
curl --fail --silent --show-error --cacert ~/modelanvil/ca.crt https://localhost:8443/api/v1/health/
```

The release carries its own PostgreSQL image, so the second machine runs the same PostgreSQL and pgvector versions. The restored instance has its own certificate authority. To compare it table by table with the source, take a drill snapshot of the source before the backup and run `drill_selfhost.py snapshot --expect` on the restored instance, as [self-host-drills.md](engineering/self-host-drills.md#off-host-restore) describes.

## Limits

- Linux arm64 Docker engines only. The controller refuses Windows, amd64 and emulated engines.
- One CPU worker and one small reference model with the `full_sft` recipe. No pretrained model, no GPU worker and no language-quality result. Larger recipes that need packages absent from the release show as unavailable.
- Hardware levels across ModelAnvil: CPU, and MPS on one Apple silicon Mac, at the integrated-execution level. CUDA is in the code and not verified.
- `production_qualified` is `false` in `release.json` and in the install, `start`, `status` and `diagnostics` results. No support, uptime, recovery-time or recovery-point commitment.
- HTTPS uses a local certificate authority per instance. No public DNS and no ACME. The default bind address is loopback.
- Releases are checksummed, not signed. The `.app` and `.desktop` shortcuts are unsigned and experimental.
- Going back to old code does not reverse database migrations. The rollback is a restore of the upgrade backup. Schema compatibility is checked release by release.
- One controller operation at a time per instance. Concurrent upgrades by several operators are not covered.
- Backups are written on the same machine. Copying them elsewhere is your step.
- No published release, tag or registry image yet. Publishing a release and installing it on a separate physical Linux arm64 host are still to come.

What was run:

- This page was followed command by command on a new, empty Docker engine, with a second new engine for [Restore on another machine](#restore-on-another-machine). Both engines were `docker:dind` containers on Docker Desktop on one Apple M5 Pro Mac, not separate physical hosts. The releases were 0.1.0 and 0.1.1, built earlier. The two build steps were not rerun. [Record](engineering/verification/anvil-027-2026-11-12/report.md).
- Earlier records: the [package test on 24 October 2026](engineering/self-host.md), the [fresh-engine install](engineering/verification/anvil-024-2026-11-12/report.md), the [backup, upgrade and rollback drill](engineering/verification/anvil-025-2026-11-12/report.md), the [install on a second, reset engine](engineering/verification/anvil-026-2026-11-12/report.md) and the [memory measurement](engineering/verification/anvil-029-2026-11-12/report.md).

## Other deployment files in this repository

- `deploy/helm` is unsupported. Do not install ModelAnvil with it. See [deploy/helm/README.md](../deploy/helm/README.md).
- `deploy/production` is a separate Compose procedure for one public Docker host, with PostgreSQL, Gunicorn and Caddy. It is not this package, it starts no job worker, and `scripts/install_selfhost.py` does not call it. See [deploy/production/README.md](../deploy/production/README.md).
- [deploy/selfhost/README.md](../deploy/selfhost/README.md) is the package guide; every release ships it as `README.md`. [self-host-package.md](engineering/self-host-package.md) records the scope of this work.
