# ANVIL-070 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. `premerge.json` was written by `.venv/bin/python scripts/premerge.py`. The gitleaks and pip-audit records were written by `.venv/bin/python scripts/local_evidence.py`. Each command started from an empty `git status --porcelain`.

The measured tree is `754934f330e7718893b6f5c8b17a5d8562890950`. This report is the following docs-only commit. Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

## What changed

`modelanvil/sdk/test_manifest.py` checks extension manifests against `contracts/schemas/adapter-manifest.schema.json`:

- A minimal manifest from `AdapterManifestBuilder` is accepted by `validate_extension_manifest`.
- A manifest with the documented required field `license` removed is rejected with `InvalidDocumentError`.
- `capabilities` set to a string, where the schema requires a list, is rejected.
- An empty document is rejected, and the error text names every documented required field.

`modelanvil/sdk/manifest.py` is unchanged. `validate_extension_manifest` already rejects an empty document and a document missing a required field, so no validator edit was required. `custom_format.py`, `runtime.py`, and `test_sdk.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:57:05+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:45:06+00:00 | `pip-audit -r` on every `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:43:34+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:43:38+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`scripts/premerge.py` records the command as `make premerge`. Backend result: `Ran 1289 tests in 309.179s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 113.203s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

## Counts against main `4dd5060` and `1d4ecd1`

Discovery with this interpreter, without executing the suite:

- `1d4ecd1a6f1a65f159649350be5c751645e0773a` (`origin/main`, which contains `4dd5060`), `--exclude-tag=pg`: 1285 collected, 0 decorator skips.
- This SHA, `--exclude-tag=pg`: 1289 collected, 0 decorator skips.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run on this SHA passed 1289, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The four added tests are `ExtensionManifestValidationTests.test_minimal_builder_manifest_is_accepted`, `ExtensionManifestValidationTests.test_missing_required_license_is_rejected`, `ExtensionManifestValidationTests.test_capabilities_string_is_rejected`, and `ExtensionManifestValidationTests.test_empty_document_is_rejected`. This ticket adds no frontend test and no `pg` test.

`4dd5060` recorded 1285 backend, 249 frontend, and 28 PostgreSQL in `docs/engineering/verification/anvil-012-2026-11-11/report.md`. This run is above that backend count by the four new tests. Frontend and PostgreSQL match that record.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `1d4ecd1` without those variables.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` on this main pins `pypdf==6.21.4`. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No baseline and no new allowlist. `.gitleaks.toml` is the ANVIL-043 file already on main. This ticket does not edit it.

- `gitleaks dir . --redact` on the working tree at `754934f330e7718893b6f5c8b17a5d8562890950` exited 0 with no leaks. Console: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. All 36 fingerprints are on `reviews/ANVIL-017-gitleaks-history.md`. Findings on this SHA: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0 under this config. Console: `gitleaks-detect.json`. The raw report is not committed.
- A stock 8.30.1 config, passed with `--config` so it does not load `.gitleaks.toml`, still reports 370 `generic-api-key` findings on the working tree. None are in `modelanvil/sdk/test_manifest.py`. Those 370 are the decoded-digest hits on `75e2565` owned by ANVIL-043. No allowlist was added.

After these evidence files were written, `gitleaks dir . --redact` on `docs/engineering/verification/anvil-070-2026-11-12` exited 0, and the same command on the working tree exited 0.

## Gate G-rag

This change does not add a retrieval measurement. `premerge.json` still contains the existing `TASK69_CONTROLS` control that was already on main.

## Result

`make premerge` exited 0 with 1289, 249, and 28 passed and no runtime skip, xfail, or timeout. `pip-audit` exited 0 on every `requirements*.txt` with no ignore. `gitleaks dir` exited 0. The pull request stays open.
