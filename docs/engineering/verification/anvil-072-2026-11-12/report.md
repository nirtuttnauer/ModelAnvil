# ANVIL-072 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json` and were written by `.venv/bin/python scripts/local_evidence.py` or `scripts/premerge.py` from an empty `git status --porcelain`.

The measured tree is `1378219008a155208f04a099de1b294a8e06805a`. This report is the following docs commit. Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`. The count floor named for this ticket is `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

## Change

`modelanvil/core/test_tenancy_context.py` covers the active-tenant context contract:

- After `set_active_tenant` and `set_active_project`, `get_active_tenant` and `get_active_project` return those values.
- `reset_context()` clears the tenant, project, and bound request. The getters return `None`, the unscoped default documented on `get_active_tenant` and `get_active_project`.
- A second set after `reset_context()` returns the new tenant and project. The values from before the reset are not returned.
- `bind_request` on a later request, after `reset_context()`, does not keep the previous tenant.

`reset_context()` in `modelanvil/core/tenancy.py` already sets the three context variables to `None`. These tests pass with that function unchanged. `modelanvil/core/test_tenancy_queryset.py`, `modelanvil/core/middleware.py`, `modelanvil/identity/`, and `modelanvil/settings.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:50:41+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `make-check.json` | 2026-11-12T14:53:42+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-12T14:54:48+00:00 | `pip-audit -r` on every `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:53:44+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:53:45+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output docs/engineering/verification/anvil-072-2026-11-12/premerge.json`. The record's command field is `make premerge`. Backend result: `Ran 1289 tests in 314.748s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 112.606s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. `make check` printed `System check identified no issues (0 silenced).`

## Counts against main

Discovery with this interpreter, without executing the suite:

- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, default runner: 1285 collected. The runner excludes the `pg` tag on this host.
- This SHA: 1289 collected.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run passed 1289, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The four added tests are `TenancyContextTests.test_set_active_tenant_and_project_are_returned_by_getters`, `TenancyContextTests.test_reset_context_clears_tenant_and_project_to_unscoped`, `TenancyContextTests.test_second_set_after_reset_does_not_see_the_first_tenant`, and `TenancyContextTests.test_next_request_after_reset_does_not_keep_the_previous_tenant`. This ticket adds no frontend test and no `pg` test.

`4dd5060e632bae598003bf3a51a474709fe8c7ac` executed 1285, 249, and 28. This SHA is above that floor on the backend suite and level with it on the frontend and PostgreSQL suites. It is also above current `origin/main` `1d4ecd1` by the four tests named above. `1d4ecd1` did not add a backend, frontend, or `pg` test after `4dd5060`.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `1d4ecd1` and on `4dd5060` without those variables.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0. Each stderr line is `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` on this base pins `pypdf==6.21.4`. The scan does not report CVE-2026-119203 through CVE-2026-119209. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. The scan uses the repo file `.gitleaks.toml` already on `1d4ecd1`. This ticket does not edit that file and does not add an allowlist entry.

- `gitleaks dir . --redact` exited 0, `no leaks found`, 35.99 MB. Record: `gitleaks-dir.json`.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. None are on `1378219008a155208f04a099de1b294a8e06805a` or under `test_tenancy_context.py`. The paths and counts match the 36 history findings ANVIL-043 left in place: `modelanvil/runners/training/hf_runtime.py` (7), `scripts/audio_candidate_infer.py` (7), `modelanvil/runners/training/audio_runtime.py` (4), `scripts/vlm_candidate_infer.py` (4), `modelanvil/runners/training/vlm_math.py` (4), `modelanvil/runners/training/audio_math.py` (3), `scripts/verify_cpu_export.py` (3), and one each in `docs/engineering/verification/manual-qa-2026-10-12/local-workflows.md`, `modelanvil/core/test_selfhost.py`, `modelanvil/rag/chunking.py`, and `modelanvil/context_lab/test_context_lab.py`. ANVIL-043 records those fingerprints on `reviews/ANVIL-017-gitleaks-history.md`. Record: `gitleaks-detect.json`.

The 370 `generic-api-key` findings introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165` are owned by ANVIL-043. With the allowlist already on main, this dir scan reports 0 and this history scan does not include those 370. No allowlist was added here.

`web/storybook-static/` from the Storybook build was removed before the dir scan. It is gitignored build output and is not in the commit.

## Result

`make premerge` exited 0. Backend 1289, frontend 249, and PostgreSQL 28 passed, with no runtime skip, xfail, or timeout. `pip-audit` exited 0 on all 11 requirement files. `gitleaks dir` exited 0. The pull request stays open.
