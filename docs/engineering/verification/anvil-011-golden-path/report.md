# ANVIL-011 local evidence, 29 October 2026

Label: `local`. Machine: `cursor`, Linux 6.12.94+ x86_64, Python 3.12.3, Node v22.23.4. Records use `docs/engineering/schemas/local-evidence.v1.json` and were written by `.venv/bin/python scripts/local_evidence.py` from a clean `git status --porcelain`.

The measured tree is `d22a46af751a7f692aa2cdf67361fa9ef85676bc`, the merge of the golden-path implementation with `origin/main` (`aaec53bb3c30d92ce7230991c24542bcfa1a4265`, ANVIL-009). This report is the following docs-only commit. The branch was already pushed, so latest `main` was merged in rather than rewritten.

## Records

| File | SHA | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `golden-path.json` | `d22a46af751a7f692aa2cdf67361fa9ef85676bc` | `scripts/golden_path.sh d22a46af751a7f692aa2cdf67361fa9ef85676bc --steps 3` | 0 | 0 | 0 | 0 | 0 |
| `make-check.json` | `d22a46af751a7f692aa2cdf67361fa9ef85676bc` | `make check` | 0 | 0 | 0 | 0 | 0 |
| `backend-sqlite.json` | `d22a46af751a7f692aa2cdf67361fa9ef85676bc` | `manage.py test --noinput --exclude-tag=pg` | 0 | 1266 | 28 | 1266 | 0 |
| `frontend-npm-test.json` | `d22a46af751a7f692aa2cdf67361fa9ef85676bc` | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |
| `backend-pg.json` | `d22a46af751a7f692aa2cdf67361fa9ef85676bc` | `manage.py test --noinput --tag=pg` | 0 | 28 | 0 | 28 | 0 |
| `pip-audit.json` | `d22a46af751a7f692aa2cdf67361fa9ef85676bc` | `pip-audit -r` on every `requirements*.txt` | 1 | 0 | 0 | 0 | 0 |

`backend-sqlite.json` lists the 28 excluded test IDs. They are the same 28 IDs the PostgreSQL command executed. SQLite used `DATABASE_ENGINE=sqlite` and `DATABASE_TEST_NAME=/tmp/anvil011-sqlite.sqlite3`. PostgreSQL used `DATABASE_ENGINE=postgresql`, local database `modelanvil` on `127.0.0.1`, pgvector 0.8.1, RabbitMQ at `127.0.0.1:5672`, `HF_HUB_OFFLINE=1`, and the pinned MiniLM, SciFact, and SmolLM2 caches. The database password was supplied in the environment and is not in the record.

The golden-path stdout redacts one line from `bootstrap_dev`. That command prints the local development key that already lives in `modelanvil/identity/management/commands/bootstrap_dev.py`. No Hub token was set. The run logged Hugging Face's unauthenticated-request warning.

## Golden path

`scripts/golden_path.sh d22a46af751a7f692aa2cdf67361fa9ef85676bc --steps 3` cloned that commit from `https://github.com/nirtuttnauer/ModelAnvil.git` into a temporary directory, ran only the README install block, and trained 3 CPU LoRA steps on the pinned SmolLM2-135M base. Exit 0. The log ends with `completed 3 SmolLM2-135M CPU LoRA steps` and `golden path completed 3 SmolLM2-135M CPU steps at d22a46af751a7f692aa2cdf67361fa9ef85676bc`. Duration 60414 ms. The temporary directory was removed after success.

## Counts against baseline `3200915`

Baseline `3200915506331979c712c17ffd0b1817f95fda75`, from the [ANVIL-002 record](../anvil-002-2026-10-29/report.md):

- Default SQLite discovery collected 1237 tests. Six were decoration-time skips, leaving 1231 executed tests.
- The `pg` tag collected 24 tests.
- Frontend `npm test`: 234 passed, 0 skipped.

This run:

- SQLite: 1266 passed. That is 35 more executed tests than the baseline's 1231. ANVIL-002 accounts for 25 of them. ANVIL-009's premerge record at `c12d6f1` collected 1260, which is those 1256 plus the four `PaidDefaultsTests` from `d39751a` (`#72`). This ticket adds the six `GoldenPathCommandTests` and `GoldenPathDownloadTests` methods. 1260 + 6 = 1266.
- PostgreSQL: 28 passed. That is the baseline 24 `pg` tests plus the four tests ANVIL-002 retagged. Same count as ANVIL-009. This ticket adds no `pg` test.
- Frontend: 249 passed, 0 skipped. That is 15 above the baseline. ANVIL-002 records those 15. This ticket does not change the frontend tests.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The three test records above have zero of each. The default command excludes `pg` before the run and lists those IDs. The PostgreSQL command runs that tag. Every ID collected on this host is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on the test records as `fixture_tests_not_collected`. Their bodies are unchanged.

`tests/test_premerge.py` is not collected by Django. On this tree, `python3.12 tests/test_premerge.py` runs 12 tests and fails `test_node_20_process_fails_before_any_suite`, because that test asserts `docs/engineering/verification/anvil-009-2026-10-29/premerge.json` is absent and ANVIL-009 committed that file. The same assertion fails on `origin/main` before this ticket. This ticket does not change that test.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit -r <file>` for every `requirements*.txt`, with no `--ignore-vuln`. Log: `pip-audit.json`. Ten files reported no known vulnerabilities and exited 0. `requirements.specialists.txt` exited 1 because `mlx-metal==0.32.3` has no matching distribution on this Linux host. No ignore was added. This is the same pre-existing Linux result recorded by ANVIL-002 and ANVIL-009.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

- `gitleaks dir --redact` on the working tree at `d22a46af751a7f692aa2cdf67361fa9ef85676bc`, before this evidence directory was added, exited 1 with 404 findings, all rule `generic-api-key`. The `(rule, file, line)` set matches `../anvil-002-2026-10-29/gitleaks-dir.txt` with nothing added and nothing removed. Console: `gitleaks-dir.summary.txt`.
- `gitleaks detect --redact` scanned 170 commits and exited 1 with 411 findings, all rule `generic-api-key`. The `(rule, file, commit)` set matches `../anvil-002-2026-10-29/gitleaks-detect.txt` with nothing added and nothing removed. Console: `gitleaks-detect.summary.txt`.

A second `gitleaks dir --redact` of this evidence directory, after the records were written, exited 0 with 0 findings. The committed files do not add a finding.

There is no QA-signed ANVIL-017 triage list in the repository. These are the same 404 working-tree and 411 history findings already on `main`. One local training artifact under gitignored `/storage/` produced three extra `dir` hits during an earlier scan; that directory is not part of the tree and was removed before the scan above.

## Gate G-rag

`backend-pg.json` stdout includes one retrieval measurement, `TASK69_CONTROLS`: held-out nDCG@5 real 1.0 next to seeded random 0.021535, on 20 queries and 200 SciFact documents. That is the existing small correctness check. This change does not claim a new RAG number.

## Merge

The golden path, `make check`, the SQLite suite, the PostgreSQL suite, and the frontend suite exited 0 with no runtime skip, xfail, or timeout. The remaining non-zero results are the pre-existing `mlx-metal` pip-audit failure on Linux, the pre-existing 404/411 gitleaks findings, and the two fixture tests that are not collected without their model directories. `make premerge` was not re-run: it refuses this host's Node v22.23.4 and requires the Docker images named in ANVIL-009. The suites it wraps were run directly and are the records above.
