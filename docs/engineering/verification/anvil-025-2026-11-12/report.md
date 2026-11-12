# ANVIL-025: backup, upgrade, rollback and off-host restore drill

Label: `local`. Everything ran on Nir's Mac: the Docker Desktop Linux VM, plus one new `docker:dind` engine inside that VM for the off-host restore. Neither is a second physical machine.

- Date: 12 November 2026. Times below are UTC.
- Code commit built, installed and drilled: `bf7359ea82ee6376d092684a09da32bb1d861a6c` on `claude/anvil-025-selfhost-drills`, parent `fb9ccef` (`origin/main`). `git status --porcelain` printed 0 lines after the commit and before the build.
- This report and its evidence files are the docs-only commit that follows `bf7359e`.
- Machine: Apple M5 Pro, 48 GiB, macOS 27.0.1 (26A434). Docker Desktop engine 29.9.2, `linux/arm64`, kernel `7.0.14-linuxkit`, VM `MemTotal` 8317202432, 18 CPUs. Docker Compose v5.6.1. The installer, the controllers and the drill ran on `/usr/bin/python3` 3.9.6. The unit tests and the builder ran on Python 3.12.15.

Paths below:

- `$WT` = the `claude/anvil-025-selfhost-drills` worktree
- `$RELEASES` = `~/.cache/modelanvil-selfhost/releases` (both release directories are kept)
- `$SCRATCH` = a private session scratch directory; the instances, backups and credentials there were removed
- `$TESTLOCK` = the host test-lock wrapper; `$VENV_PYTHON` = the Python 3.12 venv interpreter

## What changed in `bf7359e`

- `scripts/drill_selfhost.py`, `run`: calls the existing controller in the order the ANVIL-026 child of [self-host-package.md](../../self-host-package.md) sets. Step 1 is `backup` of the installed directory into a new directory, run by the installed copy of the controller. Step 2 is `upgrade` with the second release and a second new backup directory, run by the second release's controller. Step 3, the rollback, is `restore` of the backup passed to `upgrade` into a new directory, run by the previous release's controller with the previous release. There is no in-place rollback and no new controller subcommand. Before step 1 and after each step it takes a snapshot and stops at the first difference. Refusals before the first controller call exit 2.
- `scripts/drill_selfhost.py`, `snapshot [--expect]`: one read-only probe in the instance's `api` container records exact `COUNT(*)` for every table, each committed artifact's recorded sha256 next to the sha256 of its stored bytes, path, size and sha256 for every file in the artifact volume, greedy-decoding token ids for every CPU reference model (through the bundle loader and decoder the inference API uses), PostgreSQL `server_version` and the `vector` extension version. It also records health and readiness, checked over HTTPS with the instance's own CA. `--expect` compares the instance with a recorded snapshot, which is how the off-host restore below was checked. The drill never reads `.env`, runs on Python 3.9, and uses only the standard library.
- `modelanvil/core/test_selfhost_drills.py`: 11 Docker-free tests (listed below).
- `docs/engineering/self-host-drills.md`: the operator page, which includes the off-host procedure.

The plan names `scripts/test_drill_selfhost.py` for the tests. The Django `DiscoverRunner` does not collect `scripts/`, so the tests sit in `modelanvil/core/test_selfhost_drills.py`, next to the installer tests, where `manage.py test` runs them. ANVIL-024 did the same.

## Unit tests

```sh
cd $WT && env -u DATABASE_ENGINE DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=$WT \
  DATABASE_NAME=$SCRATCH/db.sqlite3 DATABASE_TEST_NAME=$SCRATCH/test.sqlite3 \
  $VENV_PYTHON manage.py test modelanvil.core.test_selfhost_drills modelanvil.core.test_selfhost --noinput -v 2
```

This ran inside the lock hold described below. Exit 0. `Ran 27 tests in 4.333s`, `OK`, with no skips: the 16 existing tests in `modelanvil.core.test_selfhost` and these 11 new ones. Full output is in [unit-tests.txt](unit-tests.txt).

