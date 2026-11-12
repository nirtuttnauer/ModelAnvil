# ANVIL-013 local evidence, 11 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. Each record was written by `/tmp/anvil013-recorder/bin/python scripts/local_evidence.py` or `.venv/bin/python scripts/premerge.py` from a clean `git status --porcelain`.

Base: `origin/main` `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

The job definition and the commands below ran at `75e6d05abdd4877dee25ba0a1e5669a9e9d2cab3`. This report is the following docs-only commit. Adding these files changes the PR head by one commit.

## Job

`.github/workflows/ci.yml` gains one job, `golden-path`. It runs on `ubuntu-latest` with `permissions: contents: read`. The actions use the same SHAs as the other jobs in that file:

- `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1)
- `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97` (v7.0.0)
- `actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9` (v6.1.0)

The cache path is `data/smollm2-135m`, the directory `scripts/golden_path.py --train` verifies. The key is `smollm2-135m-${{ hashFiles('modelanvil/runners/training/hf_runtime.py') }}`. `SOURCE` and `FILE_HASHES` for the pinned SmolLM2-135M snapshot live in that file. The pgvector job uses the same form: `embedding-${{ hashFiles('modelanvil/rag/embedding-pins.json') }}`.

The workflow has no `needs:` key. The new job has no `continue-on-error` key. `backend`, `frontend`, and `pgvector` are unchanged. This change does not edit the repository ruleset. Ruleset `protect-main` (id 26100884), read on 2026-11-11, requires a pull request and blocks deletion and non-fast-forward updates. It has no required status checks, so `golden-path` is not a required check.

GitHub Actions was not run. The "green on a PR" check stays open.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `job.json` | 2026-11-11T21:46:54+00:00 | `bash --noprofile --norc -eo pipefail /tmp/anvil013-job.sh` | 0 | 0 | 0 | 0 | 0 |
| `cache-key.json` | 2026-11-11T21:48:04+00:00 | `.venv/bin/python /tmp/anvil013-cache-key.py` | 0 | 0 | 0 | 0 | 0 |
| `premerge.json` | 2026-11-11T22:00:27+00:00 | `make premerge` | 0 | 1285 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1285, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-11T21:50:23+00:00 | `bash /tmp/anvil013-pip-audit.sh` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-11T21:52:14+00:00 | `gitleaks dir . --redact` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-11T21:52:16+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`/tmp/anvil013-job.sh` is the job's `run` block, byte for byte. GitHub Actions runs that block with `bash --noprofile --norc -eo pipefail`. The script is:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements.txt -r requirements.gpu.txt
make migrate
.venv/bin/python manage.py bootstrap_dev
make check
MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1 OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false .venv/bin/python scripts/golden_path.py --train --steps 3
```

Exit 0. `make check` printed `System check identified no issues (0 silenced).` The log ends with `completed 3 SmolLM2-135M CPU LoRA steps`, `independent inference returned 8 tokens from verify_cpu_export.py and 8 tokens from hf_candidate_infer.py`. No Hub token was set. One `bootstrap_dev` line in `job.json` is replaced with a note: that command prints the local development key already stored in `modelanvil/identity/management/commands/bootstrap_dev.py`.

`premerge.json` was produced by `.venv/bin/python scripts/premerge.py --output /tmp/anvil013-evidence/premerge.json` with Node v24.22.3 first on `PATH`. `scripts/premerge.py` records the command as `make premerge`. Backend: `Ran 1285 tests in 334.151s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 118.091s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

## Cache key

`actions/runner` `hashFiles` hashes each matched file with SHA-256, then writes those raw digests into one outer SHA-256. For one file the result is SHA-256 of that file's SHA-256 digest. At `75e6d05` the local computation was:

```text
hashFiles 2548e82f6f43fdb5e9791779db72fe0c3bbc90fc8d26aa5013c149af5f2dfbbb
cache_key smollm2-135m-2548e82f6f43fdb5e9791779db72fe0c3bbc90fc8d26aa5013c149af5f2dfbbb
```

