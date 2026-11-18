# ANVIL-078 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7`. That commit is a descendant of `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

The measured tree is `b5913b957ed71cc54054c75ad29ca8f36eeb6f18`. This report is the following documentation commit. The commands below ran at `b5913b957ed71cc54054c75ad29ca8f36eeb6f18`.

## Wording

`modelanvil/accelerators.py` was not edited.

Before this commit, on `56b35cc`, inventory and diagnose already returned `model_qualified: false` and `production_qualified: false`. The CLI error object included `production_qualified: false`. The module docstring said availability and primitive diagnostics do not qualify a model. The source did not contain `production-ready`, `best`, or `first`, and it did not use `qualified` as a positive claim.

After this commit the module is the same. Those false flags stay because `modelanvil/test_accelerators.py` asserts `production_qualified` is false on inventory and on CLI output. That file is outside this ticket. A false value does not mark hardware or a model as qualified. Removing the keys would fail those existing tests.

`modelanvil/test_accelerator_wording.py` locks the current behavior with mocked PyTorch and no GPU:

- Inventory without a framework, with visible CUDA, ROCm, XPU, and MPS devices, and after an enumeration error does not carry a truthy qualification or production-ready field.
- A successful diagnostic and a diagnostic failure do not either.
- CLI default messages do not either.
- The module source rejects `production-ready`, the words `best` and `first`, a positive use of `qualified`, and any claim flag assigned to a value other than false. The existing phrase `do not qualify` remains allowed.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T15:07:54+00:00 | `make premerge` | 0 | 1292 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1292, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:44:56+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:43:31+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:43:50+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. Its default output path is `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. This run passed `--output` so that ANVIL-009 record was not overwritten. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1292 tests in 333.203s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 109.370s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command was `bash /tmp/anvil078/pip-audit.sh`. It runs `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `EXIT 0` for each file. Stderr records `No known vulnerabilities found` for each file.

Raw gitleaks finding reports are not committed. The recorded stderr is the scanner summary.

## Gate G-local

Label: `local`. Code SHA `b5913b957ed71cc54054c75ad29ca8f36eeb6f18`.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`, from the ANVIL-012 premerge record: 1285 backend, 249 frontend, 28 PostgreSQL, 0 skipped. This run passed 1292, 249, and 28, with 0 skipped. The seven added tests are the methods on `AcceleratorWordingTests` in `modelanvil/test_accelerator_wording.py`. Discovery on `56b35cc` with this interpreter, excluding the new file, is 1285 `--exclude-tag=pg` tests and 28 `--tag=pg` tests. The only test-file edit between `4dd5060` and `56b35cc` is an assertion string in `modelanvil/api/test_dataset_preparation_http.py`. This ticket adds no frontend test and no `pg` test.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the same 28 excluded IDs as the ANVIL-042 record, and `manage.py test --noinput --tag=pg` passed those 28.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on main without those variables. Their bodies are unchanged.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` on this tree pins `pypdf==6.21.4`. ANVIL-042 moved that pin from 6.21.2, which was the release `pip-audit` reported for CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. This run does not report those CVEs. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No `--config` argument, no baseline, and no new allowlist. The tool loads the existing `.gitleaks.toml` from ANVIL-043 because that file is in the repository. This ticket does not edit it. Raw finding reports are not committed.

- `gitleaks dir . --redact` at `b5913b957ed71cc54054c75ad29ca8f36eeb6f18` scanned 34.35 MB in 1.38s and exited 0. The summary is `no leaks found`. Console: `gitleaks-dir.json`.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 219 commits and 41.88 MB, and exited 1 with 36 findings, all rule `generic-api-key`. None are on `75e2565a83b4b0cf96aebe793a9da6823e67d165`, and none are on `b5913b957ed71cc54054c75ad29ca8f36eeb6f18`. The 36 file counts match the history remainder ANVIL-043 recorded: `hf_runtime.py` 7, `scripts/audio_candidate_infer.py` 7, `audio_runtime.py` 4, `scripts/vlm_candidate_infer.py` 4, `vlm_math.py` 4, `audio_math.py` 3, `scripts/verify_cpu_export.py` 3, and one each in `local-workflows.md`, `test_selfhost.py`, `chunking.py`, and `test_context_lab.py`. The 370 findings on `75e2565` are owned by ANVIL-043. Console: `gitleaks-detect.json`.

## Result

`make premerge` exited 0 with 1292 backend, 249 frontend, and 28 PostgreSQL tests, and with no runtime skip, xfail, or timeout. Backend is 7 above the ANVIL-012 count on `4dd5060`. Frontend and PostgreSQL match that count. `pip-audit -r` exited 0 on all 11 requirements files, with no ignore. `gitleaks dir` exited 0. Full-history `gitleaks detect` still reports the 36 historical `generic-api-key` findings outside the ANVIL-043 allowlist, and reports none from `75e2565`.