- `DrillCommandTests.test_drill_backs_up_upgrades_then_restores_the_upgrade_backup_with_the_previous_release`: checks the exact three controller argument lists and their order, and that the restore never names the upgraded directory. The rollback restores the upgrade backup, not the step-1 backup. Snapshots run on the instance three times and on the rollback directory once. Also checks the record files, the backup age and restore time fields, `production_qualified: false`, and that the instance secrets appear nowhere in stdout, stderr or the record.
- `DrillCommandTests.test_refusals_run_before_any_controller_call_or_snapshot`: 9 cases (no `instance.json`; previous release with another version; same version but other images; release already installed; release without `release.json`; existing backup; existing record; backup equals upgrade backup; rollback inside the instance). Each exits 2 with no controller call, no snapshot and no directory created.
- `DrillCommandTests.test_an_instance_without_a_model_is_refused_before_the_backup`
- `DrillCommandTests.test_failed_upgrade_stops_the_drill_before_any_restore`
- `DrillCommandTests.test_state_changed_by_the_upgrade_stops_the_drill_and_names_the_table`
- `DrillCommandTests.test_rollback_that_comes_back_on_another_version_fails`
- `DrillComparisonTests.test_comparison_names_every_difference`: covers row counts, a missing table, artifact sha256 and set, stored bytes, artifact files, tokens, a failed generation, a different prompt, pgvector, PostgreSQL version, health and readiness.
- `SnapshotCommandTests.test_snapshot_probes_through_the_instance_compose_project_and_trusts_only_its_ca`
- `SnapshotCommandTests.test_failed_probe_keeps_docker_detail_in_a_private_log`
- `SnapshotCommandTests.test_expect_reuses_the_recorded_prompt_and_exits_one_on_a_mismatch`
- `ProbeTests.test_probe_records_rows_artifact_hashes_and_greedy_tokens_and_detects_changed_bytes`: runs the exact probe source against the test database with a real imported reference model. Two probes compare equal. After one flipped byte in a stored artifact, the comparison reports both the artifact-file change and the stored-bytes mismatch.

An earlier run of the same command, before the commit, had 4 failures and 1 error. All five came from fixture bugs in the new tests: the stand-in controller did not create parent directories, and one helper's argument name clashed with `name=`. They were fixed before `bf7359e`. The run above is at `bf7359e`'s tree.

## Live run

All of it ran under one hold of the host test lock:

```sh
$TESTLOCK $SCRATCH/tools/gate-build-live.sh
```

That script ran the unit tests, made the code commit, built release 0.1.1, then ran [run-all.sh](run-all.sh), which ran [phase1.sh](phase1.sh), [offhost_restore.py](offhost_restore.py) and [cleanup.sh](cleanup.sh). The lock was held from 20:17:05Z to 20:20:24Z. The committed [gate-build-live.sh](gate-build-live.sh) shows its four fixed paths as environment variables. The full log is [live-run.txt](live-run.txt). Its second `lock acquired` line is `run-all.sh`'s own banner inside the same hold.

| Step | Command | Exit | Seconds | Start |
|---|---|---:|---:|---|
| Unit tests | as above | 0 | 9 | 20:17:05 |
| Build 0.1.1 | `$VENV_PYTHON scripts/build_selfhost_release.py --output $RELEASES/0.1.1 --version 0.1.1` | 0 | 37 | 20:17:14 |
| Install 0.1.0 | `/usr/bin/python3 $WT/scripts/install_selfhost.py --directory $SCRATCH/live/instance --release $RELEASES/0.1.0 --http-port 41080 --https-port 41443 --credentials-stdin < <owner credentials>` | 0 | 18 | 20:17:52 |
| Health after install | `curl --fail --cacert $SCRATCH/live/instance/ca.crt https://localhost:41443/api/v1/health/` | 0 | | |
| Data | `/usr/bin/python3 seed.py seed $WT/scripts $SCRATCH/live/instance <owner credentials>` ([seed.py](seed.py)) | 0 | 11 | 20:18:10 |
| Drill | `/usr/bin/python3 $WT/scripts/drill_selfhost.py run --directory $SCRATCH/live/instance --previous-release $RELEASES/0.1.0 --release $RELEASES/0.1.1 --backup $SCRATCH/live/backup --upgrade-backup $SCRATCH/live/upgrade-backup --rollback-directory $SCRATCH/live/rollback --record $SCRATCH/live/record --rollback-http-port 42080 --rollback-https-port 42443` | 0 | 55 | 20:18:21 |
| Off-host restore | `/usr/bin/python3 offhost_restore.py $WT $RELEASES/0.1.0 $SCRATCH/live/backup $SCRATCH/live/record/baseline.json <owner credentials> $SCRATCH/live/seed.json $SCRATCH/live/offhost` | 0 | 50 | 20:19:23 |
| Cleanup | `cleanup.sh $SCRATCH/live` | 0 for each command | 11 | 20:20:13 |

