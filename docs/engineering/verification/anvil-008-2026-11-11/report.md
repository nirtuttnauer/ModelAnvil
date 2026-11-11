# ANVIL-008 license and ownership inventory

Label: `local`. This is a $0 inventory for Board Q47. It is not legal advice. It does not decide the license of a future add-on, and it does not promise that any present or future code stays MIT.

Base SHA: `6febdec8fe71da4f759a7a72e419809682e1b4cd` (`origin/main` on 2026-11-11). Host: `cursor`, Linux 6.12.113+ x86_64, Python 3.12.3. The public tree at that SHA is the tree that was installed. This folder is the only addition.

The closed add-on is not in this repository. The inventory covers every `requirements*.txt` group, including `requirements.selfhost.lock.txt`, and the production tree of `web/package-lock.json`.

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

Counts are compared with `main` `6febdec`. This ticket adds no tests. The local premerge record is `premerge.json` in this folder, written by `scripts/premerge.py` (the command `make premerge` runs) with `--output` set here so the existing ANVIL-009 record is left untouched. The record's SHA, date, machine, command, output, and exit code are in that file. Label: `local`.

The run is filled in after this inventory is committed, because premerge requires an empty `git status --porcelain`.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge record is the required run: backend `--exclude-tag=pg`, then the same IDs under `--tag=pg` on PostgreSQL. Excluded IDs are listed on the backend run. Fixture tests that are not collected on this host are `fixture_tests_not_collected` on that record. They are not runtime skips.

## Gate G-audit

`pip-audit` 2.10.1, `--progress-spinner off -r <file>`, no `--ignore-vuln`, at `6febdec` with an empty `git status --porcelain`. Summary: [pip-audit/summary.txt](pip-audit/summary.txt).

Ten files exited 0 with `No known vulnerabilities found`: `requirements.txt`, `requirements.production.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.embeddings.txt`, `requirements.audio.txt`, `requirements.vision.txt`, `requirements.tools.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has seven findings: CVE-2026-119208, CVE-2026-119206, CVE-2026-119209, and CVE-2026-119207 (fix 6.21.3); CVE-2026-119203, CVE-2026-119205, and CVE-2026-119204 (fix 6.21.4). No ignore was added. Clearing the finding means changing `requirements.documents.txt`, which this ticket does not change. This gate is unmet.

## Gate G-secrets

`gitleaks` 8.28.0, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

- `gitleaks dir . --redact` on the working tree, including this evidence folder before commit, scanned 24.47 MB and exited 0 (`no leaks found`) at 2026-11-11T18:26:25Z.
- `gitleaks detect --source . --log-opts=--all --redact` at `6febdec` scanned 194 commits and exited 1 with 411 findings, 391 unique fingerprints, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. None are missing from that list, and the list has no fingerprint this scan did not find. The raw report is not committed.

A repeat of both commands at the committed SHA is recorded with the premerge update.

## Gate G-rag

This inventory adds no retrieval measurement. If the PostgreSQL run prints the existing `TASK69_CONTROLS` line, that line is the small correctness check already on main: MiniLM nDCG@5 1.0 next to seeded random 0.0215 on 20 queries / 200 SciFact docs. It is not a new RAG number.
