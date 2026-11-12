# ANVIL-008 license and ownership inventory

Label: `local`. This is a $0 inventory for Board Q47. It is not legal advice. It does not decide the license of a future add-on, and it does not promise that any present or future code stays MIT.

Base SHA: `6febdec8fe71da4f759a7a72e419809682e1b4cd` (`origin/main` on 2026-11-11). Host: `cursor`, Linux 6.12.113+ x86_64, Python 3.12.3. The public tree at that SHA is the tree that was installed. This folder is the only addition.

The closed add-on is not in this repository. The inventory covers every `requirements*.txt` group, including `requirements.selfhost.lock.txt`, and the production tree of `web/package-lock.json`.

The sections from here to Gate G-rag are the 11 November results as recorded. [12 November 2026](#12-november-2026-darwin-arm64-unknown-rows-and-verdicts) at the end adds the Darwin arm64 run, resolves two of the three unknown rows, and gives pass or fail for each Board condition.

## How the table was built

Python. For each requirements file, a new virtualenv, `pip install --upgrade pip` (pip 26.3), then `pip install -r <file>` with no extra index URL. `pip-licenses` 5.5.5 then ran twice:

- `--from=mixed --format=json --with-urls --order=name`
- `--from=all --format=json --with-urls --order=name`

Every install and both license commands exited 0. Raw JSON is under `pip-licenses/`. The host is Linux x86_64, so environment markers for Darwin arm64 did not install. Those direct requirements are still rows in the table, with SPDX taken from PyPI metadata for the pinned version.

The SPDX column uses `License-Expression` when pip-licenses has one. Otherwise it uses an unambiguous metadata or classifier token (`MIT`, `Apache-2.0`, `BSD-3-Clause`, `MPL-2.0`, `ISC`, `LicenseRef-NVIDIA-Proprietary`). Where the expression was missing and the installed wheel's license file is the 3-clause BSD text, the column is `BSD-3-Clause` and the source says so. `numpy` 2.3.3 and `scipy` 1.18.1 are `BSD-3-Clause` from that license text. Their wheels also carry other permissive notices (for numpy: Zlib, NCSA, and BSD-3-Clause components).

Three installed distributions have no SPDX expression and no license file that states one. They stay `UNKNOWN`.

Web. `web/package.json` and `web/package-lock.json` were copied to a temp directory. The sha256 of both copies matched the repo files. `npm ci --ignore-scripts` and `npx license-checker --production --json` ran there. `license-checker` 25.0.1 exited 0. Nothing under `web/` changed. Maintainer email fields were removed from the saved JSON. Two other addresses that appeared inside saved tool text were replaced with `[redacted]`.

The full table is [spdx-table.md](spdx-table.md) and [spdx-table.csv](spdx-table.csv). 701 rows. Counts by group:

| Group | Rows |
| --- | ---: |
| `requirements.txt` | 40 |
| `requirements.production.txt` | 41 |
| `requirements.documents.txt` | 1 |
| `requirements.gpu.txt` | 59 |
| `requirements.inference.txt` | 67 |
| `requirements.embeddings.txt` | 63 |
| `requirements.audio.txt` | 61 |
| `requirements.vision.txt` | 61 |
| `requirements.tools.txt` | 56 |
| `requirements.selfhost.lock.txt` | 41 |
| `requirements.specialists.txt` | 82 |
| `web/package-lock.json` | 129 |

`web/package.json` has `"private": true` and no `license` field, so license-checker reports the root package `modelanvil-web@0.1.0` as `UNLICENSED`. That row is the application itself, not a third-party dependency, and it is not in the table. The repository `LICENSE` file is MIT.

Darwin-only direct requirements, not installed on this host, SPDX `MIT` from PyPI metadata:

| Group | Name | Version |
| --- | --- | --- |
| `requirements.inference.txt` | mlx-lm | 0.29.1 |
| `requirements.inference.txt` | mlx | 0.32.3 |
| `requirements.inference.txt` | mlx-metal | 0.32.3 |
| `requirements.specialists.txt` | mlx | 0.32.3 |
| `requirements.specialists.txt` | mlx-audio | 0.5.8 |
| `requirements.specialists.txt` | mlx-metal | 0.32.3 |
| `requirements.specialists.txt` | mlx-vlm | 0.7.6 |

On this host, `pip install -r` for any file that pulls `torch==2.13.0` resolves the PyPI CUDA build. That install includes 14 `LicenseRef-NVIDIA-Proprietary` packages (`nvidia-cublas`, `nvidia-cuda-cupti`, `nvidia-cuda-nvrtc`, `nvidia-cuda-runtime`, `nvidia-cudnn-cu13`, `nvidia-cufft`, `nvidia-cufile`, `nvidia-curand`, `nvidia-cusolver`, `nvidia-cusparse`, `nvidia-cusparselt-cu13`, `nvidia-nccl-cu13`, `nvidia-nvjitlink`, `nvidia-nvshmem-cu13`). Those are proprietary, not GPL-family. CI installs `torch` from the CPU index before the requirements file, which does not pull these packages. This inventory did not set an index URL.

`nvidia-nvtx` 13.0.85 is `Apache-2.0`. Its classifier says `Other/Proprietary License`. The license file in the wheel is the Apache License 2.0.

## GPL, AGPL, LGPL, and unknown

No dependency's SPDX expression is GPL or AGPL.

LGPL:

| SPDX | Name | Version | Where |
| --- | --- | --- | --- |
| `LGPL-3.0-only` | psycopg | 3.2.12 | direct in `requirements.txt`, `requirements.production.txt` (via `-r requirements.txt`), and `requirements.selfhost.lock.txt` |
| `LGPL-3.0-only` | psycopg-binary | 3.2.12 | transitive in `requirements.txt` and `requirements.production.txt` (the `psycopg[binary]` extra); direct in `requirements.selfhost.lock.txt` |

MPL-2.0, which is not LGPL and is not GPL:

| SPDX | Name | Version | Where |
| --- | --- | --- | --- |
| `MPL-2.0` | certifi | 2026.10.23 | transitive in `requirements.txt`, `requirements.production.txt`, and every torch group; direct in `requirements.selfhost.lock.txt` |
| `MPL-2.0` | certifi | 2026.10.19 | direct in `requirements.specialists.txt` |
| `MPL-2.0 AND MIT` | tqdm | 4.70.1 | transitive in `requirements.txt`, `requirements.production.txt`, and every torch group; direct in `requirements.selfhost.lock.txt` and `requirements.specialists.txt` |
| `MPL-2.0` | lightningcss | 1.33.0 | transitive production dependency of `web/package-lock.json` |
| `MPL-2.0` | lightningcss-linux-x64-gnu | 1.33.0 | transitive production dependency of `web/package-lock.json` |

Unknown:

| Name | Version | Where | Why it is unknown |
| --- | --- | --- | --- |
| cuda-toolkit | 13.0.3.0 | transitive in `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.embeddings.txt`, `requirements.audio.txt`, `requirements.vision.txt`, `requirements.tools.txt`, `requirements.specialists.txt` | NVIDIA meta-package. The wheel metadata has no license field and no license file. The packages it pulls on this host are the `LicenseRef-NVIDIA-Proprietary` packages above. |
| sentencepiece | 0.2.1 | direct in `requirements.audio.txt` | The installed wheel has no license metadata and no license file. `sentencepiece` 0.2.2 in `requirements.specialists.txt` does declare `Apache-2.0`. That declaration is not used for 0.2.1. |
| pypdfium2 | 5.14.0 | direct in `requirements.specialists.txt` | Metadata says `BSD-3-Clause, Apache-2.0, dependency licenses`, which is not an SPDX expression. The wheel contains Apache-2.0, BSD-3-Clause, and CC-BY-4.0 texts plus bundled component notices (FreeType, ICU Unicode, libpng, zlib, MIT components, and others). The ICU notice includes the Autoconf `install-sh` special exception to GPLv3. That snippet is a notice about one install script, not an SPDX GPL license on pypdfium2. No `License-Expression` for this package is GPL, AGPL, or LGPL. |

## Authors and committers

Counts only. Addresses are not in this folder. Detail: [identity-counts.txt](identity-counts.txt). Commands: `git log --format='%ae'` and `git log --format='%ce'` at `6febdec`. 286 commits.

| Class | Author commits | Author identities | Committer commits | Committer identities |
| --- | ---: | ---: | ---: | ---: |
| owner | 258 | 4 | 241 | 2 |
| agent | 28 | 1 | 28 | 1 |
| other | 0 | 0 | 17 | 1 |

Owner is the git name `Nir Tuttnauer` or `nirtuttnauer`. `LICENSE` names Copyright (c) 2026 Nir Tuttnauer. Agent is the git name `Cursor Agent`. The other committer identity is the git name `GitHub`, on 17 merge commits. The author of each of those commits is the owner. Two of the four owner author identities do not appear as committers; those commits were committed by the GitHub merge identity.

Unexplained third parties: 0.

## MIT promise search

```
rg -n -i 'always (be )?(free|mit)|will remain' README.md docs
```

Exit 1. No lines. Record: [mit-promise.txt](mit-promise.txt).

`README.md` line 239 says ModelAnvil is released under the MIT license, and that model weights, datasets, and third-party packages retain their own licenses. The search does not match that sentence. The sentence describes the license of this repository. It does not say that future features stay MIT.

## Verdicts for Nir

Recorded 11 November at `6febdec`. Superseded by the [12 November verdicts](#verdicts-for-nir-12-november).

| Board condition | Verdict |
| --- | --- |
| (1) Dependency licenses, no conflicting copyleft, and no GPL/AGPL in the closed part | open |
| (2) VCTK notice closed (ANVIL-004) | open |
| (3) Nir is the copyright holder | pass |
| (4) Nothing in the public repo promises that future features stay MIT | pass |

Condition (1) is open because the inventory found `LGPL-3.0-only` on `psycopg` and `psycopg-binary`, `MPL-2.0` on `certifi`, `tqdm`, and `lightningcss`, and three unknown SPDX rows (`cuda-toolkit`, `sentencepiece` 0.2.1, `pypdfium2`). It found no GPL or AGPL expression. Whether LGPL-3.0-only or MPL-2.0 conflicts with a closed add-on is a Board reading. If the Board treats either as conflicting, condition (1) fails and the question returns to the Board. This inventory does not make that call.

Condition (2) stays open until ANVIL-004 merges. `main` at `6febdec` has no ANVIL-004 commit. A search of this repository's pull requests and issues for ANVIL-004 returned none. Docs still describe CSTR VCTK 0.92 as a CC-BY-4.0 dataset-bank source.

Condition (3) passes the identity check: every author is the owner or the Cursor Agent, every committer is the owner, the Cursor Agent, or GitHub's merge identity, and unexplained third parties are 0. That is not a legal opinion about copyright in agent-authored commits.

Condition (4) passes the required search: no match.

## Gate G-local

Label: `local`. Record: [premerge.json](premerge.json). `scripts/premerge.py` is the command `make premerge` runs. `--output` points at this folder, so `docs/engineering/verification/anvil-009-2026-10-29/premerge.json` was not rewritten.

The recorded run started from an empty `git status --porcelain` at `5b1da33abcd7d8181f99ed9886b2daf3393725ad`. That commit's parent is `6febdec8fe71da4f759a7a72e419809682e1b4cd`. The diff is this evidence folder and contains no tests. Recorded at 2026-11-11T18:45:01+00:00. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Exit 0.

| Run | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | ---: | ---: | ---: | ---: |
| backend `--exclude-tag=pg` | 1282 | 28 | 1282 | 0 |
| frontend `npm --prefix web test` | 249 | 0 | 249 | 0 |
| pgvector `--tag=pg` | 28 | 0 | 28 | 0 |

Backend result line: `Ran 1282 tests in 324.856s` then `OK`. PostgreSQL result line: `Ran 28 tests in 114.800s` then `OK`. Frontend install, production build, and storybook build exited 0.

Counts against `main` `6febdec`: the suite is unchanged, because this ticket adds no tests. Measured counts are 1282 backend, 28 PostgreSQL, and 249 frontend.

An earlier attempt on the same SHA exited 1 with two errors, both `operator torchvision::nms does not exist`. The local virtualenv had CPU `torch` 2.13.0 and a PyPI `torchvision` 0.28.0 wheel that did not match it. Reinstalling `torchvision==0.28.0+cpu` from the CPU index fixed the import. That mismatch is not a product failure. The record above is the run after that reinstall.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge record has zero of each. The backend command excludes `pg` before the run. Those 28 IDs are `runs[0].excluded_ids` in `premerge.json`. The PostgreSQL command runs that tag: 28 passed. Every collected ID is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on the record. They are not runtime skips. They are the same two IDs recorded on earlier main runs.

## Gate G-audit

`pip-audit` 2.10.1, `--progress-spinner off -r <file>`, no `--ignore-vuln`, at `6febdec` with an empty `git status --porcelain`. Summary: [pip-audit/summary.txt](pip-audit/summary.txt).

Ten files exited 0 with `No known vulnerabilities found`: `requirements.txt`, `requirements.production.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.embeddings.txt`, `requirements.audio.txt`, `requirements.vision.txt`, `requirements.tools.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has seven findings: CVE-2026-119208, CVE-2026-119206, CVE-2026-119209, and CVE-2026-119207 (fix 6.21.3); CVE-2026-119203, CVE-2026-119205, and CVE-2026-119204 (fix 6.21.4). No ignore was added. Clearing the finding means changing `requirements.documents.txt`, which this ticket does not change. This gate is unmet.

## Gate G-secrets

`gitleaks` 8.28.0, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

- `gitleaks dir . --redact` on the working tree that includes this evidence folder, before `premerge.json`, scanned 24.50 MB at `5b1da33` and exited 0 (`no leaks found`).
- The same command after `premerge.json` was written, and after the gitignored `web/storybook-static/` build was removed, scanned 32.62 MB and exited 0. While that build output was on disk it added one `generic-api-key` hit in a generated bundle. The directory is gitignored. It is not in the commit. The recorded scan is the one after it was removed.
- `gitleaks detect --source . --log-opts=--all --redact` at `5b1da33` scanned 195 commits and exited 1 with 411 findings, 391 unique fingerprints, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. None are missing from that list, and the list has no fingerprint this scan did not find. None are on `5b1da33`. The raw report is not committed.

## Gate G-rag

This inventory adds no retrieval measurement. `premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents. That is a small correctness check. The documented baseline next to it is MiniLM nDCG@5 `1.0` next to seeded random `0.0215` on 20 queries / 200 SciFact docs. This change does not claim a new RAG number.

## 12 November 2026: Darwin arm64, unknown rows, and verdicts

Label: `local`. Base SHA: `56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7` (`origin/main` on 2026-11-12). It contains ANVIL-008 (#82, `ad41479`) and ANVIL-004 (#81, `49574c0`). Host: `Nirs-MacBook-Pro.local`, Apple M5 Pro, macOS 27.0.1, arm64, CPython 3.12.15. This is an inventory, not legal advice. Commands and tool versions are in the 12 November block of [commands.txt](commands.txt).

### Verdicts for Nir, 12 November

| Board condition | Verdict | Reason |
| --- | --- | --- |
| (1) Dependency licenses, no conflicting copyleft, and no GPL/AGPL in the closed part | pass | No package in any group, on Linux x86_64 or Darwin arm64, has a GPL or AGPL license; the copyleft present (LGPL-3.0-only `psycopg`, MPL-2.0 `certifi`/`tqdm`/`lightningcss`, and the LGPL-2.1-or-later and GCC-runtime-exception libraries bundled in `numpy` and `scipy` wheels) is weak or excepted when the add-on uses the packages unmodified as separate installs. |
| (2) VCTK notice closed (ANVIL-004) | pass | ANVIL-004 merged as `49574c0` (#81); at `56b35cc` `rg -n '@'` on the VCTK readme notice exits 1, and the redact decision and its CC BY 4.0 clause are in `docs/open-dataset-bank.md`. |
| (3) Nir is the copyright holder | pass | At `56b35cc`, all 294 commits are authored by the owner (266) or the Cursor Agent (28); the 25 commits with the GitHub committer identity are owner-authored merges; 0 unexplained third parties. |
| (4) Nothing in the public repo promises that future features stay MIT | pass | The required search at `56b35cc` matches only the search command quoted inside this evidence folder. |

A failed condition returns the question to the Board. No condition failed in this inventory.

The pass for (1) rests on two readings that the Board can overrule. First, the add-on imports these packages unmodified as separate installs and copies none of their code. Second, LGPL-3.0-only, MPL-2.0 and the GCC Runtime Library Exception do not conflict with a closed component used that way. If the Board does not accept either reading, (1) is fail and the question returns to the Board. The one remaining unknown row, `cuda-toolkit`, does not change (1): it is a Linux-only meta-package with no files besides its metadata (see below). The 14 `LicenseRef-NVIDIA-Proprietary` packages it pulls on Linux are proprietary, not copyleft. Their terms matter only if the add-on redistributes them.

### What changed since 11 November

- Every group was installed and inventoried on Darwin arm64, so the 7 MLX rows are measured instead of typed in from PyPI. Their macOS transitive dependencies are now in the table.
- `sentencepiece` 0.2.1 is now `Apache-2.0` and `pypdfium2` 5.14.0 is now `Apache-2.0 OR BSD-3-Clause`. `cuda-toolkit` stays `UNKNOWN`.
- The table is generated by [`scripts/license_table.py`](../../../../scripts/license_table.py) instead of by hand.
- Two gaps in the 11 November table: it has no `setuptools` rows, and it does not list GPL-family notices for components bundled inside wheels. Both are covered below. The 11 November files were not rewritten.

### How the Darwin table was built

The method is the 11 November one: a new venv per root `requirements*.txt`, `pip install --upgrade pip` (pip 26.3), `pip install -r <file>` with no extra index URL, then `pip-licenses` 5.5.5 with `--from=mixed` and `--from=all`, both with `--format=json --with-urls --order=name`. The differences are these:

- `uv venv --seed --python 3.12` creates the venv, outside the repo. pip does the install, as before.
- `pip-licenses` runs from its own venv with `--python <venv>/bin/python`.
- `pip-licenses` drops `pip`, `setuptools`, `wheel`, `prettytable` and `wcwidth` unless `--with-system` is set. One more run per group adds `--with-system --packages setuptools wheel prettytable wcwidth`. Saved as `<group>.system.json`.
- `pip freeze` for each venv is saved as `<group>.freeze.txt`.
- The web copy ran `npx --yes license-checker@25.0.1 --production --json`. The lockfile sha256 matched both the repo and the 11 November copy.

Every install and license command exited 0. Raw output: [pip-licenses-darwin-arm64/](pip-licenses-darwin-arm64/) and [web-darwin-arm64/](web-darwin-arm64/). Before commit, 95 email fields were removed from the license-checker JSON. Its local temp path was replaced with `<tmp>/web`. One address inside the `numpy` and `scipy` license text was replaced with `[redacted]`, as in the 11 November files.

The Darwin table is in separate files, [spdx-table-darwin-arm64.md](spdx-table-darwin-arm64.md) and [spdx-table-darwin-arm64.csv](spdx-table-darwin-arm64.csv), not a platform column, so the 11 November table stays as recorded. The script applies the 11 November rules in order: `License-Expression`, then a reviewed license-file row, then an unambiguous metadata token, then an unambiguous classifier, else `UNKNOWN`. `--check-venvs` reopened every license-file row in the installed wheels: 44 ok, 0 failed. A second run wrote a byte-identical CSV. Run against the 11 November JSON and the `6febdec` requirement files, the script reproduces 692 of the 701 rows in the same order. The 9 others are the 7 typed MLX rows and the two unknown rows resolved here.

Rows by group:

| Group | 11 Nov, Linux x86_64 | 12 Nov, Darwin arm64 | Why the count differs |
| --- | ---: | ---: | --- |
| `requirements.txt` | 40 | 40 | |
| `requirements.production.txt` | 41 | 41 | |
| `requirements.documents.txt` | 1 | 1 | `pypdf` 6.21.2 became 6.21.4 in #87 (`BSD-3-Clause` both) |
| `requirements.gpu.txt` | 59 | 41 | 19 Linux-only CUDA rows absent, `setuptools` added |
| `requirements.inference.txt` | 67 | 51 | 19 CUDA rows absent; 3 MLX rows measured; `protobuf`, `sentencepiece` 0.2.3, `setuptools` added |
| `requirements.embeddings.txt` | 63 | 45 | 19 CUDA rows absent, `setuptools` added |
| `requirements.audio.txt` | 61 | 43 | 19 CUDA rows absent, `setuptools` added |
| `requirements.vision.txt` | 61 | 43 | 19 CUDA rows absent, `setuptools` added |
| `requirements.tools.txt` | 56 | 38 | 19 CUDA rows absent, `setuptools` added |
| `requirements.selfhost.lock.txt` | 41 | 41 | |
| `requirements.specialists.txt` | 82 | 64 | 19 CUDA rows absent; 4 MLX rows measured; `setuptools` added |
| `web/package-lock.json` | 129 | 130 | 4 linux-x64 builds replaced by 5 darwin-arm64 packages |
| Total | 701 | 578 | |

The 19 Linux-only rows in each of the 7 torch groups are the 14 `LicenseRef-NVIDIA-Proprietary` packages, `nvidia-nvtx`, `cuda-toolkit`, `cuda-bindings`, `cuda-pathfinder` and `triton`. Every other package resolved to the same version on both hosts.

### New macOS-only packages

| Group | Name | Version | Relation | SPDX | Source |
| --- | --- | --- | --- | --- | --- |
| `requirements.inference.txt` | mlx | 0.32.3 | direct | `MIT` | License-Metadata |
| `requirements.inference.txt` | mlx-lm | 0.29.1 | direct | `MIT` | License-Metadata |
| `requirements.inference.txt` | mlx-metal | 0.32.3 | direct | `MIT` | License-Metadata |
| `requirements.inference.txt` | protobuf | 7.36.2 | transitive, from `mlx-lm` | `BSD-3-Clause` | License-Metadata `3-Clause BSD License`; the wheel's LICENSE is the 3-clause text |
| `requirements.inference.txt` | sentencepiece | 0.2.3 | transitive, from `mlx-lm` | `Apache-2.0` | License-Expression |
| `requirements.specialists.txt` | mlx | 0.32.3 | direct | `MIT` | License-Metadata |
| `requirements.specialists.txt` | mlx-audio | 0.5.8 | direct | `MIT` | License-Expression |
| `requirements.specialists.txt` | mlx-metal | 0.32.3 | direct | `MIT` | License-Metadata |
| `requirements.specialists.txt` | mlx-vlm | 0.7.6 | direct | `MIT` | License-Metadata |
| `web/package-lock.json` | @esbuild/darwin-arm64 | 0.28.2 | transitive | `MIT` | license-checker |
| `web/package-lock.json` | @rolldown/binding-darwin-arm64 | 1.2.13 | transitive | `MIT` | license-checker |
| `web/package-lock.json` | @typescript/typescript-darwin-arm64 | 7.0.2 | transitive | `Apache-2.0` | license-checker |
| `web/package-lock.json` | fsevents | 2.3.3 | transitive | `MIT` | license-checker |
| `web/package-lock.json` | lightningcss-darwin-arm64 | 1.33.0 | transitive | `MPL-2.0` | license-checker |

The 7 MIT values typed in on 11 November match the installed metadata. `requirements.specialists.txt` pins every dependency of `mlx-audio` and `mlx-vlm`, so they add no unpinned packages. `mlx-lm` in `requirements.inference.txt` pulls `protobuf` and `sentencepiece` 0.2.3.

`setuptools` is not macOS-only. It is MIT (`License-Expression`): 84.2.1, transitive, in the 6 groups above, because `torch` 2.13.0 has `Requires-Dist: setuptools>=77.0.3` with no marker, and 84.1.0, direct, in `requirements.specialists.txt`. The 11 November Linux installs had it too, but pip-licenses filtered it out of the table.

### GPL, AGPL, LGPL, MPL, and unknown on Darwin arm64

No package's SPDX expression is GPL or AGPL. No row is unknown.

| SPDX | Name | Version | Groups |
| --- | --- | --- | --- |
| `LGPL-3.0-only` | psycopg | 3.2.12 | `requirements.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt` |
| `LGPL-3.0-only` | psycopg-binary | 3.2.12 | `requirements.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt` |
| `MPL-2.0` | certifi | 2026.10.23 | `requirements.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, and the 6 torch groups other than specialists |
| `MPL-2.0` | certifi | 2026.10.19 | `requirements.specialists.txt` |
| `MPL-2.0 AND MIT` | tqdm | 4.70.1 | every group except `requirements.documents.txt` |
| `MPL-2.0` | lightningcss | 1.33.0 | `web/package-lock.json` |
| `MPL-2.0` | lightningcss-darwin-arm64 | 1.33.0 | `web/package-lock.json` |

The only new entry against Linux is `lightningcss-darwin-arm64`, which takes the place of `lightningcss-linux-x64-gnu`. Darwin adds no GPL, AGPL, LGPL or unknown entry.

### Components bundled inside wheels

`--notices` lists every `License:` or `SPDX-License-Identifier` line naming GPL, LGPL or AGPL, and every file that opens with a GNU license title, in the license files that installed wheels ship. Output: [bundled-notices-darwin-arm64.tsv](bundled-notices-darwin-arm64.tsv), 39 rows. These are notices for code inside a wheel. They are not the package's SPDX expression. The same three wheels were read on manylinux x86_64 by HTTP range requests.

| Package | Groups | Notice | Shipped in the wheel |
| --- | --- | --- | --- |
| numpy 2.3.3 | `requirements.txt`, production, gpu, inference, embeddings, audio, vision, selfhost.lock | `LICENSE.txt` line 171: GCC runtime library, `GPL-3.0-or-later WITH GCC-exception-3.1`; line 955: libquadmath, `LGPL-2.1-or-later` | Darwin: no `numpy/.dylibs`, so those libraries are not in this wheel. manylinux: `libgfortran` and `libquadmath` are in the wheel. |
| numpy 2.5.4 | tools, specialists | `licenses/LICENSE.txt` lines 135 and 919, the same two sections | Darwin: no `numpy/.dylibs`. Not checked on manylinux. |
| scipy 1.18.1 | embeddings, audio, specialists | `LICENSE.txt` line 136: `GPL-3.0-or-later WITH GCC-exception-3.1`; line 921: `LGPL-2.1-or-later` | Darwin: `scipy/.dylibs` has `libgcc_s.1.1.dylib`, `libgfortran.5.dylib`, `libquadmath.0.dylib`. manylinux: `libgfortran` and `libquadmath`. |
| torch 2.13.0 | the 7 torch groups | `licenses/third_party/kineto/libkineto/third_party/dynolog/third_party/cpr/test/LICENSE` is the GPL-3.0 text, scoped to that test directory | Only the license files from that directory are in the wheel's `RECORD`. The manylinux wheel ships the same license file. |
| psycopg, psycopg-binary 3.2.12 | as above | the LGPL text that is their own license | |

The GCC Runtime Library Exception lets a program that is not GPL use these runtime libraries. libquadmath is a separate shared library. Both pass under the readings stated for condition (1).

This corrects the 11 November report. It says the numpy and scipy wheels carry Zlib, NCSA and BSD-3-Clause component notices. The same `LICENSE.txt` also has the GCC runtime and libquadmath sections. That text is already in the 11 November `License-Metadata` JSON, and the manylinux wheels ship both libraries. The 11 November run did not scan torch's license bundle.

`pypdfium2` 5.14.0 ships 15 `BUILD_LICENSES` files for its PDFium binary. The darwin_arm64 and linux_x64 sets have the same names, and only `pdfium.txt` formatting differs. They are abseil `Apache-2.0`; AGG 2.3, a permissive notice; fast_float `MIT`; FreeType `FTL`; ICU `Unicode-3.0`; lcms `MIT`; libjpeg-turbo IJG and `BSD-3-Clause`; OpenJPEG `BSD-2-Clause`; libpng `libpng-2.0`; llvm-libc `Apache-2.0 WITH LLVM-exception`; pdfium-binaries `MIT`; PDFium `BSD-3-Clause`; simdutf `MIT`; zlib `Zlib`. None is a GPL, AGPL or LGPL license. The ICU file mentions GPLv3 only for the Autoconf exception on `install-sh`, as noted on 11 November. The llvm-libc file mentions GPLv2 only in its compatibility exception.

### The three 11 November unknown rows

| Name | Version | Groups | SPDX now | Source |
| --- | --- | --- | --- | --- |
| sentencepiece | 0.2.1 | direct in `requirements.audio.txt` | `Apache-2.0` | The wheel's dist-info holds only METADATA, WHEEL, top_level.txt and RECORD, with no License field, on both platforms. The PyPI sdist `sentencepiece-0.2.1.tar.gz` (sha256 `8138cec27c2f2282f4a34d9a016e3374cd40e5c6e9cb335063db66a0a3b71fad`) has `sentencepiece-0.2.1/sentencepiece/LICENSE`, lines 2-3: `Apache License` / `Version 2.0, January 2004`. The sdist's bundled third-party sources are absl `Apache-2.0`, darts_clone `BSD-3-Clause`, esaxx `MIT` and protobuf-lite `BSD-3-Clause`. 0.2.2 and 0.2.3 declare `License-Expression: Apache-2.0`. |
| pypdfium2 | 5.14.0 | direct in `requirements.specialists.txt` | `Apache-2.0 OR BSD-3-Clause` | `pypdfium2/__init__.py` line 2: `SPDX-License-Identifier: Apache-2.0 OR BSD-3-Clause`. 43 of the wheel's 45 `.py` files carry it. The other two are `pypdfium2/_helpers/__init__.py` and `pypdfium2_raw/bindings.py`, which `REUSE.toml` lines 27-32 mark `Apache-2.0 OR BSD-3-Clause`. The README Licensing section, at wheel METADATA line 862, says pypdfium2 itself is under Apache-2.0 / BSD-3-Clause. The METADATA `License` field, line 8, reads `BSD-3-Clause, Apache-2.0, dependency licenses`; the dependency licenses are the PDFium `BUILD_LICENSES` above. The sdist's `LGPL-3.0-or-later` text covers one test file, `tests/resources/images.pdf` (`REUSE.toml` line 95), which is not in the wheel. |
| cuda-toolkit | 13.0.3.0 | transitive in the 7 torch groups, Linux only | stays `UNKNOWN` (SPDX `NOASSERTION`) | `cuda_toolkit-13.0.3.0-py2.py3-none-any.whl` (2512 bytes) contains only METADATA, WHEEL and RECORD. METADATA has no License, License-Expression or license classifier. PyPI's `license` and `license_expression` are null. METADATA line 107 calls it a meta-package that "contains no software and only installs other packages". No file from NVIDIA states a license for the meta-package itself. What it installs on Linux is the 14 `LicenseRef-NVIDIA-Proprietary` packages. It does not install on Darwin. |

### Conditions (2), (3) and (4) at 56b35cc

Condition (2). `49574c0` is an ancestor of `56b35cc`. `rg -n '@' catalog/qualified-datasets/notices/audio-vctk-full-readme.txt` exits 1. Line 12 of that file now reads `[contact address removed; see the upstream VCTK README]`. `docs/open-dataset-bank.md`, section "VCTK readme notice: author contact address" (lines 137-152), records the redact decision, the governing clause, Section 3(a)(1)(A), and the hash updates. One address-like string remains in the three VCTK notice files. It is the University of Edinburgh DataShare service's data-support role mailbox, inside the archived publisher page `audio-vctk-publisher-declaration.txt`. It is not an author's address. ANVIL-004 covered the author address in the readme.

Condition (3). [identity-counts-2026-11-12.txt](identity-counts-2026-11-12.txt). Counts only.

| Class | Author commits | Author identities | Committer commits | Committer identities |
| --- | ---: | ---: | ---: | ---: |
| owner | 266 | 4 | 241 | 2 |
| agent | 28 | 1 | 28 | 1 |
| other | 0 | 0 | 25 | 1 |

The 8 commits since `6febdec` are owner-authored pull request merges committed by GitHub. Unexplained third parties: 0. As on 11 November, this does not give a legal opinion on copyright in agent-authored commits.

Condition (4). [mit-promise-2026-11-12.txt](mit-promise-2026-11-12.txt). The required search exits 0 with two lines, `report.md:105` and `mit-promise.txt:4`. Both are the search command quoted inside this folder. Nothing in `README.md` or `docs` promises that present or future features stay MIT. After this commit the 11 November report line is at 107, and the search also matches line 4 of the new `mit-promise-2026-11-12.txt`, which quotes the command for the same reason.

### Gates for this update

This update adds `scripts/license_table.py` and evidence files. It changes no product code, test or requirement file. No test command, premerge or pip-audit ran: another session owns this host's test lane, and pip-audit is not installed here. The G-local, G-skip and G-audit records above are the 11 November ones, at `5b1da33` and `6febdec`. They were not repeated at the new SHA. `gitleaks` 8.30.1 `dir --redact` ran on a copy of every new and changed file, outside the repo so the repo `.gitleaks.toml` did not load, and found no leaks. That is a check on this change, not the full G-secrets gate. This update adds no RAG number.