The build's only stderr was Docker's legacy-builder deprecation notice, printed once for each image target. Most layers came from the build cache. Only the layers that copy the source tree were rebuilt.

### Release 0.1.1

The builder's last line reported version `0.1.1`, source revision `bf7359ea82ee6376d092684a09da32bb1d861a6c` and `offline_bytes` 349829632. `release.json` records `architecture` `arm64`, `os` `linux` and `production_qualified` `false`. Release 0.1.0 was built at `fe9a94c` earlier the same day (ANVIL-024) and was not rebuilt. Its image tags were already on this engine, and the rollback used them.

| | 0.1.0 (`fe9a94c`) | 0.1.1 (`bf7359e`) |
|---|---|---|
| `api` image | `20b2a07b dccc130a c1847faa e755f24a 69d53379 e5707047 53d03871 3a80ad75` | `67fef97c 390f4698 c1d8dbd0 ea653397 59efe132 030b9719 70cca130 b27ecb4c` |
| `web` image | `d82a908d 496b0100 1458be5f 2f201112 1f81c523 4cbcc573 191b2428 51134b1d` | `09e375c9 eb1a41ce 5e86af5e 27ff70f4 13b382a5 fa2ed680 45d1a7b7 e5966998` |
| `db` image (`pgvector/pgvector`) | `7b822b0a ac60967b eb1ea5e5 76b8602c 94c300a1 57d187f3 85ae3e0d a199b90a` | same |
| `images.tar` | 349774336 bytes, `144932c4 6721d3f2 efe91810 6e22ddea d2e6705e 41bb9024 837ca690 45814d67` | 349829632 bytes, `5e09f39e c227d386 5bcdfc4b 2818977a b98f65d0 c152912f c73cab6e a3dea8fb` |
| `modelanvil.py` | `32e77635 d8cbd064 cd64ee09 9c8c2ce9 ed2c0dfc 25aca494 802d3430 0b50af81` | same |

The other release files (`LICENSE`, `README.md`, `compose.yaml`, `reference.json`, `requirements.selfhost.lock.txt`) have the same bytes in both releases. No migration file changed between `fe9a94c` and `bf7359e`, so the upgrade's `migrate` had nothing to apply.

### Data in the instance

[seed.py](seed.py) ran the controller's `example` import, signed in as the owner, and sent one greedy chat completion to the imported model. It then ran the returned four-step `full_sft` launch to completion (`completed`, step 4, 4 checkpoints, 7.0 s) and sent one greedy chat completion to the trained model. The instance then held:

- imported model version `01a1d169-28b3-708c-91f0-ff3051e2ee95` and trained model version `01a1d169-4579-7b24-9469-569c4e795c49` (training run `01a1d169-30c0-78f9-8873-da9ec72c007d`)
- 4 committed artifacts: the imported reference bundle, the example records, the prepared dataset and the trained candidate bundle
- 107 tables, 31 of them with rows, 661 rows in all

### Backup, upgrade and rollback

From [drill-report.json](drill-report.json):

