# ANVIL-026: clean install on a second machine, 12 November 2026

Label: `local`. Ticket: ANVIL-026 (Aftur TASK-103).

## Which machine

The ticket's second machine is "a free local VM or a reset environment; never rented". On 12 November 2026 Nir chose a brand-new Docker engine on his Mac for this ticket: a privileged `docker:dind` container, image pinned by digest, with a new and empty `/var/lib/docker` volume. That engine had never held ModelAnvil. Before the install it listed 0 images, 0 volumes and 0 containers. It runs inside the Docker Desktop Linux VM (linux/arm64) of the Apple M5 Pro that built the release. It is a reset environment, not a separate physical host. A distinct physical Linux arm64 host, as `docs/engineering/self-host-package.md` describes for the published tag, remains with ANVIL-028.

## Record

[second-machine.json](second-machine.json) is the ANVIL-002 record (schema `local-evidence.v1`) of one run of [second-machine.sh](second-machine.sh), written by `scripts/local_evidence.py` from a clean `git status`:

- SHA `cf429f68d214b8e1f24dd6e047f3018b7f08ed55`: this branch with the script committed, on top of `main` `fb9ccef`.
- Recorded at 2026-11-12T18:54:29+02:00 on `Nirs-MacBook-Pro.local`, macOS 27.0.1 arm64.
- Command: `zsh docs/engineering/verification/anvil-026-2026-11-12/second-machine.sh ~/.cache/modelanvil-selfhost/releases/0.1.0 fb9ccef696163f2f7b837f7ce0d6bc133eccc64e`.
- Exit code 0. The record's `stdout` holds the full output.

The run held the host test lock, so no other suite or measurement shared the machine.

## Steps and results

| Step (UTC) | What ran on the second engine | Result |
| --- | --- | --- |
| 16:44:26 | Start the fresh engine (Docker 29.9.3, linux/arm64) and count its contents | 0 images, 0 volumes, 0 containers |
| 16:44:30 | `python3 /scripts/install_selfhost.py --directory /work/instance --release /release --http-port 18080 --https-port 18443 --credentials-stdin`, with throwaway owner credentials generated inside the engine | exit 0, `ready: true`, version `0.1.0`, `production_qualified: false` |
| 16:44:51 | `curl --fail --cacert /work/instance/ca.crt https://localhost:18443/api/v1/health/`, then the controller's `status`, `stop` and `uninstall` | `{"status": "ok"}`, curl exit 0; status, stop and uninstall exit 0 |
| 16:45:02 | `python3 /scripts/qualify_selfhost.py --release /release`: a second install of the same release that trains and serves | exit 0 (details below) |
| 16:46:39 | The golden path from a clean clone at `fb9ccef` in a fresh `python:3.12-slim-bookworm` container (pinned by digest) on the second engine: `git clone`, then `sh scripts/golden_path.sh fb9ccef… --steps 3` | exit 0 |
| 16:54:28 | Remove the engine and its volume | 0 containers and 0 volumes left |

The release qualification ran on the installed package in the second engine. It recorded `fresh_install`, `verified_tls`, `owner_authentication`, `explicit_local_model_import`, `offline` and `external_acquisition_refused` all true. It also recorded 4 actual optimizer steps with 4 checkpoints, trained weights whose hash differs from the base weights, `isolated_restore_checked_state_and_all_artifact_hashes_equal` true, an uninstall that kept the four data volumes, and a restart of the retained installation, in 96.9 s. Its own scope string says it covers a small numerical CPU reference pipeline and the local-CA Docker package. It does not cover pretrained-model or task quality, public DNS or ACME, a physical second host, or native signing.

The golden path ran only the README install block. It downloaded and verified the pinned SmolLM2-135M snapshot and completed 3 CPU LoRA steps. It then loaded the exported candidate in two separate processes, `verify_cpu_export.py` and `hf_candidate_infer.py`, which returned 8 tokens each: "golden path completed 3 SmolLM2-135M CPU steps and independent inference at fb9ccef…".

The golden-path log prints the local development API key that `modelanvil/identity/management/commands/bootstrap_dev.py` creates. That key is in the repository source and is used for development only. It is not a deployment secret. The owner credentials of the self-host installs were generated inside the engine and never printed. Stock `gitleaks` 8.28.0 and 8.30.1 find nothing in this directory.

## What this does not show

- It does not show a separate physical machine. The engine shares the Mac's Docker Desktop VM with the build host.
- The golden path trains from a source clone, as the golden path defines it. The training and inference on the installed self-host package are the release qualification step above, which uses the package's small reference recipe, not SmolLM2.
- It does not cover upgrade or rollback, which belong to ANVIL-025.
- No tag, GitHub release or published image was made.

## Gates

The shared gate records for this branch are in [gates.md](gates.md).
