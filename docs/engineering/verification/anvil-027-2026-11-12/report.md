# ANVIL-027: customer install page, followed command by command on new engines, 12 November 2026

Label: `local`. Ticket: ANVIL-027 (Aftur TASK-104). Times are UTC.

## What changed

- `docs/self-host-install.md`, a new page for an outside operator. Its sections: What you get; How to read this page; Requirements; Get a release; Install; Check that it runs; Everyday commands; Add the example model; Back up; Upgrade (Build the newer release, Rehearse the upgrade on a copy, Upgrade your instance); Roll back; Uninstall; Restore on another machine; Limits; Other deployment files in this repository.
- `docs/engineering/verification/anvil-027-2026-11-12/verbatim_run.py`, the script that runs the page's command blocks in order on new `docker:dind` engines.
- This report and the run record, `verbatim-run.json`.

The page is sourced from [deploy/selfhost/README.md](../../../../deploy/selfhost/README.md), the controller `deploy/selfhost/modelanvil.py`, `deploy/selfhost/VERSION`, `scripts/build_selfhost_release.py`, `scripts/install_selfhost.py`, `scripts/drill_selfhost.py`, [self-host-drills.md](../../self-host-drills.md), and the ANVIL-024, ANVIL-025, ANVIL-026 and ANVIL-029 reports. It documents only controller subcommands that exist (`install`, `initialize`, `start`, `stop`, `status`, `diagnostics`, `backup`, `example`, `import-reference`, `upgrade`, `restore`, `uninstall`) and states that there is no rollback subcommand. It says that `deploy/helm` is unsupported and links [deploy/helm/README.md](../../../../deploy/helm/README.md). It says that `release.json` sets `production_qualified` to `false`, and that `deploy/production` is a separate Compose procedure that `scripts/install_selfhost.py` does not call. Hardware wording: the package has a CPU worker only; across ModelAnvil, CPU and MPS on one Apple silicon Mac are at the integrated-execution level; CUDA is in the code and not verified.

Not changed: `docs/engineering/self-host.md`, `README.md`, anything under `web/`, the requirements files, the gitleaks configuration, CI and `deploy/helm`. No tag, GitHub release or image was made.

## Which machine

The ANVIL-026 reset environment that Nir chose on 12 November 2026: a brand-new privileged `docker:dind@sha256:08a98015 fce594af 7c382883 bea080ea 206de744 02a95da9 dc52b642 8c8cd121` container with a new, empty `/var/lib/docker` volume, inside the Docker Desktop Linux VM of Nir's Apple M5 Pro Mac. The run used two such engines:

- `anvil027-first` (volume `anvil027-first-docker`) for every section up to and including Uninstall;
- `anvil027-second` (volume `anvil027-second-docker`), started fresh at that point, for Restore on another machine.

Each engine reported Docker 29.9.3 `linux/arm64`, `MemTotal` 8317202432 and Docker Compose v5.7.0, with 0 images, 0 volumes and 0 containers before the first step. Python 3.14.10 came from the page's Alpine example. The two engines share one VM, kernel and disk. They are not separate physical hosts.

## Record

[verbatim-run.json](verbatim-run.json) is the ANVIL-002 record (`docs/engineering/schemas/local-evidence.v1.json`), written by `scripts/local_evidence.py` from a clean `git status`:

- SHA `27407b7889d00b7c0f564ba93d7c24566860ed9e`: this branch with the page and the runner committed, on top of `main` `5e23997`. `git_status_porcelain` is empty.
- Recorded at 2026-11-12T23:51:38+02:00 on `Nirs-MacBook-Pro.local`, macOS 27.0.1 arm64.
- Command: `/usr/bin/python3 docs/engineering/verification/anvil-027-2026-11-12/verbatim_run.py /Users/nirtuttnauer/.cache/modelanvil-selfhost/releases`.
- Exit code 0. `stderr` is empty. `stdout` (62,515 characters) holds every block as the page writes it, the `sh -x` trace with `~` expanded, the full output, and the exit code and duration of each step.

It ran inside one hold of the host test lock, from 21:47:56 to 21:51:38:

```sh
cd <anvil-027 worktree> && $TESTLOCK $GATES_VENV/bin/python scripts/local_evidence.py \
  --output docs/engineering/verification/anvil-027-2026-11-12/verbatim-run.json -- \
  /usr/bin/python3 docs/engineering/verification/anvil-027-2026-11-12/verbatim_run.py /Users/nirtuttnauer/.cache/modelanvil-selfhost/releases
```

