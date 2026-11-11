# ANVIL-023 local evidence, 11 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. `gitleaks` 8.30.1. `pip-audit` 2.10.1. Records use `docs/engineering/schemas/local-evidence.v1.json`.

The measured tree is `f2ceca69c4a347513dabbecef7cbd6d5a092e859`. `git status --porcelain` was empty at the start of each recorded command. This report is the following documentation commit. The commands below ran at `f2ceca69c4a347513dabbecef7cbd6d5a092e859`.

Base: `origin/main` `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-11T21:56:35+00:00 | `make premerge` | 0 | 1285 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1285, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-11T21:49:27+00:00 | `bash /tmp/anvil023/pip-audit.sh` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-11T21:48:22+00:00 | `gitleaks dir . --redact` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-11T21:48:25+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by this command, with Node v24.22.3 at the front of `PATH`:

```sh
.venv/bin/python scripts/premerge.py --output /tmp/anvil023/premerge.json
```

`scripts/premerge.py` records the command as `make premerge`. The `--output` path keeps the run from writing `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Backend result: `Ran 1285 tests in 328.735s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, `duration_ms 2331.469642`, after `npm --prefix web ci`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 117.288s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The displayed pg command includes `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. `DATABASE_PASSWORD` is not in the record. `docker compose ... down -v --remove-orphans` ran at the end. Exit 0.

`pip-audit.json` was produced by:

```sh
.venv/bin/python scripts/local_evidence.py --output /tmp/anvil023/pip-audit.json -- bash /tmp/anvil023/pip-audit.sh
```

`/tmp/anvil023/pip-audit.sh` runs `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` in sorted order, prints `EXIT` for each file, and exits 1 if any file exits non-zero. No `--ignore-vuln`.

The gitleaks records were produced by `scripts/local_evidence.py` with:

```sh
gitleaks dir . --redact --report-path /tmp/anvil023/gitleaks-dir-report.json --report-format json
gitleaks detect --redact --log-opts=--all --report-path /tmp/anvil023/gitleaks-detect-report.json --report-format json
```

The raw reports stayed in `/tmp` and are not committed. `Secret` in those reports is `REDACTED`.

## Counts against main `4dd5060`

Discovery with this interpreter, without executing the suite, on `f2ceca69c4a347513dabbecef7cbd6d5a092e859` and on a detached worktree of `4dd5060e632bae598003bf3a51a474709fe8c7ac`:

- `--exclude-tag=pg`: 1285 collected, 0 decorator skips, on both SHAs.
- `--tag=pg`: 28 collected on both SHAs. Three of those tests carry `skipUnless` for a PostgreSQL connection, so a SQLite discovery lists them as decorator skips. The same three IDs appear on both SHAs:

  - `modelanvil.api.test_team_access.ConcurrentInvitationTests.test_simultaneous_issue_allows_only_one_pending_invitation`
  - `modelanvil.jobs.test_device_claims.DeviceClaimConcurrencyTests.test_two_workers_tenants_claim_one_device_once`
  - `modelanvil.rag.test_research.ActualPostgreSQLResearch.test_actual_keyword_retrieval_model_answer_compaction_and_revocation`

The executed premerge run on this SHA passed 1285, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. `git diff --stat 4dd5060e632bae598003bf3a51a474709fe8c7ac f2ceca69c4a347513dabbecef7cbd6d5a092e859` is `deploy/helm/README.md` and `docs/engineering/self-host-package.md`. `web/` is unchanged, and this ticket adds no test. ANVIL-012 recorded the same executed counts, 1285, 249, and 28, on the commit merged as `4dd5060`.

The local virtualenv also had the pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.vision.txt`, `requirements.inference.txt`, and `pypdfium2==5.14.0`. Those packages let the optional PDF, audio, image, GGUF, and embedding tests run.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. ANVIL-012 recorded the same two IDs on the commit merged as `4dd5060`.

## Gate G-local

Label: `local`. Code SHA `f2ceca69c4a347513dabbecef7cbd6d5a092e859`. Passed counts are 1285 SQLite, 249 frontend, and 28 PostgreSQL. Those counts equal the discovery counts on `4dd5060` for the SQLite and PostgreSQL suites, and equal the executed frontend count ANVIL-012 recorded for the commit merged as `4dd5060`.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28, including the three tests whose PostgreSQL decorator does not skip once `DATABASE_ENGINE=postgresql`. Skipped, xfailed, and timeout are 0 in each executed run. The two fixture IDs above were not collected. They are the same two absent on `4dd5060` without those variables.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. Ten files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. The reported fix versions are 6.21.3 and 6.21.4. That file is outside this ticket's edit list, the pin matches `4dd5060`, and no ignore was added. The audit gate does not pass on this host for that pre-existing pin. ANVIL-042 owns the pin.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`. The raw reports are not committed.

- `gitleaks dir --redact` on the working tree at `f2ceca69c4a347513dabbecef7cbd6d5a092e859` exited 1 with 370 findings, all rule `generic-api-key`. None are under `docs/engineering/self-host-package.md` or `deploy/helm/README.md`. Console: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 198 commits and exited 1 with 781 findings, all rule `generic-api-key`. Findings on `f2ceca69c4a347513dabbecef7cbd6d5a092e859`: 0. Findings whose fingerprint is in `reviews/ANVIL-017-gitleaks-history.md`: 411. The triage file lists 391 fingerprints. The other 370 findings are all on commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. Console: `gitleaks-detect.json`.

`gitleaks dir` is not 0. It matches the 370 findings ANVIL-012 recorded on main, and this ticket adds no finding and no allowlist. ANVIL-043 owns that set.

After these evidence files were written, `gitleaks dir --redact` on `docs/engineering/verification/anvil-023-2026-11-11` exited 0 (`no leaks found`). The premerge Storybook build left a gitignored `web/storybook-static/` tree. One `generic-api-key` hit was in that generated file. That directory was removed. A following `gitleaks dir --redact` of the worktree exited 1 with 370 findings, all `generic-api-key`, and none under this directory, `docs/engineering/self-host-package.md`, or `deploy/helm/README.md`.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

This ticket writes the packaged-install scope and marks `deploy/helm` unsupported. It does not add a version file, an install script, a drill, a customer page, or a git tag. `make premerge` exited 0 with no runtime skip, xfail, or timeout. Counts equal the counts on `4dd5060`. `pip-audit` exits 1 on the unchanged `requirements.documents.txt` pin. `gitleaks dir` exits 1 with the same 370 findings as main.
