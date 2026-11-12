# ANVIL-071 local evidence, 12 November 2026

Label: `local`. Records use `docs/engineering/schemas/local-evidence.v1.json`. Commands ran from a clean `git status --porcelain` at `1cceb099cc6f4bd0b58ddc3514f27b1c996255ef`. This report is the documentation commit that follows those commands.

Parent: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:51:36+00:00 | `make premerge` | 0 | 1291 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1291, 249, 28 | 0 |
| `make-check.json` | 2026-11-12T14:54:29+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-12T14:53:32+00:00 | `pip-audit -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:54:07+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-stock.json` | 2026-11-12T14:54:30+00:00 | stock `gitleaks dir` on `git archive HEAD` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output /tmp/anvil071-evidence/premerge.json` with Node v24.22.3 at the front of `PATH`. The script records the command as `make premerge`. Backend: `Ran 1291 tests in 308.118s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`. PostgreSQL: `Ran 28 tests in 120.191s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

`make check` printed `System check identified no issues (0 silenced).`

## What the tests lock

`modelanvil/cli/test_cli_client_errors.py` uses a fake transport and a patched `urllib.request.urlopen`. No live network is opened. HTTP 400, 401, 403, 404, 422, 500, 502, and 503 become `ModelAnvilClientError` with `status_code` set and `str(error)` starting `HTTP <status>:`. A urllib network failure becomes `ModelAnvilClientError` whose message starts `Network error:`.

The same tests send an Authorization bearer, a `token` query value, or both. They build those values in the test process and assert that the exception message, `str(error)`, `repr(error)`, the payload, the formatted traceback, and captured `modelanvil.cli.client` log lines do not contain them. The assertion failure text does not print the value.

A response body or URL error reason that echoes the bearer or the token query is stored as `[redacted]` in the exception message and debug log line. The raw urllib exception is not chained, so its URL is not attached as `__cause__` or `__context__`.

## Counts

`4dd5060` on a Linux host, recorded in `docs/engineering/verification/anvil-012-2026-11-11/report.md`: 1285 backend passed, 249 frontend passed, 28 PostgreSQL passed, 0 skipped.

This host, this SHA: 1291 backend passed, 249 frontend passed, 28 PostgreSQL passed, 0 skipped. The six added methods are in `ClientHttpErrorTests`:

- `test_transport_4xx_and_5xx_become_client_errors`
- `test_echoed_bearer_and_token_query_stay_out_of_the_error`
- `test_token_query_without_bearer_stays_out_of_the_error`
- `test_urllib_http_errors_redact_bearer_and_token_query`
- `test_urllib_network_error_redacts_bearer_and_token_query`
- `test_success_response_does_not_log_the_bearer`

No frontend test and no `pg` test was added. `web/` is unchanged from `1d4ecd1`.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent without those variables on the `4dd5060` record.

## Gate G-skip

Skipped, xfailed, and timeout are 0 in each executed run. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` was not edited. This run did not report a pypdf CVE. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No allowlist was added. `.gitleaks.toml` is unchanged from `1d4ecd1`.

- `gitleaks dir . --redact` on the working tree at `1cceb099cc6f4bd0b58ddc3514f27b1c996255ef`, after removing the gitignored `web/storybook-static/` build output, exited 0 (`no leaks found`). Console: `gitleaks-dir.json`.
- The same command on `git archive HEAD` also exited 0.
- Stock upstream config `config/gitleaks.toml` from gitleaks 8.30.1, on that archive, exited 1 with 370 findings, all rule `generic-api-key`. None are under `modelanvil/cli/`. That is the same count ANVIL-043 records for commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. Console: `gitleaks-stock.json`. The raw finding report is not committed.

`gitleaks dir` with the repository config is 0. The stock 370 findings are the pre-existing `75e2565` set owned by ANVIL-043.

After these evidence files were written, `gitleaks dir` on `docs/engineering/verification/anvil-071-2026-11-12` exited 0.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

`make premerge` exited 0 with no runtime skip, xfail, or timeout. Backend passed 1291, which is 6 above the Linux count of 1285 at `4dd5060`. Frontend stayed at 249. PostgreSQL stayed at 28. `pip-audit` exited 0 with no ignore. `gitleaks dir` exited 0 with the repository config, and the stock scan still reports the 370 findings owned by ANVIL-043.
