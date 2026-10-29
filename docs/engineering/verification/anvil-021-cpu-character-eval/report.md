# ANVIL-021 CPU character evaluation envelope

Label: `local`.

The policy and reference were committed in `f02a21a12d421a34b28359acadedb24b7de61ebc` before these runs. That commit contains the spread rule and the pinned protocol. It contains no measured completion, score, weight hash, spread, or tolerance. The checker landed in `05d0f967b3ffb83d4b9630e55bc8a12754568c40`. These four records were taken at that SHA from an empty `git status --porcelain`, after rebasing onto `16a9be95921f0d99566cd24c1e4e491123f0d0a1`.

Machine: `cursor`, Linux-6.12.94+-x86_64-with-glibc2.39, Python 3.12.3, Node v22.23.4. Records use `docs/engineering/schemas/local-evidence.v1.json`.

## Repeat runs

| File | Recorded at | Command | Exit |
| --- | --- | --- | --- |
| `repeat-1.json` | 2026-10-29T05:35:57+00:00 | `/workspace/.venv/bin/python scripts/cpu_character_eval_repeat.py` | 0 |
| `repeat-2.json` | 2026-10-29T05:36:04+00:00 | same command | 0 |
| `repeat-3.json` | 2026-10-29T05:36:11+00:00 | same command | 0 |
| `spread.json` | 2026-10-29T05:36:25+00:00 | spread command over the three stdout reports | 0 |

Each run is `modelanvil.runners.eval_worker.evaluation_worker_executor` at evidence level `integrated_execution`, seed 42, two SGD steps, greedy CPU decoding, exact match, two generated tokens. The three stdout reports agree on every exact field. `measured_spread` reports no exact disagreements. Every numeric tolerance is `0.0`. Checking each run against the three repeats returns `checks_ok: [true, true, true]`.

Measured values from the first run, identical on the other two except wall time:

- Candidate completion: `ab`
- Baseline completion: empty string
- Case score: `0.0`. Passed: `false`. Baseline score: `0.0`
- Accuracy value, both the `all` and `held-out` slices, candidate and baseline: `0.0` on 1 case
- Wilson upper: `0.7935`. Wilson lower: `0`
- Candidate weights SHA-256: `fe523dc37d67948ff1dd54eecf6ae05aa58d550c1501dca1456115a6d19af434`
- Baseline weights SHA-256: `904541009852d589e759e2e3538fe22948be35bb4604ef51cb79e79500c66e34`
- Wall seconds, recorded and not compared: `0.04171950099998867`, `0.030515171000388364`, `0.03109438899991801`

The held-out expected text is `not-the-model-output`. The run does not produce it. That is the reproduced result. It is not a quality pass, and it is not production or hardware qualification.

The tolerance is the measured spread under policy `cpu-character-eval-reproduction-v1`. The policy file was not edited after these runs and still stores no tolerance value.

## Gate G-local

Label: `local`. Code SHA `1435757d03c45b6fccb0741565e5f43122d90202`. `git status --porcelain` was empty at the start of each command. Records use `docs/engineering/schemas/local-evidence.v1.json`.

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `backend-sqlite.json` | 2026-10-29T05:43:38+00:00 | `manage.py test --noinput --exclude-tag=pg -v 1` | 0 | 1270 | 28 | 1270 | 0 |
| `backend-pg.json` | 2026-10-29T05:50:17+00:00 | `manage.py test --noinput --tag=pg -v 1` | 0 | 28 | 0 | 28 | 0 |
| `frontend-npm-test.json` | 2026-10-29T05:38:24+00:00 | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |

SQLite result line: `Ran 1270 tests in 329.874s` then `OK`. `DATABASE_NAME=/tmp/anvil021/dev3.db`, `DATABASE_TEST_NAME=/tmp/anvil021/sqlite3.sqlite3`, `RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/%2F`. The record's node field is v22.23.4.

PostgreSQL result line: `Ran 28 tests in 112.486s` then `OK`. Database `modelanvil` on localhost, `DATABASE_ENGINE=postgresql`, pgvector 0.8.1, RabbitMQ on localhost:5672, and the pinned MiniLM, SciFact, and SmolLM2 caches with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

Frontend result: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, `duration_ms 2821.485835`. Node v24.22.2, npm 11.19.1.

Counts against current `origin/main` `16a9be95921f0d99566cd24c1e4e491123f0d0a1`: DiscoverRunner on that tree collected 1263 tests with `--exclude-tag=pg`. This SHA executed 1270. The seven additional IDs are in `modelanvil.runners.test_cpu_character_eval_envelope`:

- `EnvelopeRuleTests.test_policy_and_reference_contain_no_measurement`
- `EnvelopeRuleTests.test_tolerance_is_the_unpadded_spread`
- `EnvelopeRuleTests.test_failure_does_not_change_the_policy`
- `EnvelopeRuleTests.test_exact_text_is_not_given_a_tolerance`
- `EnvelopeRuleTests.test_a_stored_tolerance_is_rejected`
- `EnvelopeRuleTests.test_matching_run_passes_at_the_measured_spread`
- `CpuCharacterEvalRepeatTests.test_two_runs_match_on_the_pinned_worker_path`

PostgreSQL stayed at 28. Frontend stayed at 249.

Baseline `3200915506331979c712c17ffd0b1817f95fda75`, as recorded in `docs/engineering/verification/anvil-002-2026-10-29/report.md`: 1231 SQLite tests executed, 24 `pg` tests, 234 frontend tests. This run is above that baseline. The increase is the tests recorded on `main` after that SHA, including the four `PaidDefaultsTests` present at `8989985` and the three `DeploySecretKeyCheckTests` recorded by ANVIL-017, plus the seven tests above.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The three records have zero of each. The SQLite command excludes `pg` before the run and lists those 28 IDs. The PostgreSQL command runs the same 28 IDs. DiscoverRunner on this SHA collected the same PostgreSQL set.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on the test records. They are the same two IDs recorded on `main`.

## Gate G-audit

`pip-audit -r <file>` for every root `requirements*.txt`, no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.txt`, `requirements.production.txt`, `requirements.documents.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.embeddings.txt`, `requirements.audio.txt`, `requirements.vision.txt`, `requirements.tools.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`. Summary: `pip-audit.txt`.

## Gate G-secrets

No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

`gitleaks` 8.28.0, the version recorded by ANVIL-017:

- `gitleaks dir .` on the working tree that contains these records scanned 24.74 MB and exited 0. Console: `gitleaks-8.28-dir.summary.txt` (`no leaks found`).
- `gitleaks detect --source . --log-opts=--all` scanned 175 commits and exited 1 with 411 findings, 391 unique fingerprints, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Console: `gitleaks-8.28-detect.summary.txt`. The raw report is not committed.

`gitleaks` 8.30.1 is the binary on `PATH`. `gitleaks dir .` exited 1 with 370 findings, all rule `generic-api-key`, and none under `anvil-021`. The same command on `origin/main` `16a9be95921f0d99566cd24c1e4e491123f0d0a1` also found 370. `gitleaks detect --source . --log-opts=--all` found 781. The 370 fingerprints that are absent from the ANVIL-017 list are all on main commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. None are on this branch's commits.

## Gate G-rag

The character-evaluation accuracy above is not a retrieval measurement. `backend-pg.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.
