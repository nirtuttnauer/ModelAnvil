# ANVIL-064 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`. Comparison baseline named by the ticket: `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

The measured tree is `6cecd13bb013e05cba0f32f673a3e360df4d743c`. This report is the following documentation commit. The commands below ran at `6cecd13bb013e05cba0f32f673a3e360df4d743c`.

## What changed

`modelanvil/artifacts/tombstones.py` refused a tombstoned resource only when a `DeletionTombstone` row matched the exact `resource_id` string. The probe in [before.txt](before.txt) recorded the fail-open paths on that code:

- An unknown artifact UUID, a blank id, `None`, and a blank tenant or resource type made `enforce_resource_active` return `None`.
- `register_tombstone` for `""` or `"not-a-uuid"` raised `ValueError: Field 'id' expected a number` from the primary-key lookup and wrote no tombstone. A later check still allowed the id.
- `register_tombstone` for `None` stored the literal resource id `None`.
- Registering by the artifact primary key marked the artifact `tombstoned`, but `enforce_resource_active` on the public artifact id returned `None`.
- `Artifact.tombstone()` alone left `is_resource_tombstoned` false and `enforce_resource_active` returned `None`.

After the change, missing identifiers raise `django.core.exceptions.PermissionDenied` and `is_resource_tombstoned` is true. An artifact id that does not resolve is refused. Registering an unresolvable artifact id records a tombstone instead of raising from the lookup. A tombstoned artifact is refused by its public id, its primary key, and after `Artifact.tombstone()` with no separate row. A committed artifact that has not been tombstoned still passes. A non-artifact id with no tombstone row still passes; that is the documented check for resource types this module cannot resolve, and `modelanvil/ops/tombstones.py` was not edited. Refusal stays `PermissionDenied`. No HTTP status was added. No storage backend is used.

`modelanvil/artifacts/test_tombstone_failclosed.py` covers those paths. `modelanvil/artifacts/test_tombstones.py` was not edited. The existing two tests still pass.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:50:55+00:00 | `make premerge` | 0 | 1293 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1293, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:43:58+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:42:41+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:42:43+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` was `.venv/bin/python scripts/premerge.py --output /tmp/anvil064/premerge.json`. The record's command field is `make premerge`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1293 tests in 321.640s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 118.002s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for the PostgreSQL run after the pinned caches were filled.

The audit command was `/tmp/anvil064/pip-audit.sh`. It runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `exit 0` for each of the 11 files. Stderr records `No known vulnerabilities found` for each file.

## Gate G-local

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`, from the ANVIL-012 premerge record: 1285 backend, 249 frontend, 28 PostgreSQL, 0 skipped.

This run passed 1293, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The eight added tests are in `modelanvil.artifacts.test_tombstone_failclosed`:

- `test_artifact_id_from_another_tenant_fails_closed`
- `test_direct_artifact_tombstone_fails_closed`
- `test_missing_identifiers_fail_closed`
- `test_primary_key_registration_refuses_the_public_artifact_id`
- `test_registered_artifact_is_tombstoned_and_refused`
- `test_registered_non_artifact_is_tombstoned_and_refused`
- `test_unknown_artifact_id_fails_closed`
- `test_unresolved_artifact_id_registration_still_tombstones`

This ticket adds no frontend test and no `pg` test. `1d4ecd1` is 1285 backend tests before these eight. 1293 is above 1285.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `4dd5060` without those variables.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command excludes `pg` before the run and lists those 28 IDs. The PostgreSQL command runs those 28.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` on this tree pins `pypdf==6.21.4`. That pin is the ANVIL-042 fix for CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. This run does not report those CVEs. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No new allowlist was added, and `.gitleaks.toml` was not edited. gitleaks loads the config already on main from ANVIL-043. The raw finding report is not committed.

- `gitleaks dir . --redact` at `6cecd13bb013e05cba0f32f673a3e360df4d743c` exited 0, `no leaks found`, 31.10 MB. Record: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0. Findings on `6cecd13bb013e05cba0f32f673a3e360df4d743c`: 0. The 36 that remain are the history findings ANVIL-043 left in place. Record: `gitleaks-detect.json`.

`web/storybook-static/` from the premerge build was removed before this evidence was written. It is gitignored and is not in the commit.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is the existing small correctness check. This change does not claim a new RAG number.

## Result

Missing, unknown, and mismatched artifact ids fail closed with `PermissionDenied`. `make premerge` exited 0 with no runtime skip, xfail, or timeout. Counts are above main `4dd5060`. `pip-audit` exits 0 with no ignore. `gitleaks dir` exits 0. History findings on `75e2565` stay with ANVIL-043. No allowlist was added.
