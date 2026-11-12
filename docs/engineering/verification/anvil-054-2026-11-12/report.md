# ANVIL-054 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `001b978497e0a216917977b45119d80b50ef49fd`. This report is the following documentation commit. The commands below ran at `001b978497e0a216917977b45119d80b50ef49fd`.

`contracts/versioning.py` matches its module docstring. `parse_version` accepts `MAJOR.MINOR` and `MAJOR.MINOR.PATCH`, normalizes a missing patch to `0`, and raises `ValueError` for a non-string, the wrong number of components, a negative component, or a non-integer. `is_compatible` is false across majors, true for the same major when `allow_additive` is true, and requires matching minors when `allow_additive` is false. `supported_versions` returns the inclusive min/max window stored in `CONTRACTS`. No edit to `contracts/versioning.py` was required. `CONTRACTS` and the contract ids are unchanged. `contracts/validate.py` and `contracts/errors.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:52:01+00:00 | `make premerge` | 0 | 1299 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1299, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:44:57+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:43:46+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:45:00+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` was `.venv/bin/python scripts/premerge.py --output /tmp/anvil054-evidence/premerge.json`. `scripts/premerge.py` records the command as `make premerge`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1299 tests in 319.152s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 126.427s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for the PostgreSQL run after the pinned caches were filled. `web/storybook-static/` was removed after the build. It is gitignored and is not in the commit.

## Counts against main `4dd5060` and `1d4ecd1`

Discovery with this interpreter, without executing the suite:

- `4dd5060e632bae598003bf3a51a474709fe8c7ac`, as recorded by ANVIL-012 and ANVIL-043: `--exclude-tag=pg` 1285 passed, frontend 249 passed, `--tag=pg` 28 passed.
- `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`: `--exclude-tag=pg` 1285 collected, 0 decorator skips; `--tag=pg` 28 collected.
- This SHA: `--exclude-tag=pg` 1299 collected, 0 decorator skips; `--tag=pg` 28 collected.

The executed premerge run passed 1299, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. That is 14 more backend tests than `4dd5060` and than `1d4ecd1`. The 14 tests are the methods in `contracts/test_versioning.py`. This ticket adds no frontend test and no `pg` test.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `1d4ecd1` without those variables.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command ran those 28. Every collected ID is in one of those two runs.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` on this main pins `pypdf==6.21.4`. ANVIL-042 owns that pin. No ignore was added, and this ticket does not edit a requirements file.

## Gate G-secrets

`gitleaks` 8.30.1. The repository `.gitleaks.toml` is the ANVIL-043 config. This ticket does not edit it and does not add an allowlist.

- `gitleaks dir . --redact` on the working tree at `001b978497e0a216917977b45119d80b50ef49fd` exited 0, `no leaks found`, 34.76 MB. Record: `gitleaks-dir.json`. The same command after these evidence files were written, and a scan of this directory, also exited 0.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. None are on `001b978497e0a216917977b45119d80b50ef49fd`. None are on `75e2565a83b4b0cf96aebe793a9da6823e67d165`. The 370 findings on `75e2565` are owned by ANVIL-043. The raw detect report is not committed.

## Acceptance criteria

- `parse_version` accepts `MAJOR.MINOR` and `MAJOR.MINOR.PATCH` and normalizes a missing patch to `0`: `ParseVersionTests.test_major_minor_normalizes_a_missing_patch_to_zero`, `test_major_minor_patch_keeps_each_component`.
- `parse_version` rejects non-strings, wrong arity, negatives, and non-integers with `ValueError`: `test_non_strings_raise_value_error`, `test_wrong_arity_raises_value_error`, `test_negative_components_raise_value_error`, `test_non_integers_raise_value_error`.
- `is_compatible` is false across majors: `IsCompatibleTests.test_different_majors_are_incompatible`.
- `is_compatible` is true for the same major when `allow_additive` is true, even if the minors differ: `test_same_major_allows_different_minors_when_additive`.
- `is_compatible` requires matching minors when `allow_additive` is false: `test_strict_mode_requires_matching_minors`.
- `supported_versions` returns the inclusive min/max window for every `ContractId.ALL` key: `SupportedVersionsTests.test_every_contract_id_returns_its_inclusive_window`.
- `supported_versions` raises `KeyError` for an unknown id: `test_unknown_contract_raises_key_error`.

## Result

`make premerge` exited 0 with no runtime skip, xfail, or timeout. Backend counts are above main `4dd5060` (1299 versus 1285) and above `origin/main` `1d4ecd1` by the 14 new tests. Frontend stays 249. PostgreSQL stays 28. `pip-audit` exited 0 with no ignore. `gitleaks dir` exited 0. The pull request stays open.
