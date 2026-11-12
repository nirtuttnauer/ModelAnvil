# ANVIL-067 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `ccb0f5e504fafa98b0d18574e49607a66b839c80`. This report is the following documentation commit. The commands below ran at that SHA.

`arguments()` in `modelanvil/runners/tool_schema.py` calls `tools()` before it accepts a payload. A duplicate function name, a missing name or parameters, or a schema `tools()` rejects (a boolean schema, an empty schema, or an object that does not set `additionalProperties` to false) is rejected on the `arguments()` and `parse_reply()` paths. A text-only reply stays content with an empty call list and does not become a tool call. `modelanvil/runners/test_tool_schema_bounds.py` covers those cases. `modelanvil/runners/test_tool_schema.py` and `modelanvil/runners/tool_sandbox.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:53:44+00:00 | `make premerge` | 0 | 1288 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1288, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:56:11+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:58:05+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:56:16+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output` outside this directory, then copied here. `scripts/premerge.py` records the command as `make premerge`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1288 tests in 365.050s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 117.002s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command in `pip-audit.json` is `/tmp/anvil-067/pip-audit.sh`. It runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`.

## Counts against main

Discovery on this interpreter, without executing the suite:

- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips.
- This SHA, `--exclude-tag=pg`: 1288 collected, 0 decorator skips.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run on this SHA passed 1288, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The three added tests are in `modelanvil.runners.test_tool_schema_bounds.ToolSchemaBoundTests`:

- `test_duplicate_function_names_are_rejected`
- `test_missing_name_parameters_or_required_fields_are_rejected`
- `test_text_only_reply_is_not_execution_authority`

This ticket adds no frontend test and no `pg` test. `web/` source is unchanged from `1d4ecd1`.

Main `4dd5060e632bae598003bf3a51a474709fe8c7ac`, as recorded by ANVIL-012 and ANVIL-042, passed 1285 backend tests, 249 frontend tests, and 28 PostgreSQL tests. This run is above that baseline by the three tests above. Frontend and PostgreSQL stay at 249 and 28.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command on this Linux host is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `1d4ecd1` without those variables.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` pins `pypdf==6.21.4`. That is the pin ANVIL-042 set for CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. This ticket does not change that file and adds no ignore.

## Gate G-secrets

`gitleaks` 8.30.1. This ticket does not add an allowlist and does not edit `.gitleaks.toml`. That file is the ANVIL-043 config. `gitleaks dir` and `gitleaks detect` load it from the repository.

- `gitleaks dir . --redact` exited 0 (`no leaks found`). The scan ran after the gitignored premerge outputs `web/dist` and `web/storybook-static` were removed. A scan that still included `web/storybook-static` reported one `generic-api-key` hit in a generated Storybook bundle. That path is not tracked and is not in this record.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings. None are on `ccb0f5e504fafa98b0d18574e49607a66b839c80`. The files and counts match the history section of `docs/engineering/verification/anvil-043-2026-11-11/report.md`. The 370 `generic-api-key` hits on `75e2565a83b4b0cf96aebe793a9da6823e67d165` stay under that ANVIL-043 allowlist.

## Gate G-rag

`premerge.json` stdout still contains the existing `TASK69_CONTROLS` line. This change does not add a retrieval measurement.

## Result

`make premerge` exited 0 with no runtime skip, xfail, or timeout. Duplicate function names and catalogs that `tools()` rejects are rejected before `arguments()` or `parse_reply()` can return a call. A text-only reply does not become a tool call.