| Drill step | Controller | Exit | Seconds | Start | Result |
|---|---|---:|---:|---|---|
| 1. `backup --directory $SCRATCH/live/instance --output $SCRATCH/live/backup` | `$SCRATCH/live/instance/release/modelanvil.py` (0.1.0) | 0 | 12.6 | 20:18:24 | 4 verified checksums; `backup.json` written 20:18:29 |
| 2. `upgrade --directory $SCRATCH/live/instance --release $RELEASES/0.1.1 --backup $SCRATCH/live/upgrade-backup` | `$RELEASES/0.1.1/modelanvil.py` | 0 | 14.6 | 20:18:39 | version `0.1.1`, ready; 0.1.0 kept at `release-history/0.1.0-d8e6a0cb`; upgrade backup `backup.json` written 20:18:45 with `release` `0.1.0` |
| 3. Rollback: `restore --directory $SCRATCH/live/rollback --backup $SCRATCH/live/upgrade-backup --release $RELEASES/0.1.0 --http-port 42080 --https-port 42443` | `$RELEASES/0.1.0/modelanvil.py` | 0 | 13.7 | 20:18:57 | version `0.1.0`, ready, new Compose project |

| Check | Instance | Version | Result |
|---|---|---|---|
| after backup | `modelanvil-local-080d2e2d1e3d` | 0.1.0 | equal to the baseline, no problems |
| after upgrade | `modelanvil-local-080d2e2d1e3d` | 0.1.1 | equal to the baseline, no problems |
| after rollback | `modelanvil-local-3420ff77e118` (new) | 0.1.0 | equal to the baseline, no problems |

The baseline snapshot was taken at 20:18:21, before step 1. The after-backup snapshot, taken from the same instance after the backup restarted it, is equal to it. So the baseline is also the state in both backups.

Rollback recovery point: the upgrade backup was completed at 20:18:45 and the restore started at 20:18:57. That is a **backup age of 12.5 s at restore start** and a **restore time of 13.7 s**. Release 0.1.0's images were already on this engine.

Backup sizes: `database.dump` 725726 bytes (step 1) and 725727 bytes (upgrade backup); `artifacts.tar` 61440 bytes in both. Every backup file is mode 0600.

## Off-host restore

[offhost_restore.py](offhost_restore.py) started a new privileged `docker:dind@sha256:08a98015 fce594af 7c382883 bea080ea 206de744 02a95da9 dc52b642 8c8cd121` container (`anvil025-offhost`) with a new, empty `/var/lib/docker` volume (`anvil025-offhost-docker`). It mounted release 0.1.0 read-only at `/release` and `$WT/scripts` (at `bf7359e`) read-only at `/scripts`. The inner engine was Docker 29.9.3, `linux`/`aarch64`, `MemTotal` 8317202432, 18 CPUs. It had 0 images, 0 volumes and 0 containers before the restore and had never seen ModelAnvil. `apk add python3 curl` gave Python 3.14.10. Full log: [offhost.txt](offhost.txt); record: [offhost.json](offhost.json).

1. `docker cp $SCRATCH/live/backup anvil025-offhost:/offhost/backup` copied the step-1 backup into the inner container's filesystem. Inside it, the sha256 of all five files (`database.dump`, `artifacts.tar`, `.env`, `instance.json`, `backup.json`) equalled the source, and every file was mode 600. The baseline snapshot was copied next to it.
2. Restore inside the new engine, with release 0.1.0:

   ```sh
   python3 /release/modelanvil.py restore --directory /offhost/restored --backup /offhost/backup --release /release \
     --http-port 43080 --https-port 43443
   ```

   Exit 0. Result: `ready` true, version `0.1.0`, `production_qualified` false, Compose project `modelanvil-local-93ceac61900d`. The step-1 backup was completed at 20:18:29 and the restore ran from 20:19:29 to 20:19:53. That is a **backup age of 59.7 s at restore start** and a **restore time of 24.5 s**. The restore time includes loading release 0.1.0's `images.tar` into the empty engine.
3. Health: `curl --fail --cacert /offhost/restored/ca.crt https://localhost:43443/api/v1/health/` returned `{"status": "ok"}` (exit 0); `/api/v1/ready/` returned `{"status": "ready"}` (exit 0).
4. Comparison with the source:

   ```sh
   python3 /scripts/drill_selfhost.py snapshot --directory /offhost/restored --expect /offhost/baseline.json --output /offhost/snapshot.json
   ```

   Exit 0, `equal` true, `problems` `[]`. The snapshot is [offhost-snapshot.json](offhost-snapshot.json).