`$TESTLOCK` is the host test-lock wrapper. `$GATES_VENV` is the `anvil-gates` worktree's virtual environment, which has `jsonschema` for the record check.

## How the runner follows the page

The runner reads every top-level `sh` code fence of the page in order: 19 blocks. The one `json` fence, the example install result, is not a command. Each block is written into the engine unchanged and run as one `sh -e -x` script from `/root`, so a block stops at its first failing command, as it would for a person. Standard input is `/dev/null`, except for the install.

The page leaves four things to the operator. The runner did them as follows and printed each one as `operator:` with its command:

1. **Tools.** Requirements says to install missing tools and gives `apk add python3 curl git` as the Alpine example. The runner ran that line on each engine. It installed curl 8.23.0 and python3 3.14.10. git was already in the `docker:dind` image.
2. **Answers to the install prompts.** The installer asks for an email, a workspace name and a password. Three lines (`owner@first-machine.test`, a workspace name and a `secrets.token_urlsafe(24)` password) were generated inside the first engine into a mode-0600 file. They were fed to the install block on standard input, as typing, and the file was deleted after the install. Without a terminal, Python's `getpass` printed `GetPassWarning: Can not control echo on the terminal` and `Warning: Password input may be echoed.`. The password does not appear anywhere in the output (see [Secrets](#secrets)). On a terminal the prompt hides the input.
3. **The two build blocks** (page lines 71 and 175) were not run, because there is no published release, as the ticket instructs. In their place the runner copied the existing release directories to the `--output` path each block names: `~/modelanvil-releases/0.1.0` (built at `fe9a94c` by ANVIL-024) and `~/modelanvil-releases/0.1.1` (built at `bf7359e` by ANVIL-025), from `~/.cache/modelanvil-selfhost/releases` on the host, mounted read-only. So the `python3.12 -m venv`, `pip install` and `git pull --ff-only` lines in those blocks did not run either. The builds themselves are recorded in the ANVIL-024 and ANVIL-025 reports.
4. **The copy to the second machine** (Restore on another machine, page step 2, which names the two directories and asks for a tool that keeps file modes). The runner piped `tar -C /root -cf - modelanvil-backups/before-upgrade modelanvil-releases/0.1.0` from the first engine into `tar -C /root -xpf -` on the second. Both tars exited 0. The listing on the second engine shows the backup files at mode 0600.

For page step 1 of that section ("check it with the same commands"), the Requirements block ran again, verbatim, on the second engine.

## Steps and results

From the record's summary. "Verbatim" means the page's block, unchanged.

| Step | Start | Engine | Page section (line) | How | Exit | Seconds | Result |
|---:|---|---|---|---|---:|---:|---|
| 1 | 21:47:58 | first | Requirements, tools | operator: `apk add python3 curl git` | 0 | 1.7 | curl, python3 3.14.10 |
| 2 | 21:48:00 | first | Requirements (50) | verbatim | 0 | 0.1 | `linux/arm64`, Compose v5.7.0, 8317202432, Python 3.14.10 |
| 3 | 21:48:00 | first | Get a release (65) | verbatim | 0 | 5.8 | `git clone` of `origin/main` `9e3ed89` |
| 4 | 21:48:06 | first | Get a release (71), build | operator: copy release 0.1.0 | 0 | 0.2 | |
| 5 | 21:48:06 | first | Install (87) | verbatim, prompts answered | 0 | 19.3 | `ready` true, version `0.1.0`, `production_qualified` false |
| 6 | 21:48:25 | first | Check that it runs (118) | verbatim | 0 | 0.1 | `{"status": "ok"}`, `{"status": "ready"}` |
| 7 | 21:48:25 | first | Everyday commands (131) | verbatim | 0 | 20.2 | status, stop, start, diagnostics, each exit 0 |
| 8 | 21:48:46 | first | Add the example model (144) | verbatim | 0 | 1.1 | model imported, 4-step `full_sft` launch returned |
| 9 | 21:48:47 | first | Back up (156) | verbatim | 0 | 17.8 | `verified_checksums` 4 |
| 10 | 21:49:05 | first | Build the newer release (175), build | operator: copy release 0.1.1 | 0 | 0.2 | |
| 11 | 21:49:05 | first | Rehearse the upgrade on a copy (188) | verbatim | 0 | 11.2 | rehearsal copy ready on 18443, version 0.1.0 |
| 12 | 21:49:16 | first | Rehearse the upgrade on a copy (196) | verbatim | 0 | 53.8 | drill `passed` true (below) |
| 13 | 21:50:10 | first | Rehearse the upgrade on a copy (222) | verbatim | 0 | 21.9 | both copies uninstalled |
| 14 | 21:50:32 | first | Rehearse the upgrade on a copy (229) | verbatim | 0 | 0.1 | 8 rehearsal volumes and 4 directories removed; record kept |
| 15 | 21:50:32 | first | Upgrade your instance (241) | verbatim | 0 | 19.4 | version `0.1.1`, ready, 0.1.0 kept at `release-history/0.1.0-adb15ee3` |
| 16 | 21:50:51 | first | Upgrade your instance (250) | verbatim | 0 | 0.2 | status version 0.1.1, `{"status": "ready"}` |
| 17 | 21:50:52 | first | Roll back (261) | verbatim | 0 | 10.8 | upgraded instance stopped |
| 18 | 21:51:02 | first | Roll back (267) | verbatim | 0 | 10.9 | restore of the upgrade backup with 0.1.0: version `0.1.0`, ready on 8443; `{"status": "ready"}` |
| 19 | 21:51:13 | first | Uninstall (281) | verbatim | 0 | 0.4 | containers removed, volumes kept |
| 20 | 21:51:15 | second | Restore on another machine, step 1, tools | operator: `apk add python3 curl git` | 0 | 1.7 | |
| 21 | 21:51:17 | second | Restore on another machine, step 1 (Requirements block, line 50) | verbatim | 0 | 0.1 | same values as step 2 |
| – | 21:51:17 | first to second | Restore on another machine, step 2 | operator: tar copy | 0 | | backup and release 0.1.0 copied |
| 22 | 21:51:20 | second | Restore on another machine (297) | verbatim | 0 | 16.8 | `"release": "0.1.0"`; restore ready, version `0.1.0`; `{"status": "ok"}` |

