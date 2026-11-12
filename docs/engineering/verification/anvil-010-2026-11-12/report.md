# ANVIL-010 local run of PR #70 head, 12 November 2026

Label: `local`. Commit under test: `4dbda069a066b951fa2a9a2017ec1f2edfd76a19`, the head of PR #70. This is a historical head: #70 merged on 2026-10-29 as `5dddd7ad63b893e9eae1e4d2c3c9e1c3f3dca4c0`. The review that uses these results is `reviews/ANVIL-010-pr70-pr16.md`.

Machine: Apple M5 Pro, macOS 27.0.1 (Darwin 27.0.0, arm64). Python 3.12.15 from the shared `anvil-gates` virtual environment. Node v24.22.3, placed first on `PATH`.

## How the commands ran

`4dbda06` predates `scripts/local_evidence.py`. The script was run from this branch (`claude/anvil-010-pr70-review`, based on `56b35cc`) with `--root` set to a detached worktree of `4dbda06`. The script refuses to start when `git status --porcelain` at the root is not empty. It was empty before every command below.

Names used below:

- `<py>`: the `anvil-gates` interpreter, `.claude/worktrees/anvil-gates/.venv/bin/python`.
- `<evidence>`: `<py> .claude/worktrees/anvil-010/scripts/local_evidence.py --root .claude/worktrees/pr70-head --output <record>`.
- Backend environment: `DATABASE_NAME` and `DATABASE_TEST_NAME` set to new SQLite files in a session temporary directory, `DJANGO_SETTINGS_MODULE=modelanvil.settings`, `PYTHONPATH=.claude/worktrees/pr70-head`, working directory `pr70-head`.

| # | Command | Start to end (+02:00) | Exit | Result | Record |
| --- | --- | --- | --- | --- | --- |
| 1 | `<evidence> -- npm --prefix web ci` | about 15:23:36 to 15:23:44 | 0 | 312 packages added | `frontend-npm-ci.json` |
| 2 | `<evidence> -- npm --prefix web test` | about 15:23:45 to 15:23:52 | 0 | `tests 235`, `pass 235`, `fail 0`, `skipped 0`, `todo 0`, `cancelled 0` | `frontend-npm-test.json` |
| 3 | `<evidence> -- <py> manage.py test --noinput --exclude-tag=pg -v 1` | 15:24:00 to 15:27:39 | test 0, script 3 | `Ran 1248 tests`, `OK (skipped=14)` | refused, superseded by run 5 |
| 4 | `<py> manage.py test --noinput --exclude-tag=pg -v 2` (diagnostic, no evidence script) | 15:28:34 to 15:32:07 | 0 | `Ran 1248 tests`, `OK (skipped=10)` | `backend-sqlite-skips.txt` lists the 10 IDs |
| 5 | `<evidence> -- <py> manage.py test --noinput --exclude-tag=pg -v 1` | 15:33:51 to 15:37:33 | test 0, script 3 | `Ran 1248 tests`, `OK (skipped=10)` | refused; full console in `backend-sqlite-console.txt` |

No backend run had a failure, an error, or a `DeviceBusy` message. Another session's backend suite started on this host at about 15:32 and overlapped run 5. The local device lease is host-wide, but run 5 shows no lease error and no failure.

Run 3 is not used for counts. Another session was installing packages into the shared `anvil-gates` environment while it ran (`pypdfium2` at 15:24:04, `huggingface_hub` and others at 15:27:48). The four extra skips are the four `modelanvil.runners.test_specialist_runtime.SpecialistRasterTests` tests. They are decorated `skipUnless(PIL and pypdfium2)`, and `pypdfium2` was not importable when that module loaded. Runs 4 and 5 ran after the environment stopped changing, and they agree.

## Why there is no backend-sqlite.json

`docs/engineering/schemas/local-evidence.v1.json` requires `skipped` to be 0 on every run. The script validates the record before writing it. For runs 3 and 5 it printed `local evidence record does not conform: - runs/0/skipped: 0 was expected` and exited 3 without writing a file. That refusal is the G-skip result for this head.

No change of invocation removes the 10 skips at `4dbda06` on this host:

- Three tests are skip-decorated for PostgreSQL and are not tagged `pg` at this commit, so `--exclude-tag=pg` does not remove them. ANVIL-002 retagged them later.
- Three PDF tests skip because the shared environment has `pypdf` 6.21.4, the current main pin, while `4dbda06` pins 6.21.2 (`requirements.documents.txt`, `PDF_VERSION` in `modelanvil/data/source_import.py:22`).
- The RabbitMQ loop test needs a live broker. Docker and port 5672 belong to another run.
- The Linux verifier RSS test does not run on macOS.
- The MLX native-adapter test and the GGUF native test need local fixtures that are not set.

## Counts against the claim, CI, and the baseline

| Suite | PR #70 claim | CI on `4dbda06` (2 workflow runs) | This run | Baseline `3200915` (ANVIL-002, Linux) |
| --- | --- | --- | --- | --- |
| Frontend `npm --prefix web test` | 235 passing | 235 pass, 0 skipped, both runs | 235 pass, 0 skipped | 234 pass |
| Backend default (`--exclude-tag=pg`) | no count claimed | `Ran 1248`, `OK (skipped=59)`, both runs | `Ran 1248`, `OK (skipped=10)` | 1237 collected, 6 decoration-time skips |
| PostgreSQL (`--tag=pg`) | no count claimed | `Ran 24`, `OK`, both runs | not run | 24 collected |

- The 235 frontend count holds. The one test over the baseline is `web/tests/evidence-label.test.mjs`, added by #70.
- 1248 backend tests is the baseline 1237 plus the 11 test methods in `modelanvil/core/test_trustworthy_roadmap.py`, added by #70.
- CI skipped 59 tests because its backend job installs only `requirements.txt`. This environment has the optional runtimes, so 10 skip.
- The PostgreSQL suite was not re-run for this historical head. Docker, ports 5432 and 5672, and `/tmp/modelanvil-premerge` belong to another run. The CI `pgvector` jobs on `4dbda06` ran 24 tests and passed.

## Gates for this historical head

- G-skip fails: 10 runtime skips here and 59 in CI.
- G-rag: #70 adds no retrieval number. The CI `pgvector` log at this head prints `TASK69_CONTROLS`. That is a small correctness check: held-out nDCG 1.0 next to seeded random 0.021535, on 200 documents. Its documented baseline is MiniLM nDCG@5 1.0 next to seeded random 0.0215 on 20 queries / 200 SciFact docs.
- G-audit and G-secrets were not run for this historical head. They run on the review branch.

## Notes on the records

- `frontend-npm-test.json` has `fixture_tests_not_collected` with the MLX and GGUF backend IDs. The script adds that field to any command that contains both `npm` and `test`. At `4dbda06`, those two IDs are collected and skip at runtime (see `backend-sqlite-skips.txt`). The field does not describe this commit.
- `npm ci` reported 5 npm audit findings (4 moderate, 1 critical) for the `web` lock file at this commit. They are in the `frontend-npm-ci.json` stdout and were not triaged here.
- The detached `pr70-head` worktree was removed after these runs.
