# ANVIL-058 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `93999390c349b79501259bb8aa30195e076af3dd`. This report is the following documentation commit. The commands below ran at `93999390c349b79501259bb8aa30195e076af3dd`.

`save_config` creates or replaces the CLI config file with mode `0o600` on POSIX. `redacted_config()` returns a copy whose token and password-like values are `***`. `load_config` and `get_setting` still return the stored value to the process. `config show` prints the redacted copy. Tests set `MODELANVIL_CONFIG` to a temporary path. The runs below do not contain the stored token text.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:52:02+00:00 | `make premerge` | 0 | 1290 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1290, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:56:29+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:56:37+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:56:39+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. This run passed `--output /tmp/anvil-058-evidence/premerge.json` and copied the record here. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1290 tests in 315.600s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 110.908s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command was `/tmp/anvil-058/pip-audit.sh`. It runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `exit 0` for each file. Stderr records `No known vulnerabilities found` for each file.

## Gate G-local

Label: `local`. Code SHA `93999390c349b79501259bb8aa30195e076af3dd`.

Discovery with this interpreter, without executing the suite:

- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips.
- This SHA, `--exclude-tag=pg`: 1290 collected, 0 decorator skips.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run on this SHA passed 1290, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The five added tests are `CliConfigModeTests.test_save_config_mode_is_owner_read_write`, `CliConfigModeTests.test_save_config_uses_temporary_path_not_home`, `CliConfigModeTests.test_load_config_and_get_setting_return_the_stored_value`, `CliConfigRedactionTests.test_redacted_config_never_includes_the_raw_token`, and `CliConfigRedactionTests.test_config_show_prints_placeholder`. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `1d4ecd1`.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`: the ANVIL-012 premerge record on that history passed 1285 backend tests, 249 frontend tests, and 28 PostgreSQL tests. This run is above that backend count and equal on frontend and PostgreSQL.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `1d4ecd1` without those variables.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command on this Linux host is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded `pg` IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` pins `pypdf==6.21.4`. That pin is unchanged from `1d4ecd1`. This ticket does not add an ignore.

## Gate G-secrets

`gitleaks` 8.30.1. The repo config is `.gitleaks.toml` from ANVIL-043. This ticket does not edit that file and does not add an allowlist.

- `gitleaks dir . --redact` exited 0 with `no leaks found`, 35.11 MB. Record: `gitleaks-dir.json`.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. A separate redacted JSON report, not committed, shows those 36 on eight earlier commits and on the same eleven paths recorded by ANVIL-043. None are on `93999390c349b79501259bb8aa30195e076af3dd`. None are under `modelanvil/cli/`. The 370 `generic-api-key` hits introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165` stay covered by the existing ANVIL-043 allowlist.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is the existing small correctness check. This change does not claim a new RAG number.

## Acceptance

- `save_config` creates a new file at mode `0o600` and replaces an existing `0o644` file with mode `0o600`, including under umask `0`.
- `load_config` and `get_setting` return the stored token to the process.
- `redacted_config()` returns a copy. Token and password-like keys, including nested keys, are `***`. The copy does not contain the stored token. The input mapping is left unchanged.
- `config show` and `config show --json` print that copy. Help strings in `modelanvil/cli/main.py` are unchanged. `modelanvil/cli/client.py` is unchanged.
- Tests use a temporary `MODELANVIL_CONFIG` path and check that `~/.modelanvil/config.json` is not written.
