# Gates, anvil-068-2026-11-12, Mac re-run at 417480d

Label: `local`. Measured tree: `417480d6904ae5a0037e5260924a40b6afde1b59`, the head of PR #114 before this docs-only commit. It is `ed30e3a` plus one test change: `test_result_does_not_claim_the_model_is_ready` in `modelanvil/runners/test_gguf_validation_bounds.py` now has `@skipUnless(importlib.util.find_spec('gguf'), ...)`, the same guard as `test_gguf_validation.py`. Without it, the CI backend job, which installs only `requirements.txt`, failed with `ModuleNotFoundError: No module named 'gguf'`. No product code changed after `80b063d`.

`git status --porcelain` was empty before each command and after `make premerge`. Records use `docs/engineering/schemas/local-evidence.v1.json` and were written by `scripts/local_evidence.py` or `scripts/premerge.py`.

Machine: `Nirs-MacBook-Pro.local`, macOS-27.0.1-arm64-arm-64bit, Python 3.12.15 from the shared `anvil-gates` virtual environment, Node v24.22.3 first on `PATH`.

Fixtures on this host: `MODELANVIL_MLX_TEST_MODEL_DIR` (pinned SmolLM2-135M) and `MODELANVIL_GGUF_TEST_MODEL` (FP16 GGUF from the pinned SmolLM2-135M-Instruct), as in `anvil-010-2026-11-12/gates.md`.

Host coordination: `make premerge` held the host-wide test lock from 18:12:23 to 18:17:33 (+02:00). Another session's memory-measurement batch released that lock at 18:12:20. No other test suite or measurement ran during the premerge.

## G-local and G-skip

`make premerge` (run as `scripts/premerge.py --output ...`) exited 0. Record: `premerge.json`.

| Run | Command | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- |
| backend | `manage.py test --noinput --exclude-tag=pg --exclude-tag=linux -v 1` | 1288 | 30 | 1288 | 0 / 0 / 0 |
| frontend-install | `npm --prefix web ci` | 0 | 0 | 0 | 0 / 0 / 0 |
| frontend | `npm --prefix web test` | 249 | 0 | 249 | 0 / 0 / 0 |
| frontend-build | `npm --prefix web run build` | 0 | 0 | 0 | 0 / 0 / 0 |
| frontend-storybook | `npm --prefix web run build-storybook` | 0 | 0 | 0 | 0 / 0 / 0 |
| pgvector | `manage.py test --noinput --tag=pg -v 1` | 29 | 0 | 29 | 0 / 0 / 0 |

Fixture tests not collected: 0. The MLX native adapter test (tagged `pg`) ran in the PostgreSQL run, and `GGUFNative` ran in the backend run. The `anvil-gates` environment has `gguf`, so the newly guarded test ran and passed; it was not skipped.

Excluded by the `linux` tag on this macOS host: `modelanvil.runners.alignment.test_grpo.IsolatedVerifierTests.test_linux_verifier_measures_its_own_image_after_a_large_parent`. It ran in the Linux backend run recorded at `80b063d` (`../premerge.json`) and runs in the CI backend job. Every other excluded ID is a `pg` test and ran in the PostgreSQL run.

Counts against the Linux record at `80b063d`: backend 1288 there (`--exclude-tag=pg`, two fixture IDs not collected) and 1288 here (one `linux` test excluded, `GGUFNative` collected). PostgreSQL 28 there and 29 here (the MLX fixture test). Frontend 249 on both.

## G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off --timeout 180 -r <file>` for every root `requirements*.txt`, no `--ignore-vuln`. Overall exit 0. Record: `pip-audit.json`.

- `requirements.audio.txt`: exit 0
- `requirements.documents.txt`: exit 0
- `requirements.embeddings.txt`: exit 0
- `requirements.gpu.txt`: exit 0
- `requirements.inference.txt`: exit 0
- `requirements.production.txt`: exit 0
- `requirements.selfhost.lock.txt`: exit 0
- `requirements.specialists.txt`: exit 0
- `requirements.tools.txt`: exit 0
- `requirements.txt`: exit 0
- `requirements.vision.txt`: exit 0

## G-secrets

gitleaks 8.28.0 (ANVIL-017's scanner) with the upstream v8.28.0 `config/gitleaks.toml` passed by `--config`, because gitleaks otherwise loads the repository's `.gitleaks.toml` allowlist from ANVIL-043. The working-tree scan reads `git archive HEAD` extracted to a temporary directory. Raw reports are not committed.

- `dir`: 0 findings. Record: `gitleaks-8.28-dir.json`.
- `detect --log-opts="HEAD --remotes=origin --tags"`: exit 1, 288 commits, 411 findings, all `generic-api-key`, 391 unique fingerprints, 0 not on `reviews/ANVIL-017-gitleaks-history.md`, 0 on `417480d`. Record: `gitleaks-8.28-detect.json`. The history scope is this branch plus GitHub's refs; local-only branches that were never pushed are outside it.
- The five records in this folder were scanned the same way before commit: 0 findings.

gitleaks 8.30.1 was not run for this re-run.

## G-rag

`premerge.json` stdout includes the existing `TASK69_CONTROLS` measurement: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, development nDCG real `0.982545`, on 200 documents and 412 chunks. That is a small correctness check. Its documented baseline in `README.md` is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change adds no RAG number.
