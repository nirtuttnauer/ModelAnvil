# ANVIL-002 local evidence, 29 October 2026

Label: `local`. Machine: `cursor`, Linux 6.12.94+ x86_64, Python 3.12.3, Node v22.23.4. Records use `docs/engineering/schemas/local-evidence.v1.json` and were written by `.venv/bin/python scripts/local_evidence.py` from a clean `git status --porcelain`.

## Records

| File | SHA the command ran against | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `make-check.json` | `64829d2eb12015be841151dd2cebc0d53e602aed` | `make check` | 0 | 0 | 0 | 0 | 0 |
| `backend-sqlite.json` | `8efb2721f4dcf98fd50accca6c2ad253204d8d66` | `manage.py test --noinput --exclude-tag=pg` | 0 | 1256 | 28 | 1256 | 0 |
| `frontend-npm-test.json` | `8efb2721f4dcf98fd50accca6c2ad253204d8d66` | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |
| `backend-pg.json` | `ec5a56369988376bc126b77880ae126f8080ec79` | `manage.py test --noinput --tag=pg` | 0 | 28 | 0 | 28 | 0 |

`64829d2eb12015be841151dd2cebc0d53e602aed` is the implementation commit. The later SHAs add only these evidence records. `backend-sqlite.json` lists the 28 excluded test IDs. The PostgreSQL command ran with `DATABASE_ENGINE=postgresql`, local database `modelanvil`, `RABBITMQ_URL=amqp://guest:guest@localhost:5672/%2F`, pgvector 0.8.1, and the pinned MiniLM, SciFact, and SmolLM2 caches offline.

## Counts against baseline `3200915`

Baseline `3200915506331979c712c17ffd0b1817f95fda75` on this machine, with the same optional Linux packages installed:

- Default SQLite discovery collected 1237 tests. Six of those are decoration-time skips: the five optional skips named in the status ledger, plus `GGUFNative.test_actual_cpu_generation_cancellation_and_unload`. That leaves 1231 tests that the runner would execute.
- The `pg` tag collected 24 tests.
- Frontend `npm test` at that SHA: 234 passed, 0 skipped, exit 0.

This branch:

- Default SQLite run: 1256 passed. That is 25 more executed tests than the baseline's 1231. Those 25 landed on `main` after `3200915` (`test_deployment_capabilities`, `test_guided_evaluation`, `test_trustworthy_roadmap`, and `ModelWorkspaceTests.test_provisioned_transformer_inference_does_not_connect_to_external_services`).
- The six baseline skips are absent from the default run. Four now run in the PostgreSQL suite. The MLX and GGUF tests are collected only when their fixture paths are set.
- PostgreSQL run: 28 passed. That is the baseline 24 `pg` tests plus the four retagged tests.
- Frontend: 249 passed. That is 15 more than 234, from frontend tests added on `main` after `3200915` (`classification-starter`, `css-policy`, `evidence-label`, `improvement`, `improvement-report`, `model-export`, and the onboarding-setup edits).

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The three test records above have zero of each. The default command excludes `pg` before the run and lists those IDs. The PostgreSQL command runs that tag. Every ID collected on this host is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on the test records as `fixture_tests_not_collected`. The skip gate stays open for those two IDs until a host with the fixtures runs them. Their bodies are unchanged.

## Gate G-audit

`pip-audit -r <file>` for every `requirements*.txt`, with no `--ignore-vuln`. Log: `pip-audit.log`. Ten files reported no known vulnerabilities and exited 0: `requirements.txt`, `requirements.production.txt`, `requirements.documents.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.embeddings.txt`, `requirements.audio.txt`, `requirements.vision.txt`, `requirements.tools.txt`, `requirements.selfhost.lock.txt`.

`requirements.specialists.txt` exited 1. `pip-audit` could not resolve `mlx-metal==0.32.3` on this Linux host (`No matching distribution found`). No ignore was added. This gate is unmet.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml` in the repo.

- `gitleaks dir --redact` on the working tree exited 1 with 404 findings, all rule `generic-api-key`. Console: `gitleaks-dir.summary.txt`. Findings: `gitleaks-dir.txt`.
- `gitleaks detect --redact` over 163 commits exited 1 with 411 findings, all rule `generic-api-key`. Console: `gitleaks-detect.summary.txt`. Findings: `gitleaks-detect.txt`.

The saved reports redact match text (`Secret` is `REDACTED`). The finding identity is the rule, file, line, and commit. There is no QA-signed ANVIL-017 triage list anywhere in the repository, so none of the 411 history findings can be matched to one. This gate is unmet.

## Gate G-rag

`backend-pg.json` stdout includes one retrieval measurement, `TASK69_CONTROLS`: held-out nDCG real 1.0 next to seeded random 0.021535, on 200 documents. That is the existing small correctness check. The documented baseline next to it is MiniLM nDCG@5 1.0 next to seeded random 0.0215 on 20 queries / 200 SciFact docs. This change does not claim a new RAG number.

## Merge

The pull request stays open. ANVIL-017 is absent, `gitleaks dir` found 404 leaks, `pip-audit` cannot resolve `requirements.specialists.txt` on Linux, and the MLX and GGUF fixture tests did not run on this host.