Every page block ran except the two build blocks: 17 of the 19 blocks, with the Requirements block once on each engine. Every step exited 0.

The drill in step 12 ran on the copy restored from `~/modelanvil-backups/before-upgrade`. Its baseline had 107 tables, 643 rows, 3 committed artifacts, 3 artifact files and 1 model, with PostgreSQL `16.15 (Debian 16.15-1.pgdg12+2)` and pgvector `0.8.7`. Its steps: `backup` exit 0 in 17.7 s, `upgrade` to 0.1.1 exit 0 in 20.0 s, and the rollback `restore` exit 0 in 11.1 s. `after_backup`, `after_upgrade` and `after_rollback` all compared equal to the baseline. The rollback backup was 8.5 s old when the restore started. The drill's report sets `production_qualified` to false.

## Where the page needed something it does not say

Nothing. No step needed a command, a file or a setting that the page does not give, or does not leave to the operator in words. The four operator actions above are the ones the page assigns to the operator: tools, the owner's answers, a release (built, here replaced by a copy as the ticket instructs) and the copy to the second machine.

A trial run of the same runner on the uncommitted page, 21:43:05 to 21:46:52 under the same lock, passed every step on its first attempt. It is not recorded, because the worktree was not clean. No page fix was forced. Between the trial and the recorded run:

- the disk bullet under Requirements gained the figures the trial measured (below). The recorded run measured the same values;
- two runner-only fixes: the closing summary counted the Requirements block twice, and `docker images` with no format printed an empty table on this Docker version. A formatted `docker images` also printed nothing in the recorded run, so the image sizes below come from `docker system df`.

Cosmetic: `curl` prints the JSON with no trailing newline, so in the log the next trace line starts on the same line.

Not run, because the page gives them as conditional or as examples in words, not as walk-through steps: `initialize` (resume after a failed setup), `--credentials-stdin`, `--host` and `--bind`, `start --open`, `import-reference`, the Debian `apt-get` line, `rsync -a` or `scp -rp`, `drill_selfhost.py snapshot --expect`, browser sign-in and importing `ca.crt` into a browser.

## Disk

Read-only observations after the last block, from the record:

| What | Size |
|---|---:|
| `~/modelanvil-releases/0.1.0`, `~/modelanvil-releases/0.1.1` | 333.6 MiB, 333.7 MiB |
| `~/modelanvil` after one upgrade (current release and `release-history/`) | 667.4 MiB |
| `~/modelanvil-rollback`, and the restored `~/modelanvil` on the second engine | 333.7 MiB each |
| Each backup (example data only) | 588.0 KiB |
| Images on the first engine (0.1.0 and 0.1.1, 5 images) | 1.501 GB, 25.28 MB reclaimable |
| Images on the second engine (0.1.0 only, 3 images) | 1.476 GB |
| Volumes on the first engine (upgraded and rollback instances, 8 volumes) | 134.6 MB |
| Volumes on the second engine (one instance, 4 volumes) | 58.46 MB |

