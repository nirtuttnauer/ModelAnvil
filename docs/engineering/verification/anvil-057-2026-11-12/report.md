# ANVIL-057 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`. The G-local comparison SHA in the ticket is `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

The measured tree is `7dafbaa5c543e9a58ef633c486d548aa9664832b`. This report is the following documentation commit. The commands below ran at `7dafbaa5c543e9a58ef633c486d548aa9664832b`.

`modelanvil/cli/test_cli_help.py` walks `build_parser()`. For every leaf subcommand it invokes `--help`, requires exit code 0, and requires non-empty help. The documented summary is the `help=` string. Argparse prints that string on the parent command, wrapping long lines, so the check compares the summary to the parent help with whitespace collapsed. A separate test requires the same non-empty `help=` on every subcommand, including groups. Generated help from every parser in the CLI tree must not contain `production-ready`, `qualified`, `best`, or `first`.

Every subcommand in `modelanvil/cli/main.py` already had `help=`. This change does not edit `main.py`, command behavior, config show, or client code.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:51:14+00:00 | `make premerge` | 0 | 1306 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1306, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:44:10+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:44:12+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:44:15+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` is `scripts/premerge.py`. The script records the command as `make premerge`. This run passed `--output` so it did not rewrite `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1306 tests in 350.296s` then `OK`. Frontend: 249 passed, 0 failed, 0 skipped, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 111.238s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record.

The audit command was `bash /tmp/anvil057-pip-audit.sh`. It runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`.

## Gate G-local

Label: `local`. Code SHA `7dafbaa5c543e9a58ef633c486d548aa9664832b`.

Discovery with this interpreter, without executing the suite:

- `4dd5060e632bae598003bf3a51a474709fe8c7ac`, recorded by ANVIL-012 and repeated on later main runs: 1285 backend, 249 frontend, 28 PostgreSQL, 0 skipped.
- Parent `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg` via the project runner: 1285 collected, 0 decorator skips. `--tag=pg`: 28 collected.
- This SHA, same discovery: 1306 collected, 0 decorator skips. `--tag=pg`: 28 collected.

The executed premerge run passed 1306, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. That is 21 backend tests above `4dd5060` and above parent `1d4ecd1`. The 21 tests are `CliHelpCoverageTests` in `modelanvil/cli/test_cli_help.py`: one `--help` test for each of the 18 leaves (`config show`, `config set`, `datasets create`, `datasets list`, `datasets get`, `training launch`, `training get`, `evaluation launch`, `evaluation get`, `releases create`, `releases export`, `releases sbom`, `rag query`, `context-lab compile`, `dataset-bank search`, `workers enroll`, `workers egress`, `journey smoke`), plus `test_help_text_omits_reserved_claims`, `test_every_subcommand_summary_is_documented`, and `test_root_help_exits_zero`. This ticket adds no frontend test and no `pg` test.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `1d4ecd1` without those variables.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` pins `pypdf==6.21.4`. ANVIL-042 moved that pin. The seven pypdf CVEs named on `4dd5060` (`CVE-2026-119203` through `CVE-2026-119209`) are not reported. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. `gitleaks dir` loads the repository `.gitleaks.toml` from ANVIL-043. This ticket does not edit that file and does not add an allowlist. Raw finding reports are not committed.

- `gitleaks dir . --redact` at `7dafbaa5c543e9a58ef633c486d548aa9664832b` exited 0, `no leaks found`, 34.78 MB. Record: `gitleaks-dir.json`.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0. Findings on `7dafbaa5c543e9a58ef633c486d548aa9664832b`: 0. All 36 fingerprints are on `reviews/ANVIL-017-gitleaks-history.md`. Record: `gitleaks-detect.json`.

The 370 working-tree hits that gitleaks 8.30 reports without the ANVIL-043 config are the decoded-digest `generic-api-key` set introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165`. ANVIL-043 owns that triage. This ticket does not reopen it.

After these evidence files were written, and after the gitignored `web/storybook-static/` build was removed, `gitleaks dir . --redact` exited 0.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

`modelanvil datasets list --help` and the other 17 leaves exit 0. Parent help includes each documented summary. Generated CLI help does not contain the four reserved claim strings. `make premerge` exited 0. Counts are above `4dd5060` and above `1d4ecd1` by the 21 new backend tests. `pip-audit` exited 0. `gitleaks dir` exited 0. The pull request stays open.
