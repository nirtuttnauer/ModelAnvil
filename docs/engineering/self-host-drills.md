# Self-host drills: backup, upgrade and rollback

`scripts/drill_selfhost.py` rehearses a backup, an upgrade and a rollback on an installed self-host instance. It runs only the controller subcommands that already exist (`backup`, `upgrade`, `restore`) in the order set by the ANVIL-026 child in [self-host-package.md](self-host-package.md). It adds no controller subcommand, no Compose service and no image. It builds nothing, pulls nothing and deletes nothing. The package commands it calls are documented in [deploy/selfhost/README.md](../../deploy/selfhost/README.md).

The measured run on 12 November 2026 is in [verification/anvil-025-2026-11-12/report.md](verification/anvil-025-2026-11-12/report.md).

## What you need

- Two verified Linux arm64 releases built by `scripts/build_selfhost_release.py`: the one the instance runs now, and a newer one with a different version. The builder refuses to rebuild an existing version, so the newer release needs a new `deploy/selfhost/VERSION` or an explicit `--version`.
- An installed instance with data in it. The drill refuses an instance with no committed artifact or no CPU reference model, because it could not show anything about the restore. The included example (`modelanvil.py example`) and one `full_sft` run of it are enough.
- No queued, running or interrupted job. The controller's `backup` refuses an active queue.
- Python 3.9 or later on the controller host, with the standard library only. The drill runs on the same host as the controller.

## Run the drill

```sh
python3 scripts/drill_selfhost.py run --directory "$HOME/ModelAnvil" \
  --previous-release /path/to/release-0.1.0 --release /path/to/release-0.1.1 \
  --backup /private/drill/backup --upgrade-backup /private/drill/upgrade-backup \
  --rollback-directory /private/drill/rollback --record /private/drill/record \
  --rollback-http-port 28080 --rollback-https-port 28443
```

`--backup`, `--upgrade-backup`, `--rollback-directory` and `--record` must be new directories outside the installed directory. `--rollback-host`, `--rollback-bind`, `--rollback-http-port` and `--rollback-https-port` are passed to `restore` only when given. Otherwise the controller's defaults apply (`localhost`, `127.0.0.1`, 8080 and 8443). Pick ports the upgraded instance does not use, because both instances run at the end of the drill.

| Step | Controller that runs | Subcommand | Effect |
|---|---|---|---|
| 1. Backup | the installed copy, `<directory>/release/modelanvil.py` | `backup --directory <directory> --output <backup>` | Stops writes, checks the queue, writes `database.dump`, `artifacts.tar`, `.env`, `instance.json` and `backup.json`, restarts the instance. |
| 2. Upgrade | the new release, `<release>/modelanvil.py` | `upgrade --directory <directory> --release <release> --backup <upgrade-backup>` | Verifies and stages the new release, takes its own backup with restart left off, keeps the previous release under `release-history/`, migrates, starts. |
| 3. Rollback | the previous release, `<previous-release>/modelanvil.py` | `restore --directory <rollback-directory> --backup <upgrade-backup> --release <previous-release>` | Loads the upgrade backup into a new directory and a new Compose project with the previous release, migrates, starts. |

`restore` accepts the step-3 pair because the upgrade backup records the version it was taken on, and that is the previous release. There is no in-place rollback. The drill leaves the upgraded directory, its migrated database and its volumes as they are. Code rollback does not reverse database migrations; the restore of the paired backup is the rollback.

## What the drill checks

Before step 1, and after each step on the instance that step leaves running, the drill takes a snapshot. A snapshot runs one read-only probe inside the instance's `api` container (`docker compose exec -T api python -c ...`) on the instance's own Compose project. It records:

- the row count of every table in the database, with exact `COUNT(*)`;
- every committed artifact's recorded sha256 and size, and the sha256 and size of its stored bytes, re-read from artifact storage;
- the path, size and sha256 of every file in the artifact volume;
- the token ids from greedy decoding of every CPU reference model for one prompt (default `a tiny`, 8 tokens). It uses the bundle loader and decoder that the inference API uses for these models, reading the weights from the instance's artifacts;
- the PostgreSQL `server_version` and the installed `vector` extension version;
- `GET /api/v1/health/` and `GET /api/v1/ready/` over HTTPS, trusting only the instance's own `ca.crt`.

