# ANVIL-063 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `facd87e1eeb1664675fd16a1a82c1245fd96d123`. This report is the following documentation commit. The commands below ran at `facd87e1eeb1664675fd16a1a82c1245fd96d123`.

`modelanvil/api/test_health_build.py` locks the health and build payloads. `GET /api/v1/health/` is the view in `modelanvil/api/views/health.py`. It returns 200 and `{"status": "ok"}`. The body has no filesystem path and no environment value. `build_info()` and the authenticated `GET /api/v1/build/` return `revision`, `source_digest`, and `protocol`, with `production_qualified` set to false. The JSON text and the Python string form contain that flag name and no readiness phrase. They do not contain an absolute workspace path or an environment value. A local edit that set the flag true failed `assertIs(..., False)`. A local edit that set `revision` to `str(Path(__file__))` failed because the payload contained the workspace path. Both edits were reverted before this commit. `modelanvil/api/views/health.py` and `modelanvil/build_info.py` are unchanged. No leak was found in those functions.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:52:08+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:44:50+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:43:34+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:43:38+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1289 tests in 341.537s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 115.342s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `exit:0` for each file. Stderr records `No known vulnerabilities found` for each file.

## Gate G-local

Label: `local`. Code SHA `facd87e1eeb1664675fd16a1a82c1245fd96d123`.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`, and against the branch base `1d4ecd1a6f1a65f159649350be5c751645e0773a`:

| Suite | main `4dd5060` and base `1d4ecd1` | this SHA | Skipped / xfail / timeout |
| --- | --- | --- | --- |
| Backend `--exclude-tag=pg` | 1285 | 1289 passed | 0 |
| Frontend `npm test` | 249 | 249 passed | 0 |
| PostgreSQL `--tag=pg` | 28 | 28 passed | 0 |

The four added tests are `HealthBuildPayloadTests.test_health_returns_ok_without_paths_or_environment_values`, `HealthBuildPayloadTests.test_build_info_includes_revision_digest_and_protocol`, `HealthBuildPayloadTests.test_authenticated_build_view_matches_build_info`, and `HealthBuildPayloadTests.test_unauthenticated_build_view_does_not_return_paths`. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `1d4ecd1`.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command passed those 28.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on main without those variables. Their bodies are unchanged.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` on this base pins `pypdf==6.21.4`. ANVIL-042 owns that pin. This run does not report CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, or CVE-2026-119209. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. The repository config is `.gitleaks.toml`, which gitleaks loads from the worktree. This ticket does not edit that file. Raw finding reports are not committed. `Secret` in a redacted report is `REDACTED`.

- `gitleaks dir . --redact` on `facd87e1eeb1664675fd16a1a82c1245fd96d123` exited 0 with `no leaks found`, 31.09 MB. Record: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. None are on `facd87e1eeb1664675fd16a1a82c1245fd96d123` or on `75e2565a83b4b0cf96aebe793a9da6823e67d165`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Record: `gitleaks-detect.json`.

ANVIL-043 owns the 370 `generic-api-key` hits introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165`. With the repository config those hits are not reported. This ticket adds no allowlist entry.

`web/storybook-static/` is gitignored build output from the premerge Storybook build. It was removed before these evidence files were added.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. This ticket does not add a retrieval measurement.

## Result

Health and build responses stay free of filesystem paths and environment values, and `production_qualified` stays false. `make premerge` exited 0: 1289 backend, 249 frontend, and 28 PostgreSQL tests passed, with no runtime skip, xfail, or timeout. `pip-audit` exited 0. `gitleaks dir` exited 0. History still reports the 36 ANVIL-017 findings.
