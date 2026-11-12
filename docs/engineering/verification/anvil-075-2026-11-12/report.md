# ANVIL-075 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. They were written by `.venv/bin/python scripts/local_evidence.py` or `scripts/premerge.py` from a clean `git status --porcelain`.

The measured tree is `b57a6f85140702951dfbde5da76721bed8ee3df7`. This report is the following documentation commit. The commands below ran at that SHA.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`. Floor named by the ticket: `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

## What this ticket locks

`modelanvil/jobs/executor.py` states that executors are installed by operators and that job payloads are data, never Python or shell commands. `execute_claim` already passes the claimed descriptor to the executor and does not interpret the payload. No change to `executor.py` was required.

`modelanvil/jobs/test_executor_payloads.py` reuses the claim fixture pattern from `modelanvil/jobs/test_executor.py` without editing that file. A stub executor receives a payload that contains shell metacharacters and a Python snippet. The snippet and the shell string are executed once in the test, before `execute_claim`, to prove they would create a sentinel file. `execute_claim` then delivers the same payload dict to the stub, commits a verified envelope, and leaves the sentinel absent. Calls to `subprocess`, `os.system`, `eval`, and `exec` made by `execute_claim` fail the test when they carry that payload or spawn a shell. A shell spawned by the stub is attributed to the stub.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:51:25+00:00 | `make premerge` | 0 | 1287 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1287, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:45:38+00:00 | `pip-audit -r` on every `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:44:07+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:44:09+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by:

```sh
.venv/bin/python scripts/premerge.py --output docs/engineering/verification/anvil-075-2026-11-12/premerge.json
```

`scripts/premerge.py` records the command as `make premerge`. Backend result: `Ran 1287 tests in 333.504s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 113.735s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

## Counts against main

Discovery with this interpreter, without executing the suite:

- `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips. `--tag=pg`: 28 collected.
- This SHA, `--exclude-tag=pg`: 1287 collected, 0 decorator skips.

The executed premerge run passed 1287, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The two added tests are `ExecutorPayloadDataTests.test_shell_and_python_payload_is_delivered_as_data` and `ExecutorPayloadDataTests.test_stub_shell_is_not_charged_to_execute_claim`. This ticket adds no frontend test and no `pg` test.

`4dd5060` recorded an executed suite of 1285 backend, 249 frontend, and 28 PostgreSQL in [anvil-012](../anvil-012-2026-11-11/report.md). This run is above that backend count and equal on frontend and PostgreSQL.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `1d4ecd1` without those variables.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` on this base pins `pypdf==6.21.4`. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No new allowlist was added. `.gitleaks.toml` is the ANVIL-043 config already on `origin/main`. Raw reports are not committed.

- `gitleaks dir . --redact` at `b57a6f85140702951dfbde5da76721bed8ee3df7` exited 0 with `no leaks found`. Console: `gitleaks-dir.json`.
- The same command with the stock v8.30.1 config, after the premerge Storybook output was removed, reported 370 `generic-api-key` findings. None are in this ticket's files. ANVIL-043 triaged that set as the decoded-digest hits introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165`. The repository config covers them. This ticket does not edit that config.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. Findings on `b57a6f85140702951dfbde5da76721bed8ee3df7`: 0. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Console: `gitleaks-detect.json`.

After these evidence files were written, `gitleaks dir . --redact` on the tree that this commit adds exited 0.

## Result

`execute_claim` delivers a shell-and-Python payload to the operator stub as data and does not spawn a shell for it. `make premerge` exited 0 with no runtime skip, xfail, or timeout. `pip-audit` exited 0 with no ignore. `gitleaks dir` exited 0 with the repository config. The 370 stock working-tree hits remain the `75e2565` set owned by ANVIL-043.
