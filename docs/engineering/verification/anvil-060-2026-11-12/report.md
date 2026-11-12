# ANVIL-060 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. Each record was written by `.venv/bin/python scripts/local_evidence.py` or `.venv/bin/python scripts/premerge.py` from a clean `git status --porcelain`.

The measured tree is `5e47b845e2a90c527f4808eda8de52de87d9c9a6`. This report is the following docs commit. The commands below ran at that SHA.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`. G-local floor: `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

## Request id

`RequestIdMiddleware` already reads `X-Request-Id` with `uuid.UUID`. A value that parses is stored and returned as `str(uuid.UUID(...))`, the canonical `8-4-4-4-12` form. Empty, whitespace, and CR/LF values raise `ValueError`, and the middleware assigns `uuid7()` instead of copying the header onto the response. Uppercase hex is the same UUID in canonical form. `middleware.py` is unchanged. `ExceptionMiddleware` is unchanged; an error-cycle test checks the request id it already writes on the envelope and on `X-Request-Id`.

Before this commit there was no dedicated middleware test. After it, `modelanvil/core/test_middleware.py` runs eight tests through Django's `RequestFactory` and a direct middleware call. No live network.

The tests are:

- `test_missing_header_assigns_a_nonempty_id`
- `test_well_formed_header_is_reused`
- `test_uppercase_header_reuses_the_same_uuid`
- `test_empty_header_is_ignored`
- `test_crlf_header_is_not_reflected`
- `test_non_uuid_header_is_not_reflected`
- `test_generated_id_does_not_embed_credentials`
- `test_error_response_keeps_the_request_id`

Generated ids are UUID version 7. The response header is that canonical id. A bearer token on the request is not copied into the id.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:52:40+00:00 | `make premerge` | 0 | 1293 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1293, 249, 28 | 0 |
| `make-check.json` | 2026-11-12T14:44:04+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-12T14:43:35+00:00 | `bash /tmp/anvil060-pip-audit.sh` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:43:37+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:43:40+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output /tmp/anvil060-evidence/premerge.json` with Node v24.22.3 at the front of `PATH`. `scripts/premerge.py` records the command as `make premerge`. Backend: `Ran 1293 tests in 344.230s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then the frontend build and a Storybook build. PostgreSQL: `Ran 28 tests in 119.765s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

`make check` printed `System check identified no issues (0 silenced).`

## Counts against main `4dd5060` and `1d4ecd1`

Discovery with this interpreter, without executing the suite:

- `4dd5060e632bae598003bf3a51a474709fe8c7ac`, `--exclude-tag=pg`: 1285 collected. Two PDF tests are decorator skips on this interpreter because `pypdf` 6.21.4 is installed and that SHA checks an older pin. The executed ANVIL-013 premerge record on that line passed 1285 with 0 skipped.
- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips.
- This SHA, `--exclude-tag=pg`: 1293 collected, 0 decorator skips.
- All three SHAs, `--tag=pg`: 28 collected.

The executed premerge run on this SHA passed 1293, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The eight added tests are the `RequestIdMiddlewareTests` methods above. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `1d4ecd1`. 1293 is above the 1285 collected on `4dd5060`.

The local virtualenv had `requirements.txt` and the optional pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.inference.txt`, `requirements.vision.txt` (`pillow`), and `pypdfium2==5.14.0`. Torch and torchvision are the CPU wheels `2.13.0+cpu` and `0.28.0+cpu`.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `4dd5060` and on `1d4ecd1` without those variables.

## Gate G-skip

The premerge backend command on this Linux host is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All eleven files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` on this main pins `pypdf==6.21.4`. No ignore was added. This ticket does not edit a requirements file.

## Gate G-secrets

`gitleaks` 8.30.1. No new allowlist and no edit to `.gitleaks.toml`. The repository config from ANVIL-043 stays as it is. Raw reports are not committed. `gitleaks dir` writes its report outside the repo; the record keeps the summary.

- `gitleaks dir . --redact` at `5e47b845e2a90c527f4808eda8de52de87d9c9a6` exited 0. `no leaks found`.
- The same command after these evidence files were written, and after the gitignored `web/storybook-static/` build was removed, exited 0. While that build output was on disk it added one `generic-api-key` hit in a generated bundle. That directory is gitignored and is not in the commit.
- `gitleaks detect --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. Findings on `5e47b845e2a90c527f4808eda8de52de87d9c9a6`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0. The 370 hits on `75e2565` are the decoded-digest matches owned by ANVIL-043 and covered by the existing allowlist. The 36 remaining findings are on older commits in files this ticket does not change.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`. That is a small correctness check already recorded on main. This change adds no RAG number.

## Result

A request with no `X-Request-Id` gets a non-empty UUID v7. A well-formed inbound id is reused. Empty and CR/LF headers are not reflected. The id is on the response header, including the error response `ExceptionMiddleware` already returns. `make premerge` exited 0 with no runtime skip, xfail, or timeout. Counts are above `4dd5060`. `pip-audit` exited 0. `gitleaks dir` exited 0. No allowlist was added.
