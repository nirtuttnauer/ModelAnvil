# ANVIL-015 local evidence, 29 October 2026

Label: `local`. Machine: `cursor`, Linux 6.12.94+ x86_64, Python 3.12.3, Node v24.22.2. Records use `docs/engineering/schemas/local-evidence.v1.json` and were written by `.venv/bin/python scripts/local_evidence.py` from a clean `git status --porcelain`.

Code SHA these commands ran against: `a06ad96cf56723cceb8bf2a2e41e8637a1d76b42`. That commit is the isolated-eval implementation rebased onto `4415aadcf178edf8dc4f2273c8218e7541b4d06b`.

## Network proof

`isolated-eval.json` is `python scripts/isolated_eval.py` (the `make isolated-eval` command). Exit 0. `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` are unset. The proof is a Compose network with `internal: true`. Postgres and RabbitMQ are on that network. The eval container publishes no ports.

Prefetch, while the host could still reach the network, called `cache_pinned_model()`, `cache_corpus()`, and `cache_rag_decoder`.

From the eval container:

- `curl --fail --silent --show-error --max-time 20 https://huggingface.co` exited 6.
- The same curl with `--resolve huggingface.co:443:143.204.1.6` exited 7.

Then, on that network:

| Run | Command | Collected | Passed | Skipped / xfail / timeout | Exit |
| --- | --- | --- | --- | --- | --- |
| golden path | `manage.py test --noinput --exclude-tag=pg -v 1` | 1279 | 1279 | 0 | 0 |
| eval after prefetch | `manage.py test --noinput --tag=pg -v 1` | 28 | 28 | 0 | 0 |
| empty-cache eval | `manage.py test --noinput --tag=pg -v 1` | 28 | 20 | 0 | 1 |

The empty-cache run is the required negative test. It failed and left the cache empty (`empty-cache files before []`, `empty-cache files after []`). The harness treats that failure as success and exits 0. The 20 passes are tests that do not need the pinned cache. The 8 failures and errors are the cache refusals. There is no runtime skip.

Golden path inside the container: `Ran 1279 tests in 349.418s` then `OK`. Eval after prefetch: `Ran 28 tests in 113.929s` then `OK`.

## Host records

| File | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- |
| `backend-sqlite.json` | `manage.py test --noinput --exclude-tag=pg -v 1` | 0 | 1279 | 28 | 1279 | 0 |
| `backend-pg.json` | `manage.py test --noinput --tag=pg -v 1` | 0 | 28 | 0 | 28 | 0 |
| `frontend-npm-test.json` | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |
| `make-check.json` | `make check` | 0 | 0 | 0 | 0 | 0 |

SQLite used `DATABASE_NAME=/tmp/anvil015-sqlite.sqlite3`, `DATABASE_TEST_NAME=/tmp/anvil015-sqlite-test.sqlite3`, and `RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/%2F`. Result: `Ran 1279 tests in 355.104s` then `OK`.

PostgreSQL used database `modelanvil` on 127.0.0.1, user `modelanvil`, `DATABASE_ENGINE=postgresql`, the same RabbitMQ URL, pgvector 0.8.7 (available), and the pinned MiniLM, SciFact, and SmolLM2 caches. Result: `Ran 28 tests in 127.326s` then `OK`.

Frontend used Node v24.22.2 and npm 11.19.1. Result: `# tests 249`, `# pass 249`, `# fail 0`, `# skipped 0`.

`make check` exited 0: `System check identified no issues (0 silenced).`

## Counts against the previous SHA and baseline `3200915`

Previous SHA `4415aadcf178edf8dc4f2273c8218e7541b4d06b` is current `origin/main` under this commit. Its suite is this run minus the three tests added here.

- SQLite: 1279 passed. The three additional IDs are `IsolatedEvalNetworkTests` in `modelanvil/core/test_isolated_eval.py`. The previous SHA therefore collects 1276.
- PostgreSQL: 28 passed. The same 28 IDs excluded from SQLite.
- Frontend: 249 passed, the same count as `4415aad` because `web/` is unchanged.

Baseline `3200915506331979c712c17ffd0b1817f95fda75`, as recorded in `docs/engineering/verification/anvil-002-2026-10-29/report.md`: 1231 SQLite tests after decoration-time fixture handling, 24 `pg` tests, and 234 frontend tests. This run is above that baseline.

The increase from 1231 to 1276, before this ticket, is the tests that landed on `main`:

- ANVIL-002 accounts for 25 tests after `3200915`, reaching 1256, and for moving four tests onto the `pg` tag.
- ANVIL-009 accounts for the four `PaidDefaultsTests`, reaching 1260.
- ANVIL-017 accounts for the three `DeploySecretKeyCheckTests`, reaching 1263.
- `4415aad` adds 13 tests: six in `GoldenPathCommandTests` and `GoldenPathDownloadTests`, six in `EnvelopeRuleTests`, and one in `CpuCharacterEvalRepeatTests`. That reaches 1276.

This ticket adds the three network-harness tests, reaching 1279. PostgreSQL stays at 28, which is the baseline 24 plus the four tests ANVIL-002 retagged. Frontend stays at 249, which is 15 above the baseline of 234 recorded by ANVIL-002.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The host SQLite, host PostgreSQL, frontend, and isolation records have zero of each. The SQLite command excludes `pg` before the run. `backend-sqlite.json` lists the same 28 IDs as ANVIL-017, and the PostgreSQL command runs them.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on the test records. A missing Metal or GGUF fixture is not a runtime skip. The merged ANVIL-002 ruling keeps the skip gate open for those two IDs until a host with the fixtures runs them.

## Gate G-audit

`pip-audit -r <file>` for every root `requirements*.txt`, pip-audit 2.10.1, no `--ignore-vuln`. Log: `pip-audit.txt`. All 11 files exited 0 with `No known vulnerabilities found`, including `requirements.specialists.txt`. The Apple Silicon MLX pins use the Darwin arm64 marker already on main.

## Gate G-secrets

`gitleaks` 8.28.0, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

- `gitleaks dir .` on the working tree, including this evidence directory, exited 0 with 0 findings. Summary: `gitleaks-dir.summary.txt`.
- `gitleaks detect --source . --log-opts=--all --redact` scanned 183 commits and exited 1 with 411 findings (391 unique fingerprints), all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. None are in `a06ad96`. Summary: `gitleaks-detect.summary.txt`. The raw report is not committed because it repeats digest text.

Installed `gitleaks` 8.30.1 still reports 370 `generic-api-key` findings on verification JSON that is already on main. This ticket's files and this evidence directory add none. ANVIL-017's signed working-tree result is the 8.28.0 scan, which is 0.

## Gate G-rag

`backend-pg.json` and `isolated-eval.json` include the existing retrieval control `TASK69_CONTROLS`: held-out nDCG real 1.0 next to seeded random 0.021535, on 200 documents. That is a small correctness check. The documented baseline next to it is MiniLM nDCG@5 1.0000 next to seeded random 0.0215 on 20 queries / 200 SciFact docs (`README.md`). The same record's development nDCG real 0.982545 is the development half of that same check. This change does not claim a new RAG number.
