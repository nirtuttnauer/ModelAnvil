# ANVIL-022 CPU character evaluation compare

Label: `local`.

`compare()` in `modelanvil/runners/cpu_character_eval_envelope.py` mirrors `compare()` in `scripts/rag_report.py`. It raises when the reproduction policy hash changes or a numeric field leaves the spread of the three frozen ANVIL-021 repeats. Text and boolean fields stay exact. The policy file still stores no tolerance.

The committed reference run reproduces. Its held-out completion is `ab` and the expected text is `not-the-model-output`. Case score `0.0`, case passed `false`. `compare()` returns `passed: true` for that reproduction and `quality_pass: false`. That non-match is not a quality pass, and it is not production or hardware qualification.

The implementation was rebased onto `origin/main` `7f7a155900c87148ec4dee00588880e762fe1fcd` (ANVIL-015) before these commands. The commands ran at `0b661fe94c458a469e7b8e38961b463e09b76633`.

## Gate G-local

Label: `local`. Code SHA `0b661fe94c458a469e7b8e38961b463e09b76633`. `git status --porcelain` was empty at the start of each command. Records use `docs/engineering/schemas/local-evidence.v1.json`.

Machine: `cursor`, Linux-6.12.94+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.2.

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `backend-sqlite.json` | 2026-10-29T06:40:13+00:00 | `/workspace/.venv/bin/python manage.py test --noinput --exclude-tag=pg -v 1` | 0 | 1282 | 28 | 1282 | 0 |
| `backend-pg.json` | 2026-10-29T06:43:05+00:00 | `/workspace/.venv/bin/python manage.py test --noinput --tag=pg -v 1` | 0 | 28 | 0 | 28 | 0 |
| `frontend-npm-test.json` | 2026-10-29T06:34:43+00:00 | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |

SQLite result line: `Ran 1282 tests in 325.944s` then `OK`. `DATABASE_NAME=/tmp/anvil022c/dev.db`, `DATABASE_TEST_NAME=/tmp/anvil022c/sqlite3.sqlite3`, `RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/%2F`.

PostgreSQL result line: `Ran 28 tests in 101.808s` then `OK`. Database `modelanvil` on localhost, `DATABASE_ENGINE=postgresql`, pgvector 0.8.1, RabbitMQ on 127.0.0.1:5672, and the pinned MiniLM, SciFact, and SmolLM2 caches with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

Frontend result: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, `duration_ms 2361.788296`. Node v24.22.2, npm 11.19.1.

Counts against `origin/main` `7f7a155900c87148ec4dee00588880e762fe1fcd`: ANVIL-015 recorded 1279 SQLite tests, 28 `pg` tests, and 249 frontend tests. This SHA executed 1282 SQLite tests. The three additional IDs are in `modelanvil.runners.test_cpu_character_eval_envelope.CompareEnvelopeTests`:

- `test_reference_run_reproduces_without_a_quality_pass`
- `test_policy_hash_change_fails`
- `test_field_outside_tolerance_fails`

PostgreSQL stayed at 28. Frontend stayed at 249. No new skip, xfail, timeout, or failure versus that main SHA.

Baseline `3200915506331979c712c17ffd0b1817f95fda75`, as recorded in `docs/engineering/verification/anvil-002-2026-10-29/report.md`: 1231 SQLite tests executed, 24 `pg` tests, 234 frontend tests. This run is above that baseline. The increase is the tests recorded on `main` through ANVIL-015, plus the three tests above.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The three records have zero of each. The SQLite command excludes `pg` before the run. Those 28 IDs are listed in `backend-sqlite.json`. DiscoverRunner on this SHA collects the same 28 IDs for `--tag=pg`, and the PostgreSQL command runs them. Every collected test ID is in at least one of the two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on the test records. They are the same two IDs recorded on `main`.

## Gate G-audit

`pip-audit -r <file>` for every root `requirements*.txt`, no `--ignore-vuln`. `pip-audit` 2.10.1. The requirement files are unchanged on this SHA. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.txt`, `requirements.production.txt`, `requirements.documents.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.embeddings.txt`, `requirements.audio.txt`, `requirements.vision.txt`, `requirements.tools.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`. Summary: `pip-audit.txt`.

## Gate G-secrets

No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

`gitleaks` 8.28.0, the version recorded by ANVIL-017:

- `gitleaks dir .` on this working tree, including this evidence directory before it was committed, scanned 30.65 MB and exited 0 (`no leaks found`). Console: `gitleaks-8.28-dir.summary.txt`.
- `gitleaks detect --source . --log-opts=--all` scanned 190 commits and exited 1 with 411 findings, 391 unique fingerprints, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. None are on `0b661fe` or under `anvil-022`. Console: `gitleaks-8.28-detect.summary.txt`. The raw report is not committed.

`gitleaks` 8.30.1:

- `gitleaks dir .` exited 1 with 370 findings, all rule `generic-api-key`, and none under `anvil-022` or `cpu_character_eval`. That is the same count ANVIL-021 recorded on main. Console: `gitleaks-8.30-dir.summary.txt`.
- `gitleaks detect --source . --log-opts=--all` found 781. The 370 fingerprints absent from the ANVIL-017 list are all on main commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. None are on this branch's commits. Console: `gitleaks-8.30-detect.summary.txt`.

## Gate G-rag

The character-evaluation score above is not a retrieval measurement. The reference completion does not match the held-out text, so the reproduction is not a quality pass. `backend-pg.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.