The page states these as "1.48 GB", "about 25 MB", "667 MiB", "about 60 MB" and "under 1 MiB". Its memory figures come from the ANVIL-029 report and the Compose `mem_limit` values. This run did not measure memory. During the rehearsal, three instances ran at once in the 7.75 GiB VM, and no step failed.

## Wording review

```sh
rg -n -i 'production-ready|qualified|SLA|secure' docs/self-host-install.md
```

Exit 0, 4 matches, all of them the field name `production_qualified`:

| Line | Match | Why it stays |
|---:|---|---|
| 13 | `` `release.json`, the manifest in every release, sets the field `production_qualified` to `false` `` | The ticket requires the page to state that the manifest sets this field to false. "qualified" is part of the field name, not a claim. |
| 101 | `"production_qualified": false` | A line of the install result that the controller prints. Field name, value false. |
| 140 | `` `offline: true` and `production_qualified: false` `` | What `status` and `diagnostics` report. Field name, value false. |
| 311 | `` `production_qualified` is `false` in `release.json` and in the install, `start`, `status` and `diagnostics` results `` | Limits, restating the same field. Field name, value false. |

No match for `production-ready`, `SLA` or `secure`, including inside longer words. The page states CPU, and MPS on one Apple silicon Mac, at the integrated-execution level, and CUDA as in the code and not verified.

On this report the same pattern matches only the quoted pattern, the field name `production_qualified`, and this section's own mentions of the pattern's words. `verbatim_run.py` has no match (exit 1).

## Secrets

- Before printing anything, the runner replaced any occurrence of three values: the owner password (read from the answers file inside the engine) and the instance's `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` (read from `~/modelanvil/.env` after the install). Every restore in the run came from that instance's backups, so it used the same two instance secrets. The runner held these values in memory only and never printed them. Occurrences found in the output: 0.
- The answers file was deleted after the install. Both engines, with every instance, backup and secret in them, were removed at the end.
- Stock gitleaks 8.28.0 results are under [Gitleaks](#gitleaks).

## Cleanup

`docker rm -f` and `docker volume rm` of `anvil027-first`, `anvil027-second` and their two volumes each exited 0. Afterwards `docker ps -a` and `docker volume ls` filtered by `anvil027-` listed 0 containers and 0 volumes. The trial run cleaned up the same way. The release cache under `~/.cache/modelanvil-selfhost/releases` was only read. No other container or volume on the host was touched.

## Gitleaks

Stock gitleaks 8.28.0 with the stock rules and no allowlist or baseline, before the report commit:

```sh
gitleaks dir <path> --config stock-8.28.0.toml --no-banner
```

| Path | Exit | Result |
|---|---:|---|
| `docs/self-host-install.md` | 0 | no leaks found (about 24.7 KB scanned) |
| `docs/engineering/verification/anvil-027-2026-11-12/verbatim_run.py` | 0 | no leaks found |
| `docs/engineering/verification/anvil-027-2026-11-12/verbatim-run.json` | 0 | no leaks found |
| `docs/engineering/verification/anvil-027-2026-11-12/report.md` | 0 | no leaks found |
| `docs/engineering/verification/anvil-027-2026-11-12/` (whole directory) | 0 | no leaks found (about 98.3 KB scanned) |

## What this does not show

- No separate physical machine. Both engines ran in one Docker Desktop VM on one Mac, and the backup reached the second engine through `docker exec ... tar`, not over a network. A second physical Linux arm64 host stays with ANVIL-028.
- The build steps did not run, because there is no published release. This run checks the page from a built release onward.
- `git clone` fetched `origin/main` at `9e3ed89`, not this branch. Between this branch's base `5e23997` and `9e3ed89`, `scripts/install_selfhost.py`, `scripts/drill_selfhost.py` and `deploy/selfhost/` are identical (`git diff --stat` prints nothing).
- The controllers and the drill ran on Linux with Python 3.14.10. The page's lower bound, Python 3.9, is not exercised here. ANVIL-025 ran the same controllers and the drill on Python 3.9.6.
- Browser sign-in, training the example, the LAN flags and trusting `ca.crt` in a browser were not exercised.
- No tag, GitHub release or published image was made.

## Gates

The shared gates (G-local, G-skip, G-audit, G-secrets, G-rag) are run separately by the orchestrator and are not part of this report.
