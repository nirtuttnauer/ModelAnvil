# ANVIL-055 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. Test, check, audit, and gitleaks records were written by `.venv/bin/python scripts/local_evidence.py` or `scripts/premerge.py` from a clean `git status --porcelain`.

The measured tree is `98199f3cd845b6a12d09d3a217e5a99edb31de75`. The commands below ran at that SHA. The evidence commits after it add these records and do not change the tests.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:53:22+00:00 | `make premerge` | 0 | 1290 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1290, 249, 28 | 0 |
| `make-check.json` | 2026-11-12T14:45:14+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-12T14:46:22+00:00 | `pip-audit -r` on every `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:44:56+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir-stock.json` | 2026-11-12T14:45:10+00:00 | `gitleaks dir . --redact` with the upstream 8.30.1 config | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:45:13+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect-stock.json` | 2026-11-12T14:46:34+00:00 | `gitleaks detect --redact --log-opts=--all` with the upstream 8.30.1 config | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by this command, with Node 24.22.3 at the front of `PATH`:

```sh
.venv/bin/python scripts/premerge.py --output /tmp/anvil055-evidence/premerge.json
```

`scripts/premerge.py` records the command as `make premerge`. Backend result: `Ran 1290 tests in 343.484s` then `OK`. Frontend: 249 passed, 0 failed, 0 skipped, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 118.649s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

`make check` printed `System check identified no issues (0 silenced).`

## Counts against main `1d4ecd1` and `4dd5060`

Discovery with this interpreter, without executing the suite:

- `1d4ecd1a6f1a65f159649350be5c751645e0773a` content, `--exclude-tag=pg`: 1285 collected, 0 decorator skips.
- This SHA, `--exclude-tag=pg`: 1290 collected, 0 decorator skips.
- Both trees, `--tag=pg`, without `MODELANVIL_MLX_TEST_MODEL_DIR`: 28 collected.

The executed premerge run on this SHA passed 1290, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The five added tests are `ApiErrorEnvelopeTests.test_every_registered_code_is_accepted`, `ApiErrorEnvelopeTests.test_unregistered_code_raises_value_error`, `ApiErrorEnvelopeTests.test_to_dict_uses_documented_fields_without_secrets`, `ApiErrorEnvelopeTests.test_error_from_exception_maps_api_error_to_its_stable_code`, and `ApiErrorEnvelopeTests.test_unknown_exception_maps_to_internal_error`. This ticket adds no frontend test and no `pg` test.

`4dd5060` recorded 1285 backend, 249 frontend, and 28 PostgreSQL in `docs/engineering/verification/anvil-012-2026-11-11/premerge.json`. This run is 1290, 249, and 28.

This host is Linux, so `make premerge` excludes the `pg` tag and runs the `linux` tag. The 28 excluded IDs are the PostgreSQL tests, and they passed in the PostgreSQL run.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. A missing fixture is not a runtime skip.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` on this tree pins `pypdf==6.21.4`. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No baseline and no new allowlist. Raw reports are not committed.

- `gitleaks dir . --redact` loads the repository `.gitleaks.toml` and exited 0 with no leaks. A second scan of this evidence directory also exited 0. After `make premerge` built Storybook, one `generic-api-key` hit appeared in gitignored `web/storybook-static/`. That directory is not part of this commit. Removing it and scanning the tree again exited 0.
- The same `dir` command with the upstream 8.30.1 config, passed via `--config`, exited 1 with 370 findings, all rule `generic-api-key`. None are in `contracts/test_errors.py` or this directory. Every file-and-line fingerprint is also present on commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. Those hits are owned by ANVIL-043. This ticket does not change `.gitleaks.toml`.
- `gitleaks detect --redact --log-opts=--all` with the repository config exited 1 with 36 findings. None are on `98199f3cd845b6a12d09d3a217e5a99edb31de75`.
- The same `detect` command with the upstream 8.30.1 config scanned 224 commits and exited 1 with 781 findings. 370 of those are on `75e2565a83b4b0cf96aebe793a9da6823e67d165`. Findings on this SHA: 0.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not add a RAG number.

## Result

`contracts/test_errors.py` covers the shared error envelope. `errors.py` did not need a change: every registered code constructs an `ApiError`, an unregistered code raises `ValueError`, `to_dict()` keeps the documented `code`, `message`, `details`, and `request_id` fields, and that envelope does not carry a raw exception, password, or token. `error_from_exception` returns an `ApiError` with its existing stable code, and any other exception becomes `internal_error` without the exception text. `make premerge` exited 0 with no runtime skip, xfail, or timeout. `pip-audit` exited 0 with no ignore. `gitleaks dir` exited 0.
