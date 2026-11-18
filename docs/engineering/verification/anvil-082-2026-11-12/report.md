# ANVIL-082 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. `gitleaks` 8.30.1. `pip-audit` 2.10.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each recorded command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `468ef04606f6ca626bb364dcc185b95e278e57cc`. This report is the following documentation commit. The commands below ran at `468ef04606f6ca626bb364dcc185b95e278e57cc`.

`modelanvil/artifacts/transfers.py` already rejects a part number outside `1..MAX_TRANSFER_PARTS`, a declared size outside `1..MAX_TRANSFER_PART_BYTES`, a SHA-256 that is not 64 lowercase hex characters, and a write or completion after `expires_at`. This ticket adds `modelanvil/artifacts/test_transfer_bounds.py`. `transfers.py` is unchanged. `storage.py`, `tombstones.py`, `worker_access.py`, and `test_transfer_cleanup.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T15:55:59+00:00 | `make premerge` | 0 | 1296 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1296, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T15:49:48+00:00 | `bash /tmp/anvil-082/pip-audit.sh` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T15:48:40+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T15:48:43+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output /tmp/anvil-082/premerge.json`. `scripts/premerge.py` records the command as `make premerge`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1296 tests in 302.830s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, `duration_ms 2111.499967`, after `npm --prefix web ci`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 111.905s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The displayed pg command includes `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. `DATABASE_PASSWORD` is not in the record. `docker compose ... down -v --remove-orphans` ran at the end. Exit 0.

`pip-audit.json` was produced by `.venv/bin/python scripts/local_evidence.py --output /tmp/anvil-082/pip-audit.json -- bash /tmp/anvil-082/pip-audit.sh`. The script runs `.venv/bin/pip-audit --progress-spinner=off -r` on every root `requirements*.txt` in sorted order, prints `EXIT` for each file, and exits 1 if any file exits non-zero. No `--ignore-vuln`.

The gitleaks records were produced by `scripts/local_evidence.py`. Raw finding reports stayed in `/tmp` and are not committed. `gitleaks` was invoked with `--redact`.

## Counts against main `1d4ecd1`

Discovery with this interpreter, without executing the suite:

- `1d4ecd1`, `--exclude-tag=pg`: 1285 collected.
- `1d4ecd1`, `--tag=pg`: 28 collected.
- `468ef04606f6ca626bb364dcc185b95e278e57cc`, `--exclude-tag=pg`: 1296 collected, 0 decorator skips, with the optional pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.vision.txt`, `requirements.gpu.txt`, `requirements.tools.txt`, plus `gguf==0.19.0`, `peft==0.21.2`, `accelerate==1.15.0`, `requests==2.34.2`, and `pypdfium2==5.14.0` installed so those suites run.
- `--tag=pg`: 28 collected. This ticket adds no `pg` test.

The executed premerge run passed 1296, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. `git diff --stat 1d4ecd1a6f1a65f159649350be5c751645e0773a 468ef04606f6ca626bb364dcc185b95e278e57cc` is `modelanvil/artifacts/test_transfer_bounds.py` (265 lines). `web/` is unchanged, so the frontend count stays 249.

The 11 additional backend tests are `modelanvil.artifacts.test_transfer_bounds.TransferBoundsTests`:

- `test_part_number_below_one_is_rejected_and_stores_nothing` (part numbers 0 and -1)
- `test_part_number_above_maximum_is_rejected_and_stores_nothing` (`MAX_TRANSFER_PARTS + 1` and `MAX_TRANSFER_PARTS + 10000`)
- `test_part_number_at_maximum_is_accepted`
- `test_declared_size_zero_is_rejected_and_stores_nothing`
- `test_declared_size_above_maximum_is_rejected_and_stores_nothing` (`MAX_TRANSFER_PART_BYTES + 1`, with a matching digest)
- `test_malformed_sha256_is_rejected_and_stores_nothing`
- `test_uppercase_sha256_is_rejected_and_stores_nothing` (fully uppercase, and one uppercase hex letter)
- `test_expired_open_session_rejects_a_new_part`
- `test_expired_open_session_cannot_be_completed`
- `test_valid_small_part_and_exact_retry_succeed`
- `test_conflicting_retry_fails_and_keeps_the_original_part`

1285 + 11 = 1296.

## Gate G-local

Label: `local`. Code SHA `468ef04606f6ca626bb364dcc185b95e278e57cc`. Passed counts are 1296 SQLite, 249 frontend, and 28 PostgreSQL. SQLite is 11 above main `1d4ecd1` for the tests listed above. Frontend and PostgreSQL equal the discovery counts on `1d4ecd1`.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Skipped, xfailed, and timeout are 0 in each executed run.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on main `1d4ecd1` without those variables. Their bodies are unchanged.

## Mutation check

These two edits were applied on a throwaway copy of the worktree, the named tests were run, and `transfers.py` was restored. `git diff` for that file is empty.

- Removing the declared-size guard made `test_declared_size_above_maximum_is_rejected_and_stores_nothing` and `test_declared_size_zero_is_rejected_and_stores_nothing` fail: `ValueError` was not raised. Exit 1.
- Disabling the `add_transfer_part` expiry guard made `test_expired_open_session_rejects_a_new_part` fail: `TransferExpired` was not raised. Exit 1.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` on this SHA pins `pypdf==6.21.4`, already on main `1d4ecd1` from ANVIL-042. This ticket does not bump dependencies and does not add an ignore.

## Gate G-secrets

`gitleaks` 8.30.1. No new allowlist. The repo `.gitleaks.toml` is the ANVIL-043 config already on main: stock rules stay in force (`useDefault = true`) and the existing allowlists cover the `75e2565` `generic-api-key` digests. Raw finding reports are not committed.

- `gitleaks dir . --redact` on the working tree at `468ef04606f6ca626bb364dcc185b95e278e57cc` exited 0, `no leaks found`, 28.28 MB. Record: `gitleaks-dir.json`.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 228 commits and exited 1 with 36 findings, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Findings on `468ef04606f6ca626bb364dcc185b95e278e57cc`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0 under this config. Record: `gitleaks-detect.json`.

After `make premerge` wrote a gitignored `web/storybook-static/` tree, one `generic-api-key` hit was in that generated directory. The directory was removed and is not in the commit. A following `gitleaks dir . --redact` of the worktree exited 0.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is the existing small correctness check. This change does not claim a new RAG number.

## Result

`make premerge` exited 0 with no runtime skip, xfail, or timeout. Backend passed-count is 11 above main `1d4ecd1` because of `test_transfer_bounds.py`. Frontend and PostgreSQL match main. `pip-audit` exits 0 on every root `requirements*.txt`. `gitleaks dir` exits 0. History findings that remain are the 36 fingerprints already listed for ANVIL-017 and left in place by ANVIL-043. No allowlist was added.