After each step the snapshot must equal the one taken before step 1: the same row count in every table, the same artifact ids, sha256 and sizes with stored bytes that match, the same artifact files, the same token ids for every model, the same PostgreSQL and pgvector versions, health `{"status": "ok"}` and readiness 200. The instance version must be the old version after step 1, the new version after step 2, and the previous version after step 3. The drill stops at the first failed step or check and names what differed.

The probe makes no inference request through the API, so it adds no row to the instance it checks. The drill never reads `.env`; `docker compose` reads it as the env file.

## Output and exit codes

The record directory holds `report.json` and the snapshots `baseline.json`, `after-backup.json`, `after-upgrade.json` and `after-rollback.json`. `report.json` lists each step with its command, start time, duration, exit code and the controller's JSON result. It records when each backup was completed (the time `backup.json` was written). For the rollback it records `backup_age_seconds` (from the upgrade backup's completion to the start of the restore) and `restore_seconds`. It also holds every comparison. It sets `production_qualified` to false. No credential or secret value is written to the record, and the snapshots hold no model weights or artifact content.

| Exit | Meaning |
|---:|---|
| 0 | All three steps and all checks passed. |
| 1 | A controller step failed, or a check after a step found a difference. Nothing after it ran. |
| 2 | Refused before the first controller call: a wrong or missing argument, an existing directory, a previous release that is not the one installed, a release that is already installed, or an instance with nothing to check. Nothing was created except, once the baseline snapshot ran, the record directory. |

## After the drill

Both the upgraded instance and the rollback instance are running. Keep the one you want and stop the other with `modelanvil.py stop --directory ...`. `uninstall` removes containers and networks and keeps the four data volumes (`<project>_database`, `_artifacts`, `_certificates`, `_caddy_config`). Removing them is a separate, explicit operator step (`docker volume rm`) that permanently deletes that instance's data. Both backups hold private identity and instance secrets; the record directory holds neither. Keep the backups under your retention policy.

## Off-host restore

A backup directory is self-contained: `database.dump`, `artifacts.tar`, `.env`, `instance.json` and `backup.json`. To restore it on another host:

1. Copy the whole backup directory to the other host and keep it private (the files are mode 0600).
2. Use the release whose version the backup records (`backup.json` `release`). The release carries its own PostgreSQL image (`pgvector/pgvector`, pinned by digest in the builder), so the restore host gets the same PostgreSQL and pgvector versions. `restore` refuses a release whose version differs from the backup.
3. Restore into a new directory with that release's controller:

   ```sh
   python3 /path/to/release-0.1.0/modelanvil.py restore --directory /private/offhost/restored \
     --backup /private/offhost/backup --release /path/to/release-0.1.0 --http-port 18080 --https-port 18443
   ```

4. Compare the restored instance with the snapshot taken from the source before the backup:

   ```sh
   python3 scripts/drill_selfhost.py snapshot --directory /private/offhost/restored \
     --expect /private/drill/record/baseline.json --output /private/offhost/snapshot.json
   ```

   `snapshot --expect` reuses the recorded prompt and token limit. It exits 0 when the row counts, artifacts, artifact files, greedy tokens, PostgreSQL and pgvector versions are equal and the restored instance is healthy, 1 when something differs, and 2 when it could not take the snapshot. Without `--expect` it prints the snapshot and whether it is usable for a restore check.

Record the backup age at the start of the restore and the restore duration with the result.

## Limits

- A restore of the upgrade backup brings back the state at the moment the upgrade started. Writes made to the upgraded instance after that are not in it.
- The drill covers one installed instance and one upgrade at a time. Each controller operation must run alone for a given instance.
- The greedy-token check covers CPU reference models only, the profile this package supports. Other runtimes are not in the package.
- The off-host procedure above is a manual copy. The drill does not ship backups to another host.
- `production_qualified` stays false in the builder, the controller diagnostics, the qualification proof and this drill's report.
