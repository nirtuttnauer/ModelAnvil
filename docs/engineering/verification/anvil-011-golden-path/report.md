# ANVIL-011 local evidence, 29 October 2026

Label: `local`. Machine: `cursor`, Linux-6.12.94+-x86_64-with-glibc2.39, Python 3.12.3, Node v22.23.4. Records use `docs/engineering/schemas/local-evidence.v1.json` and were written by `.venv/bin/python scripts/local_evidence.py` from a clean `git status --porcelain`.

The measured tree is `8ae141a173d1f6f4f2a814895cfd629f366ed7c7`, the merge of the golden-path implementation with `origin/main` `e56d6f33614bc2765d89bf406b1923fd3a7aff6a` (ANVIL-021). The branch was already pushed, so latest `main` was merged in rather than rewritten. This report is the following docs-only commit. The commands below ran at `8ae141a173d1f6f4f2a814895cfd629f366ed7c7`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `golden-path.json` | 2026-10-29T05:59:24+00:00 | `scripts/golden_path.sh 8ae141a173d1f6f4f2a814895cfd629f366ed7c7 --steps 3` | 0 | 0 | 0 | 0 | 0 |
| `make-check.json` | 2026-10-29T05:58:35+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `backend-sqlite.json` | 2026-10-29T06:04:17+00:00 | `manage.py test --noinput --exclude-tag=pg -v 1` | 0 | 1276 | 28 | 1276 | 0 |
| `frontend-npm-test.json` | 2026-10-29T05:58:34+00:00 | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |
| `backend-pg.json` | 2026-10-29T06:06:43+00:00 | `manage.py test --noinput --tag=pg -v 1` | 0 | 28 | 0 | 28 | 0 |
| `pip-audit.json` | 2026-10-29T05:59:36+00:00 | `pip-audit -r` on every `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |

SQLite result line: `Ran 1276 tests in 336.392s` then `OK`. The command was `DATABASE_ENGINE=sqlite DATABASE_NAME=/tmp/anvil011-dev.db DATABASE_TEST_NAME=/tmp/anvil011-sqlite.sqlite3 RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/%2F` with `DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_USER`, and `DATABASE_PORT` unset. `backend-sqlite.json` lists the 28 excluded test IDs.

PostgreSQL result line: `Ran 28 tests in 112.373s` then `OK`. The recorded command is `/workspace/.venv/bin/python manage.py test --noinput --tag=pg -v 1`. The process environment was `DATABASE_ENGINE=postgresql`, database `modelanvil`, user `modelanvil`, host `127.0.0.1`, port `5432`, pgvector 0.8.1, RabbitMQ at `127.0.0.1:5672`, and `HF_HUB_OFFLINE=1` with `TRANSFORMERS_OFFLINE=1`. The database password was supplied in the environment and is not in the record. Those 28 IDs are the same 28 the SQLite command excluded.

Frontend result: `tests 249`, `pass 249`, `fail 0`, `skipped 0`.

`make check` printed `System check identified no issues (0 silenced).`

## Golden path

`scripts/golden_path.sh 8ae141a173d1f6f4f2a814895cfd629f366ed7c7 --steps 3` cloned that commit from `https://github.com/nirtuttnauer/ModelAnvil.git` into a temporary directory, ran only the README install block, and trained 3 CPU LoRA steps on the pinned SmolLM2-135M base. Exit 0. The log ends with `completed 3 SmolLM2-135M CPU LoRA steps` and `golden path completed 3 SmolLM2-135M CPU steps at 8ae141a173d1f6f4f2a814895cfd629f366ed7c7`. The temporary directory was removed after success. No Hub token was set. The run logged Hugging Face's unauthenticated-request warning. One `bootstrap_dev` line in `golden-path.json` is replaced with a note: that command prints the local development key already stored in `modelanvil/identity/management/commands/bootstrap_dev.py`.

## Counts against baseline `3200915`

Baseline `3200915506331979c712c17ffd0b1817f95fda75`, from the [ANVIL-002 record](../anvil-002-2026-10-29/report.md):

- Default SQLite discovery collected 1237 tests. Six were decoration-time skips, leaving 1231 executed tests.
- The `pg` tag collected 24 tests.
- Frontend `npm test`: 234 passed, 0 skipped.

This run:

- SQLite: 1276 passed, 0 skipped. That is 1231 + 25 (ANVIL-002) + 4 `PaidDefaultsTests` (`d39751a`, counted in ANVIL-009's 1260) + 3 `DeploySecretKeyCheckTests` (ANVIL-017) + 7 CPU character-eval envelope tests (ANVIL-021, 1270 on `origin/main`) + 6 `GoldenPathCommandTests` and `GoldenPathDownloadTests` methods from this ticket. 1270 + 6 = 1276.
- PostgreSQL: 28 passed, 0 skipped. That is the baseline 24 plus the four tests ANVIL-002 retagged. This ticket adds no `pg` test.
- Frontend: 249 passed, 0 skipped. That is the baseline 234 plus the 15 tests recorded by ANVIL-002. This ticket adds no frontend test.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The SQLite, PostgreSQL, and frontend records have zero of each. The default command excludes `pg` before the run and lists those 28 IDs. The PostgreSQL command runs that tag. Every collected ID is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on the test records as `fixture_tests_not_collected`. Their bodies are unchanged. The same two IDs are absent on `main`.

`tests/test_premerge.py` is not collected by Django. On this tree and on `origin/main`, `python3.12 tests/test_premerge.py` fails `test_node_20_process_fails_before_any_suite`, because that test asserts `docs/engineering/verification/anvil-009-2026-10-29/premerge.json` is absent and ANVIL-009 committed that file. This ticket does not change that test.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Log: `pip-audit.json`. ANVIL-017's Darwin markers make `requirements.specialists.txt` resolve on this Linux host. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`. The raw reports are not committed.

- `gitleaks dir --redact` on the working tree at `8ae141a173d1f6f4f2a814895cfd629f366ed7c7`, before this evidence update, exited 1 with 370 findings, all rule `generic-api-key`. None are under `anvil-011` or `golden_path`. Console: `gitleaks-dir.summary.txt`.
- `gitleaks detect --redact` scanned 181 commits and exited 1 with 781 findings. Findings in commits after `e56d6f33614bc2765d89bf406b1923fd3a7aff6a`: 0. Console: `gitleaks-detect.summary.txt`.

`reviews/ANVIL-017-gitleaks-history.md` is the QA triage list. ANVIL-021 recorded `gitleaks` 8.28.0 on this history as `dir` exit 0 and `detect` 411 findings, every fingerprint on that list, and recorded `gitleaks` 8.30.1 on `origin/main` as `dir` 370 and `detect` 781. The 370 fingerprints absent from the ANVIL-017 list are all on main commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. This ticket's commits add 0 findings.

After these evidence files were written, `gitleaks dir --redact` on `docs/engineering/verification/anvil-011-golden-path` exited 0 with no leaks. The same command on the working tree still found 370, all rule `generic-api-key`, and none of those files are under this directory or `golden_path`.

## Gate G-rag

`backend-pg.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Merge

The golden path, `make check`, the SQLite suite, the PostgreSQL suite, the frontend suite, and `pip-audit` exited 0. The three test records have no runtime skip, xfail, or timeout. The two fixture tests that are not collected are the same two absent on `main`. The `gitleaks` 8.30.1 counts match the counts ANVIL-021 recorded on `main`, and this ticket adds no finding. `make premerge` was not re-run: it refuses this host's Node v22.23.4 and requires the Docker images named in ANVIL-009. The suites it wraps were run directly and are the records above.