5. Inside the engine, `stop` and `uninstall` exited 0 and `docker volume rm` removed the restored project's four volumes. The inner engine then had 0 containers, 0 volumes and 0 project networks. The outer container and its volume were then removed (0 left).

## Comparisons

All five snapshots: the source before the backup ([baseline.json](baseline.json)), the source after the backup ([after-backup.json](after-backup.json)), the upgraded source ([after-upgrade.json](after-upgrade.json)), the rollback restore ([after-rollback.json](after-rollback.json)) and the off-host restore ([offhost-snapshot.json](offhost-snapshot.json)).

### Rows per table

Exact `COUNT(*)` on every table in the `public` schema:

| Table | baseline | after backup | after upgrade | after rollback | off-host |
|---|---:|---:|---:|---:|---:|
| `artifacts_artifact` | 4 | 4 | 4 | 4 | 4 |
| `artifacts_dataset` | 1 | 1 | 1 | 1 | 1 |
| `artifacts_datasetrevision` | 1 | 1 | 1 | 1 | 1 |
| `artifacts_lineageedge` | 1 | 1 | 1 | 1 | 1 |
| `auth_permission` | 412 | 412 | 412 | 412 | 412 |
| `budgets_budgetpolicy` | 1 | 1 | 1 | 1 | 1 |
| `budgets_budgetreservation` | 1 | 1 | 1 | 1 | 1 |
| `budgets_usageevent` | 1 | 1 | 1 | 1 | 1 |
| `core_auditevent` | 1 | 1 | 1 | 1 | 1 |
| `core_idempotencykey` | 1 | 1 | 1 | 1 | 1 |
| `core_projectprivacypolicy` | 1 | 1 | 1 | 1 | 1 |
| `django_content_type` | 103 | 103 | 103 | 103 | 103 |
| `django_migrations` | 108 | 108 | 108 | 108 | 108 |
| `identity_apikey` | 1 | 1 | 1 | 1 | 1 |
| `identity_membership` | 1 | 1 | 1 | 1 | 1 |
| `identity_project` | 1 | 1 | 1 | 1 | 1 |
| `identity_team` | 1 | 1 | 1 | 1 | 1 |
| `identity_tenant` | 1 | 1 | 1 | 1 | 1 |
| `identity_user` | 1 | 1 | 1 | 1 | 1 |
| `jobs_job` | 1 | 1 | 1 | 1 | 1 |
| `jobs_jobattempt` | 1 | 1 | 1 | 1 | 1 |
| `jobs_outboxevent` | 1 | 1 | 1 | 1 | 1 |
| `jobs_worker` | 1 | 1 | 1 | 1 | 1 |
| `jobs_workerpool` | 1 | 1 | 1 | 1 | 1 |
| `runners_inferencerequest` | 2 | 2 | 2 | 2 | 2 |
| `runners_model` | 2 | 2 | 2 | 2 | 2 |
| `runners_modelversion` | 2 | 2 | 2 | 2 | 2 |
| `runners_runnermanifest` | 2 | 2 | 2 | 2 | 2 |
| `runners_tokenizerversion` | 1 | 1 | 1 | 1 | 1 |
| `runners_trainingcheckpoint` | 4 | 4 | 4 | 4 | 4 |
| `runners_trainingrun` | 1 | 1 | 1 | 1 | 1 |
| **Total, 107 tables** | **661** | **661** | **661** | **661** | **661** |

The other 76 tables had 0 rows in all five snapshots. Their names are in each snapshot's `rows` field.

### Committed artifacts

Recorded sha256 and size from the database. "Stored bytes" means the bytes re-read from artifact storage in that instance and hashed.

