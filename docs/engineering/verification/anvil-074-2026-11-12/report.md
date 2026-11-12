# ANVIL-074 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. `gitleaks` 8.30.1. `pip-audit` 2.10.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. Test, audit, and gitleaks records were written by `.venv/bin/python scripts/local_evidence.py` or `.venv/bin/python scripts/premerge.py` from a clean `git status --porcelain`.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The tests and the commands below ran at `e8ed4010760fd6771171d68a0486114f278c7381`. This report is the following documentation commit. Adding these files changes the PR head by one commit.

## Change

`modelanvil/jobs/test_access.py` covers `accessible_jobs()`:

- With no active tenant, the queryset is empty. The stored job remains in the database.
- With a tenant and an active project, a job in the caller project does not appear when its training run, evaluation run, or alignment run belongs to another project in that tenant.
- A job in the caller project with no hidden owner appears. A job whose training run is in the caller project appears.

`modelanvil/jobs/access.py` is unchanged. Those cases already hold.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T15:01:29+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:45:29+00:00 | `bash /tmp/anvil074-pip-audit.sh` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:44:25+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:44:28+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output /tmp/anvil074/premerge.json` with Node v24.22.3 at the front of `PATH`. `scripts/premerge.py` records the command as `make premerge`. Backend: `Ran 1289 tests in 328.515s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 115.676s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for the PostgreSQL run after the pinned caches were filled.

## Gate G-local

Discovery with this interpreter, without executing the suite. The non-PostgreSQL runner excludes the `pg` tag:

- `1d4ecd1a6f1a65f159649350be5c751645e0773a`: 1285 collected, 28 `pg`.
- `e8ed4010760fd6771171d68a0486114f278c7381`: 1289 collected, 28 `pg`.

The four added IDs are `AccessibleJobsTests.test_no_active_tenant_returns_no_jobs`, `test_hidden_training_run_job_is_omitted_and_accessible_jobs_remain`, `test_hidden_evaluation_run_job_is_omitted`, and `test_hidden_alignment_run_job_is_omitted`. This ticket adds no frontend test and no `pg` test.

The executed premerge run passed 1289, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. That backend count is above the 1285 recorded for `4dd5060` in the ANVIL-012 and ANVIL-043 evidence. Frontend stays at 249. PostgreSQL stays at 28.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. They are the same two IDs recorded on `1d4ecd1`.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, and `requirements.vision.txt`.

`requirements.documents.txt` pins `pypdf==6.21.4`. That pin is already on `1d4ecd1`. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No new config, baseline, or allowlist. The committed `.gitleaks.toml` from ANVIL-043 is the config gitleaks loads from the worktree. This ticket does not edit it. Raw reports are not committed.

- `gitleaks dir . --redact` at `e8ed401` scanned 31.10 MB and exited 0 (`no leaks found`). That scan ran before `web/storybook-static/` existed. The directory is gitignored build output. It was removed after premerge. Record: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. None are on `e8ed401` or `1d4ecd1`. Record: `gitleaks-detect.json`.

The 370 `generic-api-key` findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165` are the set ANVIL-043 allowlisted. They are not in this detect result.

## Result

`accessible_jobs()` returns nothing when no tenant is active. A job stays out of the result when its training, evaluation, or alignment run is outside the caller project. A job the caller can access is returned. `make premerge` exited 0 with no runtime skip, xfail, or timeout. `pip-audit` exited 0. `gitleaks dir` exited 0. No allowlist and no audit ignore were added.
