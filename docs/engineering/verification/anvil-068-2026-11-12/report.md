# ANVIL-068 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. Test, check, audit, and gitleaks records were written by `.venv/bin/python scripts/local_evidence.py` or `scripts/premerge.py` from a clean `git status --porcelain`.

The measured tree is `80b063d08c4383407efc47b96c4552093d05cb8d`. This report is the following docs-only commit. The commands below ran at `80b063d08c4383407efc47b96c4552093d05cb8d`.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T15:02:59+00:00 | `make premerge` | 0 | 1288 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1288, 249, 28 | 0 |
| `make-check.json` | 2026-11-12T14:44:30+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-12T14:45:38+00:00 | `pip-audit -r` on every `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:44:32+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:44:35+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output /tmp/anvil068-evidence/premerge.json` with Node v24.22.3 on `PATH`. `scripts/premerge.py` records the command as `make premerge`. Backend result: `Ran 1288 tests in 341.036s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 118.730s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

`make check` printed `System check identified no issues (0 silenced).`

## What changed

`modelanvil/runners/gguf_validation.py` reads the 24-byte header in the calling process. A short header, a bad magic, an unsupported version or count, or a file that ends at the header raises `ValueError` before `subprocess.run`. A header that passes that check still goes to the bounded child process, which runs `inspect_gguf` and does not load a runtime.

`modelanvil/runners/test_gguf_validation_bounds.py` adds three tests:

- `test_invalid_bytes_are_rejected_without_spawning` writes truncated and invalid bytes to a temp file. `inspect_gguf` and `validate_gguf` raise `ValueError`. Patched `subprocess` entry points, `GGUFSession`, and `inference.generate` raise if called.
- `test_result_does_not_claim_the_model_is_ready` builds a 3-by-4 float fixture with `GGUFWriter`. The returned dict has `load_tested` false and `validation` set to `structure-and-payload-bounds`. Keys and strings do not carry `production-ready`, `qualified`, or `first`. The child process is `gguf_validation.py`.
- `test_docstrings_and_raised_messages_omit_claim_words` scans the module source, docstrings, and the `ValueError` text from those invalid bytes for `production-ready`, `qualified`, and `first`.

No real weight file, GPU, or download is used. `test_gguf_validation.py` and `gguf_runtime.py` are unchanged.

## Counts against main `4dd5060` and `1d4ecd1`

Discovery with this interpreter, without executing the suite:

- `4dd5060` on the ANVIL-012 and ANVIL-043 records, `--exclude-tag=pg`: 1285 passed. PostgreSQL: 28 passed. Frontend: 249 passed.
- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips. `--tag=pg`: 28 collected.
- This SHA, `--exclude-tag=pg`: 1288 collected, 0 decorator skips. `--tag=pg`: 28 collected.

The executed premerge run passed 1288, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. That is 3 more backend tests than `4dd5060` and than `1d4ecd1`. The three added tests are the methods named above. This ticket adds no frontend test and no `pg` test.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `4dd5060` and on `1d4ecd1` without those variables.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` on this tree pins `pypdf==6.21.4` (`285b762`). No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No new allowlist, no baseline, and no edit to `.gitleaks.toml`. The raw reports are not committed.

- `gitleaks dir . --redact` on the working tree at `80b063d08c4383407efc47b96c4552093d05cb8d`, before the Storybook build, exited 0 (`no leaks found`), 34.78 MB. Record: `gitleaks-dir.json`.
- After `make premerge`, `web/storybook-static/` was removed. It is gitignored and is not in the commit. A later `gitleaks dir . --redact` on that tree exited 0 (`no leaks found`), 35.99 MB.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. Findings on `80b063d08c4383407efc47b96c4552093d05cb8d`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0. All 36 fingerprints are on `reviews/ANVIL-017-gitleaks-history.md`. The 370 working-tree hits from `75e2565` stay with ANVIL-043. Record: `gitleaks-detect.json`.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

Invalid GGUF bytes are rejected before a child process. The inspection result does not claim the model is ready. `make premerge` exited 0 with 1288, 249, and 28 passed and no runtime skip, xfail, or timeout. `pip-audit` exited 0. `gitleaks dir` exited 0. The pull request stays open.