| Artifact | Content | Bytes | Recorded sha256 | Stored bytes equal in all five |
|---|---|---:|---|---|
| `01a1d169-28ab-7e3f-9bd1-56197c811ee8` | imported `reference.json` | 17805 | `4f029379 dff4f607 760f12e8 db96d0be 054ceb6d a4184938 f099f961 c5123234` | yes |
| `01a1d169-28b5-7dce-a345-ac9ce01f2a2a` | `example.jsonl` | 1463 | `01553a6b 265571b5 28d15a57 21e89f83 6279cb57 1d21306f 38e5dc86 1c177be4` | yes |
| `01a1d169-28bf-7836-bd2f-a48c407e9974` | prepared dataset | 1850 | `a1706ba5 d05e1cf3 b16d5811 05579d05 4f4176ac 5aca61c3 3c14199b 18541852` | yes |
| `01a1d169-4574-78a4-9415-ed7ec5efb41c` | trained `candidate.json` | 19480 | `433f10f7 c7844d45 f7010e9a 02729291 49e814f6 c4be59e9 451fe02b feab1821` | yes |

The imported bundle's sha256 equals the release's `reference.json`. The artifact volume held exactly four files, under the tenant prefix: `datasets/.../51b82f87-....json`, `model-imports/.../reference.json`, `model-imports/.../example.jsonl` and `training/01a1d169-30c0-.../candidate.json`. Their paths, sizes and sha256 were the same in all five snapshots, and each one is one of the artifacts above.

### Greedy-decoding tokens

Prompt `a tiny`, 8 new tokens, greedy argmax. The weights were read from each instance's own restored artifacts:

| Model version | Token ids, identical in all five snapshots | Decoded |
|---|---|---|
| `01a1d169-28b3-708c-91f0-ff3051e2ee95` (imported, untrained) | `[161, 59, 48, 73, 212, 59, 193, 102]` | `�7,E�7�b` |
| `01a1d169-4579-7b24-9469-569c4e795c49` (trained) | `[101, 116, 120, 120, 120, 125, 50, 2]` | `apttty.` (ends with end-of-sequence id 2) |

The same prompt also went through the authenticated chat API (`temperature` 0, `max_tokens` 8, `prompt_format` `plain`). These calls ran after each snapshot, so they did not change the counted rows.

| Instance | Imported model | Trained model |
|---|---|---|
| source, before the backup | `�7,E�7�b`, 8 tokens, `length` | `apttty.`, 8 tokens, `stop` |
| rollback restore | same | same |
| upgraded source (0.1.1) | same | same |
| off-host restore | same | same |

### Database versions

PostgreSQL `16.15 (Debian 16.15-1.pgdg12+2)` and pgvector `0.8.7` in all five snapshots. Both releases ship the same `db` image ID, and the off-host engine loaded it from release 0.1.0's `images.tar`.

## Health

| Instance | `/api/v1/health/` | `/api/v1/ready/` | `curl --fail --cacert <instance ca.crt>` |
|---|---|---|---|
| source before the backup, 0.1.0 (`https://localhost:41443`, baseline snapshot) | 200 `{"status": "ok"}` | 200 `{"status": "ready"}` | health exit 0 right after the install |
| upgraded source, 0.1.1 (`https://localhost:41443`) | 200 `{"status": "ok"}` | 200 `{"status": "ready"}` | health and ready exit 0 |
| rollback restore, 0.1.0 (`https://localhost:42443`) | 200 `{"status": "ok"}` | 200 `{"status": "ready"}` | health and ready exit 0 |
| off-host restore, 0.1.0 (`https://localhost:43443` inside the inner engine) | 200 `{"status": "ok"}` | 200 `{"status": "ready"}` | health and ready exit 0 |

Every check used the instance's own local CA, with no system trust and no `--insecure`.

## Cleanup

