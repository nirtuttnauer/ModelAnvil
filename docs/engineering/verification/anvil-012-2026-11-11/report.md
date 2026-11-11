# ANVIL-012 local evidence, 11 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. Test, check, audit, and gitleaks records were written by `.venv/bin/python scripts/local_evidence.py` or `scripts/premerge.py` from a clean `git status --porcelain`.

The measured tree is `9597028bfacf26f55d3c2ae3fed5d501983fe348`. This report is the following docs-only commit. The commands below ran at `9597028bfacf26f55d3c2ae3fed5d501983fe348`. Adding these files changes the PR head by one commit.

Base: `origin/main` `6febdec8fe71da4f759a7a72e419809682e1b4cd`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `golden-path.json` | 2026-11-11T19:01:13+00:00 | `scripts/golden_path.sh 9597028bfacf26f55d3c2ae3fed5d501983fe348 --steps 3` | 0 | 0 | 0 | 0 | 0 |
| `premerge.json` | 2026-11-11T18:58:45+00:00 | `make premerge` | 0 | 1285 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1285, 249, 28 | 0 |
| `make-check.json` | 2026-11-11T18:59:45+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-11T19:04:47+00:00 | `pip-audit -r` on every `requirements*.txt` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-11T19:03:12+00:00 | `gitleaks dir . --redact` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-11T19:00:13+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by this command, with Node 24.22.3 first on `PATH`:

```sh
.venv/bin/python scripts/premerge.py --output /tmp/anvil012-evidence/premerge.json
```

`scripts/premerge.py` records the command as `make premerge`. The `--output` path keeps the run from writing `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Backend result: `Ran 1285 tests in 358.173s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 113.478s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

`make check` printed `System check identified no issues (0 silenced).`

## Golden path

`scripts/golden_path.sh 9597028bfacf26f55d3c2ae3fed5d501983fe348 --steps 3` cloned that commit from `https://github.com/nirtuttnauer/ModelAnvil.git` into a temporary directory, ran only the README install block, trained 3 CPU LoRA steps on the pinned SmolLM2-135M base, and loaded the native export in two separate `python -I` processes: `scripts/verify_cpu_export.py` on the zip and `scripts/hf_candidate_infer.py` on the extracted directory. Exit 0. The log ends with `completed 3 SmolLM2-135M CPU LoRA steps`, `independent inference returned 8 tokens from verify_cpu_export.py and 8 tokens from hf_candidate_infer.py`, and `golden path completed 3 SmolLM2-135M CPU steps and independent inference at 9597028bfacf26f55d3c2ae3fed5d501983fe348`. The temporary directory was removed after success. No Hub token was set. One `bootstrap_dev` line in `golden-path.json` is replaced with a note: that command prints the local development key already stored in `modelanvil/identity/management/commands/bootstrap_dev.py`.

The base snapshot is checked against the pinned digests before training and again after training. `verify_cpu_export.py` checks the same pins inside the export. The unit test `test_deleted_snapshot_and_blocked_network_fail_before_training` deletes the cached snapshot files and raises on socket connect. The download fails and `run_steps` is not called.

## Counts against main `6febdec`

Discovery with this interpreter, without executing the suite:

- `6febdec8fe71da4f759a7a72e419809682e1b4cd`, `--exclude-tag=pg`: 1282 collected, 0 decorator skips.
- This SHA, `--exclude-tag=pg`: 1285 collected, 0 decorator skips.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run on this SHA passed 1285, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The three added tests are `GoldenPathInferenceTests.test_both_consumers_are_separate_processes_and_return_tokens`, `GoldenPathInferenceTests.test_missing_tokens_nonzero_exit_or_in_process_import_fail`, and `GoldenPathOfflineTests.test_deleted_snapshot_and_blocked_network_fail_before_training`. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `6febdec`.

The local virtualenv also had the optional pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.vision.txt` (`pillow`), `requirements.inference.txt` (`gguf`), and `pypdfium2` from `requirements.specialists.txt`. Those packages let the optional PDF, audio, image, GGUF, and embedding tests run. Discovery on `6febdec` with the same interpreter shows 0 decorator skips in the `--exclude-tag=pg` suite.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `6febdec` without those variables.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. Ten files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. The reported fix versions are 6.21.3 and 6.21.4. That file is outside this ticket's edit list, the pin matches `6febdec`, and no ignore was added. The audit gate does not pass on this host for that pre-existing pin.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`. The raw reports are not committed.

- `gitleaks dir --redact` on the working tree at `9597028bfacf26f55d3c2ae3fed5d501983fe348` exited 1 with 370 findings, all rule `generic-api-key`. Normalized to file and line, the set matches the same command on `6febdec`. None are under this directory or `golden_path`. Console: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 195 commits and exited 1 with 781 findings. Findings on `9597028bfacf26f55d3c2ae3fed5d501983fe348`: 0. Findings whose fingerprint is in `reviews/ANVIL-017-gitleaks-history.md`: 411. The other 370 are all on commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`, the same commit ANVIL-011 recorded. Console: `gitleaks-detect.json`.

`gitleaks dir` is not 0. It matches main, and this ticket adds no finding and no allowlist.

After these evidence files were written, `gitleaks dir --redact` on `docs/engineering/verification/anvil-012-2026-11-11` exited 0.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

Separate-process inference on the exported candidate returned 8 tokens from each consumer. Exit 0. The deleted-snapshot, blocked-network test fails before training. The golden-path record covers clone, install, train, and inference at `9597028bfacf26f55d3c2ae3fed5d501983fe348`. `make premerge` exited 0 with no runtime skip, xfail, or timeout. `pip-audit` exits 1 on the unchanged `requirements.documents.txt` pin. `gitleaks dir` exits 1 with the same 370 findings as `6febdec`.
