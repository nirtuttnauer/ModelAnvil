# Gates, TASK-16 MLX optimization profile

Label: `local`. Measured at `6226dc6`, this branch's MLX optimization profile, benchmark and telemetry on top of `main` `5b28613` (PR #136).

Measured commit: `6226dc6a3fd5601894a5847a2010857fd840ea4e`. `git status --porcelain` was empty before each command. Records use `docs/engineering/schemas/local-evidence.v1.json`.

Machine: `Mac`, macOS-27.2.1-arm64-arm-64bit (Apple M5 Pro), Python 3.12.15, Node v24.22.3.

Fixtures on this host: `MODELANVIL_MLX_TEST_MODEL_DIR` (pinned SmolLM2-135M, every file hash checked) and `MODELANVIL_GGUF_TEST_MODEL` (FP16 GGUF converted from the pinned SmolLM2-135M-Instruct).

## G-local and G-skip

`scripts/premerge.py --output ...` exited 0.

| Run | Command | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- |
| backend | `python manage.py test --noinput --exclude-tag=pg --exclude-tag=linux -v 1` | 1463 | 35 | 1463 | 0 / 0 / 0 |
| frontend-install | `npm --prefix web ci` | 0 | 0 | 0 | 0 / 0 / 0 |
| frontend | `npm --prefix web test` | 252 | 0 | 252 | 0 / 0 / 0 |
| frontend-build | `npm --prefix web run build` | 0 | 0 | 0 | 0 / 0 / 0 |
| frontend-storybook | `npm --prefix web run build-storybook` | 0 | 0 | 0 | 0 / 0 / 0 |
| pgvector | `python manage.py test --noinput --tag=pg -v 1` | 34 | 0 | 34 | 0 / 0 / 0 |

Fixture tests not collected: 0, so all five MLX model tests ran in the PostgreSQL run on the Apple GPU. Against the previous record ([ANVIL-003 at `29b0d75`](../../anvil-003-2026-11-15/gates/gates.md): 1455 / 249 / 30), backend is 1463 (+8 new tests in `test_mlx_runtime`, `test_accelerator_support` and related modules), frontend 252 (+3 in `training-telemetry.test.mjs`) and PostgreSQL 34 (+4 MLX fixture tests tagged `pg`, which is why 35 instead of 31 are excluded from the backend run).

Excluded before the run by the `linux` tag on this macOS host: `modelanvil.runners.alignment.test_grpo.IsolatedVerifierTests.test_linux_verifier_measures_its_own_image_after_a_large_parent`. It checks Linux exec RSS inheritance and runs in the Linux backend run and in CI. Every other excluded ID is a `pg` test and ran in the PostgreSQL run (34 of 34).

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

Stock configuration means the upstream default `config/gitleaks.toml` of that gitleaks version, passed with `--config`, because gitleaks otherwise loads the repository's `.gitleaks.toml` allowlist from ANVIL-043. The working-tree scan reads `git archive HEAD` extracted to a temporary directory, which is the tracked tree of a clean checkout. Raw reports are not committed: gitleaks copies each finding's commit-author email into them.

- gitleaks 8.28.0 (ANVIL-017's scanner, release tarball SHA-256 `d942f3ad147250c9edbaab3fed9e482f98d3b59ba10ae97b8d75647e3ade492c`), stock, `dir`: 0 findings.
- gitleaks 8.28.0, stock, `detect --log-opts="HEAD --remotes=origin --tags"`: findings 411; unique fingerprints 391; triage rows 391; not on list 0. The triage list is `reviews/ANVIL-017-gitleaks-history.md`.
- gitleaks 8.30.1 with the repository `.gitleaks.toml`, `dir`: 0 findings.

## G-rag

`premerge.json` stdout includes the existing `TASK69_CONTROLS` measurement. It is a small correctness check: held-out nDCG on 200 SciFact documents next to a seeded random-vector baseline, as documented in `README.md` (MiniLM nDCG@5 1.0000 next to seeded random 0.0215 on 20 judged queries). This change adds no RAG number.
