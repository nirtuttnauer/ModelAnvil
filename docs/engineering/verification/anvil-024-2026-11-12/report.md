# ANVIL-024: version file and one install script

Label: `local`. This run used the Docker Desktop Linux VM on Nir's Mac. It was not a fresh VM and not a second machine. It does not stand in for the fresh-VM or second-machine install that ANVIL-028 records.

- Date: 12 November 2026 (UTC times below)
- Code commit built and installed: `fe9a94c5d04e82769f87217672b9ef3eb58beb9c` on `claude/anvil-024-selfhost-install`, parent `56b35cc` (`origin/main`). `git status --porcelain` was empty before the build and before the installs.
- This report is the docs-only commit that follows `fe9a94c`.
- Machine: Apple M5 Pro, 48 GiB, macOS 27.0.1 (26A434). Docker Desktop 4.98.0 (245422), client and engine 29.9.2, engine `linux/arm64`, kernel `7.0.14-linuxkit`, VM `MemTotal` 8317202432. Docker Compose v5.6.1. The installer and controller ran on `/usr/bin/python3` 3.9.6. The builder and the tests ran on Python 3.12.15.

Paths used below:

- `$WT` = the `claude/anvil-024-selfhost-install` worktree
- `$RELEASE` = `~/.cache/modelanvil-selfhost/releases/0.1.0` (kept)
- `$SCRATCH` = a private session scratch directory; the instance directories, the credentials and the tampered copy were removed

## What changed in `fe9a94c`

- `deploy/selfhost/VERSION`: one line, `0.1.0`. It matches `[a-z0-9][a-z0-9.-]{0,79}`, the pattern the builder and `release()` enforce.
- `scripts/build_selfhost_release.py`: with `--version` omitted, the builder reads `VERSION` and refuses it unless it is exactly one line matching the pattern. An explicit `--version` still wins. The refusals for an existing output directory, a dirty worktree, an engine that is not Linux arm64, and an existing image tag are unchanged and run in the same order. The old default, `cpu-` plus 12 hex characters of `HEAD`, is gone.
- `scripts/install_selfhost.py`: takes `--directory`, `--release`, `--host`, `--bind`, `--http-port`, `--https-port` and `--credentials-stdin`. It refuses a missing release directory, or one without `modelanvil.py` and `release.json`, with exit code 2. Otherwise it runs `<release>/modelanvil.py install --directory ... --release <release>` plus only the flags the operator passed, and returns the controller's exit code. Standard input goes straight to the controller. The script builds no image, pulls no image and never calls `deploy/production`. It runs on Python 3.9.
- `modelanvil/core/test_selfhost.py`: 7 new Docker-free tests (listed below).

The ANVIL-025 entry in [self-host-package.md](../../self-host-package.md) names `scripts/test_install_selfhost.py` for the install tests. The Django `DiscoverRunner` does not collect `scripts/`, which has no `__init__.py` ([anvil-014 local record](../anvil-014-paid-defaults/local.md) notes the same). So the install tests sit next to the existing installer tests in `modelanvil/core/test_selfhost.py`, the file named for ANVIL-024, where `manage.py test` runs them.

## Unit tests

Only this module was run, under the host test lock:

```sh
cd $WT && testlock.sh env -u DATABASE_ENGINE DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=$WT \
  DATABASE_NAME=$SCRATCH/db.sqlite3 DATABASE_TEST_NAME=$SCRATCH/test.sqlite3 \
  <python 3.12 venv>/bin/python manage.py test modelanvil.core.test_selfhost --noinput -v 2
```

Exit 0. `Ran 16 tests in 1.020s`, `OK`, no skips. Before this change the module had 9 tests; the 7 new ones are:

