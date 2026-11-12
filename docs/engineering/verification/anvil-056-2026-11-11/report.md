# ANVIL-056 local evidence, 11 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each recorded command started.

The measured tree is `462faab0e9752a561d779b94326feedac57fe2ad`. This report is the following documentation commit. The commands below ran at that SHA.

Base at measurement: `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-11T22:21:33+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-11T22:15:25+00:00 | `pip-audit -r` on every `requirements*.txt` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-8.28-dir.json` | 2026-11-11T22:15:33+00:00 | `gitleaks 8.28.0 dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-11T22:14:06+00:00 | `gitleaks 8.30.1 dir . --redact` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-11T22:15:41+00:00 | `gitleaks 8.30.1 detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by:

```sh
.venv/bin/python scripts/premerge.py --output /tmp/anvil056-evidence/premerge.json
```

`scripts/premerge.py` records the command as `make premerge`. The `--output` path keeps the run from writing `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Node 24.22.3 was at the front of `PATH`. Backend result: `Ran 1289 tests in 309.917s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then `npm run build` and `npm run build-storybook`. PostgreSQL: `Ran 28 tests in 116.180s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

## What the tests cover

`contracts/test_validate.py` loads the canonical sample-envelope schema through `contracts.schemas.load_schema` and calls `validate_envelope`. The document is the minimal envelope already used by the data-registry contract test. No new schema file. No network.

| Criterion | Result |
| --- | --- |
| Missing `schema_version` is rejected | `SchemaVersionWindowTests.test_missing_schema_version_is_rejected` raises `InvalidDocumentError` with `validation_failed`, which is in `ErrorCode.ALL`. The detail text names `schema_version`. |
| A malformed version is rejected | `test_malformed_schema_version_is_rejected` rejects `v1.0` with `schema_version_unsupported`. |
| A major outside the CONTRACTS window is rejected with a stable code | `test_major_outside_contracts_window_is_rejected` builds `2.0` and `0.0` from the sample-envelope window `1.0`..`1.0`. Both raise `InvalidDocumentError` with status 422. `to_api_error` maps the code to `schema_version_unsupported`. |
| A minimal valid document inside the window is accepted | `test_minimal_document_inside_window_is_accepted` accepts the schema `const` `1.0` and returns the same document. |

`contracts/validate.py`, `contracts/versioning.py`, and `contracts/errors.py` are unchanged. The version check already rejected these documents.

## Counts against main `4dd5060`

Discovery with this interpreter, without executing the suite:

- `4dd5060e632bae598003bf3a51a474709fe8c7ac`, default SQLite discovery (`pg` excluded by the runner): 1285 collected, 0 decorator skips.
- This SHA, same discovery: 1289 collected, 0 decorator skips.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run on this SHA passed 1289, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The four added tests are `SchemaVersionWindowTests.test_missing_schema_version_is_rejected`, `SchemaVersionWindowTests.test_malformed_schema_version_is_rejected`, `SchemaVersionWindowTests.test_major_outside_contracts_window_is_rejected`, and `SchemaVersionWindowTests.test_minimal_document_inside_window_is_accepted`. This ticket adds no frontend test and no `pg` test.

The local virtualenv also had the optional pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.vision.txt` (`pillow`), `requirements.inference.txt` (`gguf`), and `pypdfium2` from `requirements.specialists.txt`, plus the CPU wheels for `torch==2.13.0` and `torchvision==0.28.0`. Those packages let the optional PDF, audio, image, GGUF, and embedding tests run. Discovery on `4dd5060` with the same interpreter shows 0 decorator skips in the default SQLite suite.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `4dd5060` without those variables.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. Ten files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. The reported fix versions are 6.21.3 and 6.21.4. That file is outside this ticket's edit list. The pin matches `4dd5060`. No ignore was added.

## Gate G-secrets

No `--config`, no baseline, no allowlist, and no `.gitleaks.toml` was added.

- `gitleaks` 8.28.0 `dir . --redact` on the working tree at `462faab0e9752a561d779b94326feedac57fe2ad` scanned 32.35 MB and exited 0 (`no leaks found`). Console: `gitleaks-8.28-dir.json`.
- `gitleaks` 8.30.1 `dir . --redact` on that same tree exited 1 with 370 findings, all rule `generic-api-key`, across 60 files. None are under `contracts/`. Console: `gitleaks-dir.json`. The raw report is not committed.
- `gitleaks` 8.30.1 `detect --source . --redact --log-opts=--all` scanned 206 commits and exited 1 with 781 findings, all rule `generic-api-key`. Findings on `462faab0e9752a561d779b94326feedac57fe2ad`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 370. Console: `gitleaks-detect.json`.

The 370 working-tree findings are the hits on `75e2565` owned by ANVIL-043. This ticket adds no finding and no allowlist.

After these evidence files were written, `gitleaks` 8.30.1 and 8.28.0 `dir` on `docs/engineering/verification/anvil-056-2026-11-11` each exited 0. The same 8.30.1 command on `contracts/test_validate.py` exited 0.

## Retrieval control

`premerge.json` stdout includes the existing retrieval control `TASK69_CONTROLS`. This change does not add a retrieval-quality claim.

## Result

`make premerge` exited 0 at `462faab0e9752a561d779b94326feedac57fe2ad` with no runtime skip, xfail, or timeout. Backend passed tests are 1289, four above the 1285 collected on `4dd5060`. Frontend passed tests stay 249. PostgreSQL passed tests stay 28. `pip-audit` exits 1 on the unchanged `requirements.documents.txt` pin. `gitleaks` 8.28.0 `dir` exits 0. `gitleaks` 8.30.1 `dir` exits 1 with the 370 `generic-api-key` findings on `75e2565`.