[cleanup.sh](cleanup.sh), for the upgraded source (`modelanvil-local-080d2e2d1e3d`) and the rollback restore (`modelanvil-local-3420ff77e118`): `stop` exit 0, `uninstall` exit 0, then `docker volume rm` of the project's four volumes (`_artifacts`, `_caddy_config`, `_certificates`, `_database`) exit 0. Afterwards, `docker ps -a`, `docker volume ls` and `docker network ls`, filtered by each project label, listed nothing. The off-host container and volume were removed as described above. The instance, backup, record and credential directories under `$SCRATCH` were removed after the evidence was copied out. Both release directories and the `0.1.0` and `0.1.1` image tags were kept. Volumes of two older projects on this engine (`modelanvil-local-00c60ab919ac`, `modelanvil-local-6c9b31dd3e54`) and another session's `anvil026-second` container predate this run and were left alone.

## Secrets

The owner credential file held a throwaway email, a workspace name and a `secrets.token_urlsafe(24)` password. It was written mode 0600 under `$SCRATCH` and passed to the installer on standard input. `seed.py` read it to sign in, and a copy inside the off-host container did the same there; that copy was deleted before the container was removed. The credential was never printed or recorded. Before this commit, a script compared every evidence file with the owner password and with both host instances' `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` (5 values) and found none. The evidence paths were rewritten to the placeholders above. Stock gitleaks 8.28.0 (`gitleaks dir <path> --config stock-8.28.0.toml`) found no leaks in this directory or in the three code files.

## Evidence files

- [drill-report.json](drill-report.json): the drill's own report
- [baseline.json](baseline.json), [after-backup.json](after-backup.json), [after-upgrade.json](after-upgrade.json), [after-rollback.json](after-rollback.json), [offhost-snapshot.json](offhost-snapshot.json): the five snapshots
- [offhost.json](offhost.json) and [offhost.txt](offhost.txt): the off-host restore record and log
- [live-run.txt](live-run.txt): the whole locked run, without the Docker build step output
- [unit-tests.txt](unit-tests.txt): the unit test output
- [gate-build-live.sh](gate-build-live.sh), [run-all.sh](run-all.sh), [phase1.sh](phase1.sh), [seed.py](seed.py), [offhost_restore.py](offhost_restore.py), [cleanup.sh](cleanup.sh): the scripts that ran. They are evidence, not part of the package.

## What this run does not show

- No second physical machine. The off-host engine was a new `docker:dind` engine inside the same Docker Desktop VM, on the same Mac, kernel and disk. It had never held ModelAnvil, and the backup reached it by `docker cp`, not over a network. The second-machine install and drill stay with ANVIL-028.
- The data is small: a randomly initialized CPU reference transformer and one four-step run on four short texts, 0.8 MB of backup. The restore times (13.7 s, 24.5 s) and backup ages (12.5 s, 59.7 s) describe this run only. They are not a recovery-time or recovery-point claim for any customer instance.
- The 0.1.0 to 0.1.1 upgrade carried no schema migration. A rollback across a migration (restore of the paired backup with the old release) is the same procedure but was not exercised with one.
- The rollback restore ran next to the upgraded instance; nothing switched clients from one to the other. Nothing was written to the upgraded instance before the rollback backup was restored, so no post-upgrade writes were lost. In a real rollback, writes made after the upgrade backup are not in it.
- Greedy tokens were checked for the CPU reference models, the only runtime in this package.
- Inside the inner engine, `docker images -q` printed nothing after the restore, as in ANVIL-024's addendum, so that listing is not evidence. The evidence that the restore loaded release 0.1.0's own images is: the engine had 0 images before; the controller's `load_images` loads `images.tar` when an image ID is missing and then checks all three image IDs, their architecture and OS; and restore exited 0. Compose uses `pull_policy: never`.
- [installation-qualification.md](../../installation-qualification.md), [self-host-package.md](../../self-host-package.md), [self-host.md](../../self-host.md) and [deploy/selfhost/README.md](../../../../deploy/selfhost/README.md) are unchanged. They are outside this child's files. Whether this run closes the open off-host-restore and upgrade-and-rollback items in `installation-qualification.md` is QA's decision.
- The shared gates (G-local, G-skip, G-audit, G-secrets) were not run in this session; the orchestrator runs them. G-rag does not apply: this change and its evidence have no RAG numbers.
- No git tag, GitHub release, published image, public DNS or ACME. `production_qualified` is `false` in both releases, in every controller result above and in the drill report.
