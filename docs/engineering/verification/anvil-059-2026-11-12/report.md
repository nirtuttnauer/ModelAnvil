# ANVIL-059 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `47769bba7896f300de48696d839b351000a8ae9d`. This report is the following documentation commit. The commands below ran at `47769bba7896f300de48696d839b351000a8ae9d`.

`modelanvil/core/test_pagination.py` checks the public cursor paginator. `page_size` is 50, `max_page_size` is 200, and `page_size_query_param` is `page_size`. The class is `rest_framework.pagination.CursorPagination`, and it is neither `LimitOffsetPagination` nor `PageNumberPagination`. `get_paginated_response` returns `results`, `next`, and `previous`. An in-memory list of 250 rows, requested with `page_size=1000`, returns 200 rows. The `next` link carries a base64 `cursor` query parameter and continues at the remaining 50 rows, with no `offset`, `limit`, or `page` parameter. The bounds in `modelanvil/core/pagination.py` already match those checks, so that file is unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:50:42+00:00 | `make premerge` | 0 | 1288 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1288, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:43:33+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:42:28+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:42:31+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` was `.venv/bin/python scripts/premerge.py --output /tmp/anvil059-evidence/premerge.json`. The record's command field is `make premerge`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1288 tests in 337.421s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 116.659s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The three added tests are `CursorPaginationTests.test_bounds_use_cursor_pagination`, `CursorPaginationTests.test_paginated_response_includes_results_next_and_previous`, and `CursorPaginationTests.test_requested_page_size_above_max_is_capped_and_cursor_is_opaque`.

## Gate G-local

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`: the ANVIL-012, ANVIL-042, and ANVIL-043 premerge records passed 1285 backend tests, 249 frontend tests, and 28 PostgreSQL tests, with 0 skipped. This run passed 1288, 249, and 28. That is three more backend tests than 1285, and the same frontend and PostgreSQL counts.

`origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a` differs from `4dd5060` in these test files: `modelanvil/api/test_dataset_preparation_http.py` (the pypdf pin assertion), `modelanvil/runners/alignment/test_grpo.py` (a `linux` tag), and `tests/test_premerge.py` (not collected by `manage.py test`). Those commits add no Django test method. On this Linux host the backend command is `--exclude-tag=pg`, so the `linux` tag stays in the run.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command excludes `pg` before the run. `premerge.json` lists the 28 excluded IDs, and `manage.py test --noinput --tag=pg` passed those 28.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `4dd5060` without those variables.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` pins `pypdf==6.21.4`. ANVIL-042 moved that pin from 6.21.2, the version that carried CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. This run does not report those CVEs. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. `gitleaks dir . --redact` loads the repository `.gitleaks.toml` from ANVIL-043 and exited 0 with `no leaks found`. Record: `gitleaks-dir.json`. This ticket does not edit `.gitleaks.toml` and adds no allowlist.

`gitleaks detect --redact --log-opts=--all` exited 1 with 36 findings, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Findings on `47769bba7896f300de48696d839b351000a8ae9d`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0. Record: `gitleaks-detect.json`.

A stock-config `gitleaks dir` (gitleaks 8.30.1 `config/gitleaks.toml`, passed with `--config`) still reports 370 `generic-api-key` findings. The path and line of each finding match `docs/engineering/verification/anvil-043-2026-11-11/findings.json`. ANVIL-043 owns those 370 hits from `75e2565`. None are in `modelanvil/core/test_pagination.py`. The raw stock report is not committed.

## Result

`make premerge` exited 0. Backend 1288, frontend 249, and PostgreSQL 28 passed, with no runtime skip, xfail, or timeout. `pip-audit` exited 0 with no ignore. `gitleaks dir` exited 0. The pull request stays open.