A one-byte change to a temporary copy of `modelanvil/runners/training/hf_runtime.py` produced `97485a1105e817271a0eaf53a4550e96e09c4aefcd724a67abaead0b921fd19b`. The workspace snapshot had all 5 pinned files. An empty directory was missing all 5. A copy of `data/smollm2-135m` passed `acquire_pinned_base` while `_download_missing` was patched to raise. Exit 0. That is the cache-hit path: restore the directory, then verify, and do not download.

## Counts against main `4dd5060`

Discovery with this interpreter, without executing the suite, on `4dd5060e632bae598003bf3a51a474709fe8c7ac` and on `75e6d05abdd4877dee25ba0a1e5669a9e9d2cab3`:

- `--exclude-tag=pg`: 1285 collected, 0 decorator skips, on both SHAs.
- `--tag=pg`: 28 collected, on both SHAs.

The executed premerge run on `75e6d05` passed 1285, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. This ticket adds no test. `web/` is unchanged from `4dd5060`.

The local virtualenv had `requirements.txt`, `requirements.gpu.txt`, and the optional pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.inference.txt`, `pillow==13.0.0`, and `pypdfium2==5.14.0`. Discovery on both SHAs with that interpreter shows 0 decorator skips in the `--exclude-tag=pg` suite.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `4dd5060` without those variables.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Skipped, xfailed, and timeout are 0 in each executed run.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. Ten files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. The reported fix versions are 6.21.3 and 6.21.4. The pin matches `4dd5060`. No ignore was added. Those CVEs are owned by ANVIL-042.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`. The raw reports are not committed.

- `gitleaks dir --redact` on the working tree at `75e6d05abdd4877dee25ba0a1e5669a9e9d2cab3` exited 1 with 370 findings, all rule `generic-api-key`. Normalized to rule, file, and line, the set matches the same command on a clean worktree of `4dd5060`. None are under this directory or `.github/workflows/ci.yml`. Console: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 198 commits and exited 1 with 781 findings. Findings on `75e6d05abdd4877dee25ba0a1e5669a9e9d2cab3`: 0. Findings whose fingerprint is in `reviews/ANVIL-017-gitleaks-history.md`: 411. The other 370 are all on commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. Console: `gitleaks-detect.json`.

`gitleaks dir` is not 0. It matches main. This ticket adds no finding and no allowlist. The 370 findings on `75e2565` are owned by ANVIL-043.

## Result

The `golden-path` job is in `.github/workflows/ci.yml` with SHA-pinned actions, `contents: read`, no `continue-on-error`, and an `actions/cache` key from `hashFiles` of `modelanvil/runners/training/hf_runtime.py`. No other job waits on it, and the ruleset does not require it. The job script exited 0 at `75e6d05`: install, 3 CPU LoRA steps, and 8 tokens from each separate-process consumer. The cache key changes when that pins file changes, and a restored snapshot verifies without a download. `make premerge` exited 0 with 1285, 249, and 28 passed, the same counts as main `4dd5060`, and with no runtime skip, xfail, or timeout. `pip-audit` exits 1 on the unchanged `pypdf==6.21.2` pin. `gitleaks dir` exits 1 with the same 370 findings as `4dd5060`. GitHub Actions did not run, so a green Actions check is still open.

## Gate G-rag (addendum, 12 November 2026)

This report had no G-rag section, and `premerge.json` stdout carries RAG numbers without a label. This addendum labels them. It changes no record, number, or test.

- `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002` and SQL full text `0.0`, development nDCG real `0.982545` next to random `0.0`, on 200 SciFact documents and 412 chunks. That is a small correctness check, not a benchmark. The documented baseline next to it in `README.md` is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries.
- The `ndcg@3`, `recall@3`, `precision@3`, `hit@3`, and `mrr@3` lines are the embedding-candidate unit-test fixture: three hand-written passages (`refund`, `deliver`, `reset`) and their development queries. They show the evaluation code path runs. They are a small correctness check on a toy fixture and say nothing about retrieval quality.

ANVIL-013 adds no RAG number of its own.
