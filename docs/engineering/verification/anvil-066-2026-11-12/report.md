# ANVIL-066 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when `make premerge` started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `b46bdb6fe5cb1b15ecd9d2b6e4b1944afde02f70`. This report is the following documentation commit. The commands below ran at `b46bdb6fe5cb1b15ecd9d2b6e4b1944afde02f70`.

`modelanvil/runners/test_tool_sandbox_bounds.py` plants `; rm`, `$(uname)`, backticks, `sh -c`, and argv lists in the user/model `code` field, and plants the same command shapes in `seconds`. `validate()` / `run()` raise `ValueError` before any process for an argv list, for `bytes`, and for a non-integer `seconds`. A command string that is in-range text is not passed to a shell: mocked Docker `subprocess` calls use a list argv with `shell` false, `argv[0]` is the operator path returned for the literal name `docker`, and the container command is `/usr/local/bin/python` with the fixed guard script. The planted text appears as JSON `code` on stdin. No live Docker daemon is required for these tests. `modelanvil/runners/tool_sandbox.py` is unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:51:30+00:00 | `make premerge` | 0 | 1291 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1291, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:52:18+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:52:18+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. This run passed `--output /tmp/anvil066-evidence/premerge.json` so it did not overwrite `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1291 tests in 314.635s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 113.281s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `DATABASE_PASSWORD` does not appear in `premerge.json`.

The six new methods are `ToolSandboxCommandBoundsTests.test_argv_list_is_refused_before_a_process`, `test_non_text_command_is_refused_before_a_process`, `test_seconds_field_command_is_refused_before_a_process`, `test_shell_command_string_is_not_a_process_command`, `test_operator_command_ignores_a_planted_binary_path`, and `test_quoted_command_text_stays_python_source_on_stdin`.

## Gate G-local

Label: `local`. Code SHA `b46bdb6fe5cb1b15ecd9d2b6e4b1944afde02f70`.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`, from the ANVIL-042 premerge record on that history: 1285 backend, 249 frontend, 28 PostgreSQL, 0 skipped. This run passed 1291, 249, and 28. Backend is 6 above that baseline. Frontend and PostgreSQL match it. `git diff -U0 4dd5060..1d4ecd1` adds three `def test_` methods in `tests/test_premerge.py`. Those names are absent from this premerge log. `manage.py test` collected 1291 tests, and the six methods above are the Django tests this branch adds.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs, and `manage.py test --noinput --tag=pg` passed those 28.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. Their bodies are unchanged.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Log: `pip-audit.txt`.

`requirements.documents.txt` on this base already pins `pypdf==6.21.4` (ANVIL-042). This ticket does not change that pin and does not add an ignore.

## Gate G-secrets

`gitleaks` 8.30.1. No new config, baseline, or allowlist. `.gitleaks.toml` is the file ANVIL-043 added; this ticket does not edit it.

`gitleaks dir . --redact` on the working tree at `b46bdb6fe5cb1b15ecd9d2b6e4b1944afde02f70` exited 0 (`no leaks found`). Console: `gitleaks-dir.summary.txt`. The same command on this evidence directory, before this report was added, also exited 0.

Hits on `75e2565a83b4b0cf96aebe793a9da6823e67d165` stay with ANVIL-043. This ticket does not add an allowlist.

A later `gitleaks dir` during the Storybook build saw one `generic-api-key` hit in gitignored `web/storybook-static/assets/iframe-CEU7fPb6.js`. That directory is build output (`storybook-static/` in `.gitignore`) and is not in this commit. Removing it restored `gitleaks dir . --redact` to exit 0.

## Gate G-rag

This change does not add a retrieval measurement and does not add public wording about retrieval quality. The premerge log still runs the existing retrieval control.

## Result

`make premerge` exited 0. G-local counts are at or above `4dd5060`. G-skip has no runtime skip, xfail, or timeout. G-audit exited 0 with no ignore. G-secrets `gitleaks dir` exited 0 and no allowlist was added. The pull request stays open.
