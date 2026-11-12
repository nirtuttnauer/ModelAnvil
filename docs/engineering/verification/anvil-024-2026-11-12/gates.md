# Gates, anvil-024-2026-11-12

Label: `local`. Measured at this branch's head `7309b65`, which merges current `main` (with the premerge non-Linux fix from #88) into the ANVIL-024 commits. A first run at the same SHA failed three guided-evaluation and training tests outside this change while the host had about 150 MB free and a load average near 70; this re-run, with the host quieter, passed.

Measured tree: `7309b657ada018088f0e2385dc97c7b16e2e5855`. `git status --porcelain` was empty before each command. Records use `docs/engineering/schemas/local-evidence.v1.json`.

Machine: `Nirs-MacBook-Pro.local`, macOS-27.0.1-arm64-arm-64bit (Apple M5 Pro), Python 3.12.15, Node v24.22.3.

Fixtures on this host: `MODELANVIL_MLX_TEST_MODEL_DIR` (pinned SmolLM2-135M, every file hash checked) and `MODELANVIL_GGUF_TEST_MODEL` (FP16 GGUF converted from the pinned SmolLM2-135M-Instruct with the llama.cpp commit recorded in task74; its bytes differ from the task74 file only in converter metadata).

## G-local and G-skip

`make premerge` (run as `scripts/premerge.py --output ...`) exited 0.

| Run | Command | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- |
| backend | `-gates/.venv/bin/python manage.py test --noinput --exclude-tag=pg --exclude-tag=linux -v 1` | 1292 | 30 | 1292 | 0 / 0 / 0 |
| frontend-install | `npm --prefix web ci` | 0 | 0 | 0 | 0 / 0 / 0 |
| frontend | `npm --prefix web test` | 249 | 0 | 249 | 0 / 0 / 0 |
| frontend-build | `npm --prefix web run build` | 0 | 0 | 0 | 0 / 0 / 0 |
| frontend-storybook | `npm --prefix web run build-storybook` | 0 | 0 | 0 | 0 / 0 / 0 |
| pgvector | `nvil/.claude/worktrees/anvil-gates/.venv/bin/python manage.py test --noinput --tag=pg -v 1` | 29 | 0 | 29 | 0 / 0 / 0 |

Fixture tests not collected: 0. The MLX native adapter test ran in the PostgreSQL run and the GGUFNative test ran in the backend run.

Excluded before the run by the `linux` tag on this macOS host: `modelanvil.runners.alignment.test_grpo.IsolatedVerifierTests.test_linux_verifier_measures_its_own_image_after_a_large_parent`. It checks Linux exec RSS inheritance and runs in the Linux backend run and in CI. Every other excluded ID is a `pg` test and ran in the PostgreSQL run.

## G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, no `--ignore-vuln`. Overall exit 0.

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

Stock configuration means the upstream default `config/gitleaks.toml` of that gitleaks version, passed with `--config`, because gitleaks otherwise loads the repository's `.gitleaks.toml` allowlist from ANVIL-043. The working-tree scan reads `git archive HEAD` extracted to a temporary directory, which is the tracked tree of a clean checkout. Raw reports are not committed.

- gitleaks 8.28.0 (ANVIL-017's scanner), stock, `dir`: 0 findings.
- gitleaks 8.28.0, stock, `detect --log-opts="HEAD --remotes=origin --tags"`: 411 findings, 391 unique fingerprints, 0 not on `reviews/ANVIL-017-gitleaks-history.md`. The history scope is this branch plus GitHub's refs; local-only branches that were never pushed are outside it.
- gitleaks 8.30.1, stock, `dir`: 370 findings, all the decoded-digest `generic-api-key` shape triaged by ANVIL-043.
- gitleaks 8.30.1 with the repository `.gitleaks.toml`, `dir`: 0 findings.

## G-rag

`premerge.json` stdout includes the existing `TASK69_CONTROLS` measurement. It is a small correctness check: held-out nDCG on 200 SciFact documents next to a seeded random-vector baseline, as documented in `README.md` (MiniLM nDCG@5 1.0000 next to seeded random 0.0215 on 20 judged queries). The embedding-candidate ndcg@3 lines are the same kind of small correctness check. This change adds no RAG number.
