# ANVIL-076 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. `premerge.json` was written by `.venv/bin/python scripts/premerge.py`. The audit and gitleaks records were written by `.venv/bin/python scripts/local_evidence.py`. Each command started from an empty `git status --porcelain`.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`. The compiler tests and the commands below ran at `5a794b2120eb23fca2b0fc369abd054f184c8618`. This report is the following documentation commit.

`modelanvil/context_lab/compiler.py` is unchanged. A budget that cannot hold every block already raises `ContextOverflowError` for `fail_on_overflow`, and the trim policies already append `omitted_blocks` and `truncated_blocks`. The new tests follow that behavior.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:53:41+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:56:00+00:00 | `pip-audit -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:55:54+00:00 | `gitleaks dir .` 8.30.1, repository config | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-8.28-dir.json` | 2026-11-12T14:55:55+00:00 | `gitleaks dir .` 8.28.0, stock config | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-8.30-stock.json` | 2026-11-12T14:55:57+00:00 | `gitleaks dir .` 8.30.1, stock config | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by this command. `node` on `PATH` was Node v24.22.3:

```sh
.venv/bin/python scripts/premerge.py --output docs/engineering/verification/anvil-076-2026-11-12/premerge.json
```

`scripts/premerge.py` records the command as `make premerge`. Backend result: `Ran 1289 tests in 343.318s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 112.827s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

`make check` is part of the repository's check list and was not a separate premerge step. The backend run printed `System check identified no issues (0 silenced).`

## Counts against main `4dd5060` and `1d4ecd1`

Discovery with this interpreter, without executing the suite:

- `4dd5060e632bae598003bf3a51a474709fe8c7ac`, from the [ANVIL-013 record](../anvil-013-2026-11-11/report.md): `--exclude-tag=pg` collected 1285, `--tag=pg` collected 28.
- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips. `--tag=pg`: 28 collected.
- `5a794b2120eb23fca2b0fc369abd054f184c8618`, `--exclude-tag=pg`: 1289 collected, 0 decorator skips. `--tag=pg`: 28 collected.

The executed premerge run passed 1289, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. That is 4 more executed backend tests than `4dd5060` and than `1d4ecd1`. The four tests are `CompilerOverflowTests.test_strict_budget_raises_context_overflow_error`, `CompilerOverflowTests.test_trim_budget_records_omitted_and_truncated_blocks`, `CompilerOverflowTests.test_estimate_tokens_is_deterministic_for_the_same_input`, and `CompilerOverflowTests.test_results_do_not_claim_qualified_or_production_ready`. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `1d4ecd1`.

The local virtualenv had `requirements.txt` and the optional pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.vision.txt`, `requirements.inference.txt`, CPU `torch==2.13.0`, and `pypdfium2==5.14.0`. Discovery on `1d4ecd1` and on this SHA with that interpreter shows 0 decorator skips in the `--exclude-tag=pg` suite.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `1d4ecd1` without those variables.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` pins `pypdf==6.21.4`. That file is unchanged from `1d4ecd1`. No ignore was added.

## Gate G-secrets

No allowlist was added. `.gitleaks.toml` is the ANVIL-043 file already on `1d4ecd1`. Stock config means the upstream `config/gitleaks.toml` for that gitleaks version, passed with `--config`. Raw finding reports are not committed. `Secret` in the uncommitted stock report is `REDACTED`.

- `gitleaks` 8.30.1 `dir .` on the working tree, using the repository config, scanned 36.28 MB and exited 0 (`no leaks found`). Console: `gitleaks-dir.json`.
- `gitleaks` 8.28.0 `dir .` with the stock config exited 0 (`no leaks found`). Console: `gitleaks-8.28-dir.json`.
- `gitleaks` 8.30.1 `dir .` with the stock config exited 1 with 370 findings, all rule `generic-api-key`, all tags `decoded:unicode` and `decode-depth:1`. Console: `gitleaks-8.30-stock.json`. The path and line set matches [the ANVIL-043 finding list](../anvil-043-2026-11-11/findings.json): 366 locations, 370 findings, nothing extra and nothing missing. Every row in that list names commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. None of the 370 paths are `modelanvil/context_lab/test_compiler_overflow.py` or `modelanvil/context_lab/compiler.py`.

`web/storybook-static/` from `build-storybook` added one `generic-api-key` hit while it was on disk. That directory is build output. It was removed before the recorded `gitleaks dir` scans. It is not in the commit.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Acceptance criteria

- `modelanvil/context_lab/test_compiler_overflow.py` uses `ContextRecipeVersion` and `ContextBlockRevision` rows accepted by `ContextCompiler`.
- `fail_on_overflow` with a budget below the full prompt raises `ContextOverflowError` and the message names the full token count.
- `trim_lowest_priority` records the history block in `omitted_blocks` with reason `token_budget_overflow` and records the evidence block in `truncated_blocks` with reason `block_token_limit`. The included keys and the omitted keys together are the blocks that had content.
- `trim_optional_evidence` records the evidence block as omitted and marks the truncation `included_in_final` false.
- `estimate_tokens` returns the same integer for equal strings, including a fresh copy of the same text. Two compiles of the same inputs return the same prompt, token count, omissions, and truncations.
- The serialized compilation result and the strict overflow message do not contain `qualified` or `production-ready`.
- No model execution and no GPU. `test_budget.py`, `test_context_lab.py`, `test_measured.py`, `test_positions.py`, and `models.py` are unchanged.

## Result

`make premerge` exited 0 with no runtime skip, xfail, or timeout. Backend passed 1289, frontend 249, PostgreSQL 28. `pip-audit` exited 0 on every root requirements file. `gitleaks dir` exited 0. The 370 stock findings from gitleaks 8.30.1 match the ANVIL-043 list on `75e2565`. The pull request stays open.