- `InstallScriptTests.test_missing_release_directory_is_refused_before_any_controller_runs`: a missing directory and a directory with no `modelanvil.py`/`release.json` both return 2, no process starts and no instance directory is created.
- `InstallScriptTests.test_release_controller_receives_exactly_the_install_flags`: checks the exact argument list with all flags, and with only `--directory` and `--release` (the release controller's defaults then apply). Also checks that the controller's exit code is passed through.
- `InstallScriptTests.test_tampered_release_file_fails_the_install_through_the_controller_checksum`: runs `scripts/install_selfhost.py` as a real process against a release that holds the real controller. A stand-in `docker` on `PATH` answers only the controller's four engine probes and refuses everything else. The intact release passes every checksum and reaches the load of its own `images.tar`, with no pull or build. A copy with one byte of `images.tar` flipped (same size) exits 1 with `Release checksum failed: images.tar`. No instance directory is created and no Docker call runs after the probes.
- `InstallScriptTests.test_two_installs_generate_different_secrets_that_match_no_repository_default`: runs the controller's `install` twice, with Docker calls stubbed. The two installs get different `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` values. None of them equals a default or example value collected from `compose*.yaml`, `deploy/*/compose*.y*ml`, `deploy/*/docker-compose*.y*ml`, `deploy/*/.env.example`, `.github/workflows/*.yml`, or `INSECURE_DEFAULT_SECRET_KEY`. The test also checks that the collection found the repository's known example values, so an empty collection cannot pass.
- `ReleaseVersionTests.test_version_file_is_one_line_the_builder_and_controller_accept`
- `ReleaseVersionTests.test_builder_names_the_release_from_the_version_file_unless_version_is_passed`: with git and the engine stubbed, the first Docker command is `image inspect modelanvil-selfhost-api:<VERSION>`, or `:explicit-2` when `--version explicit-2` is passed. The existing-tag refusal stops the run there, so no image is built.
- `ReleaseVersionTests.test_builder_refusals_still_stop_before_any_image_build`: covers an existing output directory, a dirty worktree, an amd64 engine, an uppercase `--version`, and a `VERSION` file that is invalid, has two lines, or is empty.

## Live build

```sh
cd $WT && <python 3.12 venv>/bin/python scripts/build_selfhost_release.py --output $RELEASE
```

`--version` was omitted, so the version came from `deploy/selfhost/VERSION`. The build ran 14:01:05Z–14:08:03Z and exited 0. The only stderr was Docker's legacy-builder deprecation notice, printed once per image target, because the controller's isolated Docker config exposes only the Compose plugin. The last stdout line reported version `0.1.0`, source revision `fe9a94c5d04e82769f87217672b9ef3eb58beb9c`, three image IDs (api, web, db) and `offline_bytes` 349774336.

`release.json` records `schema_version` `modelanvil.selfhost-release.v1`, `version` `0.1.0`, `architecture` `arm64`, `os` `linux` and `production_qualified` `false`. Its files, with SHA-256 in 8-character groups so a stock `gitleaks` scan does not read them as keys:

| File | Bytes | SHA-256 |
|---|---:|---|
| `LICENSE` | 1070 | `49c10de9 3c7da966 e8196f4f a81969f9 e95f7f34 eae8c13e 9a981a97 ce53d714` |
| `README.md` | 8678 | `9e468c37 3f8a9357 8f9d3a32 5535820e ac820f71 029d08d7 efe56a94 45b1a662` |
| `compose.yaml` | 3221 | `eb782b24 4d90c2cc 058f7c88 107130a6 336588bd ee76a301 81f12551 1834053c` |
| `images.tar` | 349774336 | `144932c4 6721d3f2 efe91810 6e22ddea d2e6705e 41bb9024 837ca690 45814d67` |
| `modelanvil.py` | 22054 | `32e77635 d8cbd064 cd64ee09 9c8c2ce9 ed2c0dfc 25aca494 802d3430 0b50af81` (same as `deploy/selfhost/modelanvil.py` at `fe9a94c`) |
| `reference.json` | 17805 | `4f029379 dff4f607 760f12e8 db96d0be 054ceb6d a4184938 f099f961 c5123234` |
| `requirements.selfhost.lock.txt` | 805 | `47a2a234 728cb2eb 30a620ad cdcfda1b b6869ec5 61623ebc 96c28285 f1e7804d` |

The build left the tags `modelanvil-selfhost-api:0.1.0` and `modelanvil-selfhost-web:0.1.0` on this engine. The builder will refuse to rebuild `0.1.0` here. The next release needs a new `VERSION` or an explicit `--version`.

## Two installs

Each owner credential file held a throwaway email, workspace name and a `secrets.token_urlsafe(24)` password. The files were written mode 0600 to a private scratch directory and removed afterwards. No credential or secret value was printed or recorded.

```sh
/usr/bin/python3 $WT/scripts/install_selfhost.py --directory $SCRATCH/live/instance-a --release $RELEASE \
  --http-port 18080 --https-port 18443 --credentials-stdin < <owner-a credentials>
/usr/bin/python3 $WT/scripts/install_selfhost.py --directory $SCRATCH/live/instance-b --release $RELEASE \
  --http-port 28080 --https-port 28443 --credentials-stdin < <owner-b credentials>
```

| Install | Exit | Seconds | Controller result |
|---|---:|---:|---|
| A | 0 | 17.9 | origin `https://localhost:18443`, `ready` true, version `0.1.0`, `production_qualified` false |
| B | 0 | 17.9 | origin `https://localhost:28443`, `ready` true, version `0.1.0`, `production_qualified` false |

Compose projects: `modelanvil-local-a7cf9659dbae` (A) and `modelanvil-local-0ed3435685da` (B).

## Health

```sh
curl --fail --cacert $SCRATCH/live/instance-a/ca.crt https://localhost:18443/api/v1/health/
curl --fail --cacert $SCRATCH/live/instance-b/ca.crt https://localhost:28443/api/v1/health/
```

| Install | Exit | Body |
|---|---:|---|
| A | 0 | `{"status": "ok"}` |
| B | 0 | `{"status": "ok"}` |

Each check used that instance's own local CA, with no system trust and no `--insecure`.

## Secret comparison

A script read both `.env` files and printed only booleans and counts:

- `DJANGO_SECRET_KEY` differs between A and B: true. `POSTGRES_PASSWORD` differs: true.
- Any value equal to a repository default or example value: false (21 values compared).
- Within each instance, the secret key equals the database password: false, false.
- Lengths: `DJANGO_SECRET_KEY` 86 characters and `POSTGRES_PASSWORD` 43 characters in both instances.
- Both `.env` files are mode `0600`. No secret value was printed.

The 21 default and example values came from `.github/workflows/ci.yml`, `compose.dataset-tests.yaml`, `compose.isolated-eval.yaml`, `compose.premerge.yaml`, `compose.yaml`, `deploy/compose/.env.example`, `deploy/compose/docker-compose.yml`, `deploy/production/.env.example`, `deploy/production/compose.yaml`, `deploy/selfhost/compose.yaml`, and `INSECURE_DEFAULT_SECRET_KEY` in `modelanvil/core/checks.py`. The scan used the same rules as the unit test.

## Negative test: tampered release

A copy of `$RELEASE` was made in the scratch directory. One byte of `images.tar` at offset 174887168 was flipped. The size stayed 349774336 and the SHA-256 changed.

```sh
/usr/bin/python3 $WT/scripts/install_selfhost.py --directory $SCRATCH/live/instance-refused --release $SCRATCH/tampered-release \
  --http-port 38080 --https-port 38443 --credentials-stdin < <owner credentials>
```

Exit 1 after 0.6 s. Stderr: `ModelAnvil: Release checksum failed: images.tar`. `instance-refused` was not created. `docker events --filter type=image`, streamed for the whole install, recorded no image events. As a control, the same stream recorded `tag` and `untag` for a temporary `anvil024-event-control:1` tag on the API image, which was removed straight away.

## Cleanup

```sh
/usr/bin/python3 $SCRATCH/live/instance-a/release/modelanvil.py stop --directory $SCRATCH/live/instance-a        # exit 0
/usr/bin/python3 $SCRATCH/live/instance-a/release/modelanvil.py uninstall --directory $SCRATCH/live/instance-a   # exit 0
/usr/bin/python3 $SCRATCH/live/instance-b/release/modelanvil.py stop --directory $SCRATCH/live/instance-b        # exit 0
/usr/bin/python3 $SCRATCH/live/instance-b/release/modelanvil.py uninstall --directory $SCRATCH/live/instance-b   # exit 0
```

`uninstall` keeps the data volumes by design. After it, the four volumes of each test project (`<project>_artifacts`, `_caddy_config`, `_certificates`, `_database`) were removed with `docker volume rm` (exit 0). `docker ps -a`, `docker volume ls` and `docker network ls` filtered by each project label then listed nothing. The live instance, credentials and tampered-copy directories were removed. `$RELEASE` and the two `0.1.0` image tags were kept for the next ticket. Volumes of two older projects on this engine (`modelanvil-local-00c60ab919ac`, `modelanvil-local-6c9b31dd3e54`) predate this run and were left alone.

## What this run does not show

- It does not show a fresh VM, a clean OS or a second machine. The engine is the Docker Desktop VM on the same Mac that built the release. ANVIL-028 records the second-machine install.
- It does not show the load from `images.tar` on an engine that lacks the images. The build had already left the release images on this engine. A `docker events --since/--until` query over the install window returned nothing, but that is not evidence: the engine keeps only its last 256 events, and the healthcheck exec events had already pushed out the start of install A. That result is not claimed. The only live image-event stream covered the tampered install. Compose `pull_policy: never`, the controller's image-ID check and the stand-in-engine unit test are the evidence that install does not pull.
- The ticket's `install.sh <release>` is `scripts/install_selfhost.py`, as in the approved split. The script downloads nothing. The release controller checks every listed release file's size and SHA-256 against `release.json`, and the negative test above shows that a wrong hash stops the install.
- No public DNS, ACME, git tag, GitHub release or published image. `production_qualified` stays `false` in the builder, the controller and this release.
- The full suites and the shared gates are recorded in [gates.md](gates.md).
- `deploy/selfhost/README.md`, `docs/engineering/self-host.md` and `docs/engineering/self-host-package.md` are unchanged; they are outside this ticket's file limits. `self-host-package.md` is the dated plan and still describes the old `cpu-<sha>` default.

## Addendum: install on a fresh Docker engine (12 November 2026)

The live installs above ran on an engine that already held the release images. This check runs `scripts/install_selfhost.py` on a Docker engine that has never seen ModelAnvil, so the install has to load `images.tar` itself.

- Script: [fresh-engine-install.sh](fresh-engine-install.sh). It starts a new privileged `docker:dind` container (image pinned by digest, the same one ANVIL-029 used) with a new, empty `/var/lib/docker` volume. It mounts release `0.1.0` read-only and the scripts from `76fe094` (`main` after #122). Then it installs `python3` and `curl` in the container, runs `python3 /scripts/install_selfhost.py --directory /work/instance --release /release --http-port 18080 --https-port 18443 --credentials-stdin`, and finally runs `curl --fail --cacert /work/instance/ca.crt https://localhost:18443/api/v1/health/`. It ran under the host test lock.
- Output: [fresh-engine-install.txt](fresh-engine-install.txt). Before the install, the inner engine had 0 images and 0 volumes. The install exited 0 in 21 s with `ready: true`, version `0.1.0`, and `production_qualified: false`. Health returned `{"status": "ok"}`, and curl exited 0. `stop` and `uninstall` exited 0, and the container and its volume were then removed.
- The throwaway owner credentials were generated inside the container with `secrets.token_urlsafe(24)`, used from a 0600 file there, and deleted with the container. They were never printed or recorded.

This is a fresh engine inside the Docker Desktop VM on Nir's Mac, a reset environment that never held ModelAnvil. It is not a separate physical machine. The second-machine install stays with ANVIL-026 and ANVIL-028.
