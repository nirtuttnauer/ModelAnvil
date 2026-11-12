# ANVIL-077 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `8b7e47e1dd6da1281a869d4f49118175e4265d14`. This report is the following documentation commit. The commands below ran at `8b7e47e1dd6da1281a869d4f49118175e4265d14`.

The published OpenAPI document already defines version `3.1.0`, the path `/health/`, and the component `ApiErrorEnvelope`. `modelanvil/api/test_openapi_envelope.py` loads that document with `contracts.schemas.load_schema`, the same call `openapi_spec` makes, and reads the file `schema_path` returns. The test opens no socket. `contracts/errors.py`, `contracts/validate.py`, and `modelanvil/api/test_openapi.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:54:04+00:00 | `make premerge` | 0 | 1288 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1288, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:46:36+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:45:03+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-8.28-dir-stock.json` | 2026-11-12T14:45:04+00:00 | `gitleaks` 8.28.0 `dir` with the upstream 8.28.0 config | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-8.30-dir-stock.json` | 2026-11-12T14:45:06+00:00 | `gitleaks` 8.30.1 `dir` with the upstream 8.30.1 config | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-8.30-detect-75e2565.json` | 2026-11-12T14:45:07+00:00 | `gitleaks` 8.30.1 `detect` on `75e2565` with the upstream 8.30.1 config | 1 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. This run wrote `/tmp/anvil077-evidence/premerge.json` so it would not replace `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1288 tests in 398.732s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 127.283s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. `DATABASE_PASSWORD` is absent from the record. `HF_HUB_OFFLINE=1` was set for the PostgreSQL run after the pinned caches were filled.

## Gate G-local

Label: `local`. Code SHA `8b7e47e1dd6da1281a869d4f49118175e4265d14`.

Discovery on this host, without executing the suite:

- `4dd5060e632bae598003bf3a51a474709fe8c7ac` is the count recorded by the ANVIL-012 and ANVIL-042 premerge runs on this class of host: 1285 backend, 249 frontend, 28 PostgreSQL, 0 skipped.
- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips. `--tag=pg`: 28 collected.
- This SHA, `--exclude-tag=pg`: 1288 collected, 0 decorator skips. The executed premerge run passed 1288, 249, and 28.

The three added tests are `OpenApiEnvelopeTests.test_document_is_valid_json_with_openapi_major_3`, `OpenApiEnvelopeTests.test_health_path_remains_defined`, and `OpenApiEnvelopeTests.test_error_envelope_component_remains_defined`. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `1d4ecd1`.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `1d4ecd1` without those variables. Their bodies are unchanged.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` on this tree pins `pypdf==6.21.4`, the pin ANVIL-042 landed. This run does not report CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, or CVE-2026-119209. No ignore was added. This ticket does not edit a requirements file.

## Gate G-secrets

`gitleaks` 8.30.1 `dir . --redact` loads the repository `.gitleaks.toml` from ANVIL-043. It scanned 34.77 MB and exited 0 (`no leaks found`). Console: `gitleaks-dir.json`. This ticket does not edit that file and does not add an allowlist.

Stock configuration means the upstream `config/gitleaks.toml` for that gitleaks version, passed with `--config`, on a copy of `git archive HEAD` that does not contain `.gitleaks.toml`. Raw finding reports are not committed.

- `gitleaks` 8.28.0, stock, `dir`: 0 findings. Console: `gitleaks-8.28-dir-stock.json`.
- `gitleaks` 8.30.1, stock, `dir`: 370 findings. Console: `gitleaks-8.30-dir-stock.json`.
- `gitleaks` 8.30.1, stock, `detect` limited to `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 1 commit scanned, 370 findings. Console: `gitleaks-8.30-detect-75e2565.json`.

Those 370 findings are the decoded `generic-api-key` hits ANVIL-043 triaged. They were introduced by `75e2565`. None were added by `8b7e47e`.

`make premerge` then wrote gitignored `web/storybook-static/`. A `gitleaks dir .` while that directory was on disk found one `generic-api-key` hit in `web/storybook-static/assets/iframe-D36Q5PRP.js`. That directory is Storybook build output. It was removed and is not in the commit. After removal, `gitleaks dir .` on the working tree, including this evidence directory, scanned 36.42 MB and exited 0. The same command on `docs/engineering/verification/anvil-077-2026-11-12` exited 0.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

The served OpenAPI document parses as JSON, its `openapi` major version is 3, `/health/` stays defined, and `ApiErrorEnvelope` stays defined. `make premerge` exited 0 with no runtime skip, xfail, or timeout. Counts are above `4dd5060` and above `1d4ecd1` by the three new tests. `pip-audit` exited 0. `gitleaks dir` exited 0. The 370 stock findings stay on `75e2565` and stay with ANVIL-043.
