# ANVIL-029 server-size measurement, 12 November 2026

Label: `local`. Ticket: ANVIL-029 (Aftur TASK-106). Nothing was rented and no cloud was used.

## Host and sizes

Machine: Nir's Mac, Apple M5 Pro, 18 CPUs, 48 GiB, macOS 27.0.1. The only Linux machine is the Docker Desktop VM: Docker Engine 29.9.2, kernel 7.0.14-linuxkit (aarch64), cgroup v2, 18 CPUs, 8,317,202,432 bytes (7.75 GiB) of memory. Docker Desktop settings were not changed.

An exact 8 GB VM is not available, and neither is a 4 GB VM. Each size below is a container limit inside that one VM, with `--memory` equal to `--memory-swap` (no swap) and `--cpus 4`:

| Label | Memory limit | CPU limit |
| --- | --- | --- |
| 7.5 GiB / 4 vCPU (the "8 GB class" size) | 8,053,063,680 bytes (`--memory 7680m`) | `--cpus 4` (cgroup `cpu.max 400000 100000`) |
| 4 GiB / 4 vCPU | 4,294,967,296 bytes (`--memory 4g`) | `--cpus 4` |

Each run's `cgroup-limits.txt` and `hostconfig.txt` record the limits the kernel applied. `--cpus` is a CPU-time quota, not a CPU set, so `nproc` still prints 18 inside the containers. The README training command sets `OMP_NUM_THREADS=1`.

## Results

Measured SHA for the golden path: `56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7` (`origin/main`, and this branch's head until the evidence commits). The stack runs used release `0.1.0` from ANVIL-024, built from `fe9a94c5d04e82769f87217672b9ef3eb58beb9c` (see "Stack release" below).

| Size | Workload | Run directory | Exit | GNU time max RSS | cgroup `memory.peak` | Sampled max anon (whole container) | Wall time (GNU time) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 7.5 GiB / 4 vCPU | LoRA golden path, 3 steps | `m1-lora-7.5g` | 0 | 1,484,068 kB (1.415 GiB) | 4,731,064,320 B (4.406 GiB) | 1.854 GiB | 3:08.21 |
| 7.5 GiB / 4 vCPU | LoRA golden path, 3 steps, rerun | `m1-lora-7.5g-rerun` | 0 | 1,468,548 kB (1.401 GiB) | 5,134,172,160 B (4.782 GiB) | 1.903 GiB | 6:36.75 |
| 4 GiB / 4 vCPU | LoRA golden path, 3 steps | `m1-lora-4g` | 0 | 1,480,736 kB (1.412 GiB) | 4,294,967,296 B (4.000 GiB, at the limit) | 2.252 GiB | 1:38.77 |
| 7.5 GiB / 4 vCPU | Stack + 4-step reference `full_sft` (`qualify_selfhost.py`) | `m2-7.5g` | 0 | 53,304 kB (0.051 GiB) | 4,081,692,672 B (3.801 GiB) | 0.762 GiB | 1:44.30 |
| 4 GiB / 4 vCPU | Stack + 4-step reference `full_sft` (`qualify_selfhost.py`) | `m2-4g` | 0 | 52,184 kB (0.050 GiB) | 3,819,618,304 B (3.557 GiB) | 0.742 GiB | 1:42.84 |
| 7.5 GiB / 4 vCPU | Supplementary: SmolLM2-135M `full_sft`, 3 steps | `m1-fullsft-7.5g` | 0 | 2,927,076 kB (2.791 GiB) | 5,010,436,096 B (4.666 GiB) | 2.754 GiB | 1:47.93 |
| 4 GiB / 4 vCPU | Supplementary: SmolLM2-135M `full_sft`, 3 steps | `m1-fullsft-4g` | 0 | 2,926,560 kB (2.791 GiB) | 4,294,967,296 B (4.000 GiB, at the limit) | 2.811 GiB | 2:41.51 |

No run was OOM-killed. Every `memory.events` file shows `oom 0` and `oom_kill 0`, and Docker's `State.OOMKilled` is `false` for every run. Each run also has its own `summary.json`, raw `time-v.txt`, `memory.peak.txt`, `memory.events.txt`, `memory.stat-end.txt`, one-second (golden path) or two-second (stack) `cgroup-samples.txt`, `state.json` and container log.

### What each memory number covers

- **GNU time "Maximum resident set size"** is the peak RSS of the single largest process that `time` waited for. For the golden path that is the training process. For the stack runs it is only the qualification script and the controller. The stack containers are children of the Docker engine, so GNU time does not see them.
- **cgroup `memory.peak`** is the kernel's high-water mark for the whole size-limited container, read at the end of the run. It includes page cache: pip wheels and the venv, the model download, and, for the stack, the release copies and the image load. Page cache is reclaimable. At 4 GiB the LoRA and full-SFT runs reached the limit, and the cgroup reclaimed cache instead of failing. `memory.events` counts that as `max 698` (LoRA) and `max 12333` (full SFT), with no OOM. So `memory.peak` measures how much memory was used. It does not show how much memory the run needed.
- **Sampled max anon** is the largest `anon` value in `memory.stat` (non-file memory for every process in the container) across the samples. It is the closest number here to the memory a run needs.
- `summary.json` also gives the highest value `docker stats` sampled on the host, which is usage minus inactive file cache: LoRA 2.108 / 1.889 / 2.296 GiB, full SFT 3.059 / 3.573 GiB, stack 1.244 / 0.984 GiB (7.5 GiB first, 4 GiB second).

## Pass or fail per size

Pass means exit 0 within the size.

- **7.5 GiB / 4 vCPU, LoRA: pass.** Both runs exited 0, with a peak RSS of 1.40–1.42 GiB.
- **7.5 GiB / 4 vCPU, full SFT: pass.** The self-host qualification's 4-step `full_sft` exited 0, and so did the supplementary SmolLM2-135M `full_sft` (2.79 GiB peak RSS).
- **4 GiB / 4 vCPU, LoRA: pass.** It exited 0 with a 1.41 GiB peak RSS and 2.25 GiB sampled anon. The cgroup was at its limit through page cache.
- **4 GiB / 4 vCPU, full SFT: pass.** The self-host qualification's 4-step `full_sft` exited 0, with 0.74 GiB sampled anon for the whole stack and engine. The supplementary SmolLM2-135M `full_sft` also exited 0, with a 2.79 GiB peak RSS and 2.81 GiB sampled anon. The cgroup sat at 4 GiB and reclaimed cache 12,333 times. That leaves about 1.2 GiB between that run's anon peak and the limit.

Scope of these passes:

- The stack's `full_sft` is the release's qualified recipe: the small numerical `GeneralTransformer` reference (vocabulary 260, 1 layer, 1 head, 4-dimensional embedding). It is not SmolLM2. In `compose.yaml` the stack's worker container is capped at `mem_limit: 1g` and `cpus: 1`, and the package runs offline (`MODELANVIL_PUBLIC_MODEL_DOWNLOADS: "0"`). So the packaged stack cannot run the SmolLM2 full fine-tune measured here: that process reached 2.79 GiB.
- The SmolLM2 runs train on the golden path's 10 short synthetic sentences for 3 steps. The CPU profile admits sequences up to 256 tokens. The committed `docs/engineering/verification/sequence-envelope-2026-10-28/report.json` recorded `peak_rss_bytes` 3,281,649,664 (3.06 GiB) for one 256-token FP32 AdamW step on a 16 GB host. Longer sequences therefore need more memory than measured here. This report did not measure a 256-token run at 4 GiB.
- These sizes are container limits on a 7.75 GiB VM. Inside the containers, `/proc/meminfo` and `docker info` still report the VM's 7.75 GiB. Two installed checks read that value. The self-host controller refuses an engine whose `MemTotal` is below 4 GiB (`deploy/selfhost/modelanvil.py`). `setup_gpu_training` refuses a host below the CPU profile's `memory_bytes` (4,102,062,080 bytes, from the sequence-envelope report). On a VM with 4 GiB assigned, the kernel usually reports `MemTotal` a little below 4 GiB, so both checks would probably refuse to start. This was not tested, because no 4 GiB VM was available without changing Docker Desktop settings.
- Against the ticket's estimates: the SmolLM2-135M FP32 full fine-tune peaked at 2.79 GiB RSS, against "~2.2 GB before activations". At 4 GiB, full SFT did fit for this short 3-step run, so it is not only LoRA or inference that fits. The stack used less than the "~1–1.5 GB" estimate: 0.74–0.76 GiB anon for the engine plus all containers, and 1.24 GiB at most by `docker stats`. The cited `reviews/architecture-managed-hosting.md` §3 is not in this repository or in the ModelAnvil project memory, so the estimates are taken from the ticket text.

## Golden-path phase times

These durations come from the Docker log timestamps (`harness/phases.py`). Wall time depends mostly on network speed during `pip install`, not on the size.

| Run | Clone | venv | torch install | requirements install | migrate, bootstrap, check | Model download and 3 training steps | Independent inference |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `m1-lora-7.5g` | 11.1 s | 1.2 s | 25.2 s | 116.7 s | 5.4 s | 22.1 s | 6.5 s |
| `m1-lora-7.5g-rerun` | 7.7 s | 1.2 s | 20.0 s | 335.9 s | 5.2 s | 19.7 s | 7.1 s |
| `m1-lora-4g` | 8.3 s | 1.3 s | 24.6 s | 31.2 s | 5.0 s | 20.7 s | 7.7 s |
| `m1-fullsft-7.5g` | 6.0 s | 1.2 s | 22.8 s | 29.7 s | 4.8 s | 35.6 s | 7.9 s |
| `m1-fullsft-4g` | 7.0 s | 1.3 s | 30.5 s | 72.2 s | 5.2 s | 38.1 s | 7.3 s |

During the rerun, PyPI downloads ran at about 335 kB/s (`container-log.txt`). That is why the rerun's wall time is twice the first run's.

## Stack per-service peaks

From the two-second samples of each inner container's own cgroup (`memory.peak`, and the highest sampled `anon`), taking the highest value per service across the original and restored instances. Short `compose run` containers can finish between samples, so the migrate figures may be low.

| Service | 7.5 GiB peak / anon | 4 GiB peak / anon | Compose `mem_limit` |
| --- | --- | --- | --- |
| worker | 215.3 / 197.7 MiB | 215.6 / 197.2 MiB | 1 GiB |
| api | 201.6 / 181.2 MiB | 197.7 / 184.4 MiB | 1 GiB |
| db (pgvector) | 115.7 / 10.1 MiB | 114.9 / 9.0 MiB | 512 MiB |
| migrate (`compose run`) | 102.7 / 97.9 MiB | 102.3 / 95.6 MiB | 1 GiB |
| reconciler | 71.8 / 66.9 MiB | 71.2 / 66.9 MiB | 1 GiB |
| web (Caddy) | 24.0 / 19.4 MiB | 23.8 / 19.5 MiB | 256 MiB |

The inner engine's cgroup (`/init`: dockerd, containerd, the qualification script and the controller) peaked at 2,931 MiB and 2,811 MiB (`engine-init.memory.peak.txt`). Almost all of that is page cache from loading `images.tar` and copying the release for install and restore. The whole container's sampled anon stayed at or below 0.762 GiB.

Each stack qualification (`qualification.json`) passed every step: fresh install with verified TLS, owner sign-in, offline example import, CPU chat completion, 4 optimizer steps with 4 checkpoints and changed weights, refusal of an external model import, backup, isolated restore with equal state and artifact hashes, uninstall that kept the 4 data volumes, and restart. Both runs removed their own projects, and `inner-leftovers.txt` is empty.

## Commands

Harness scripts are under `harness/`. Every container run went through the host test lock, `testlock.sh <command>`.

Golden path (`harness/run_m1.sh lora <size> <memory> 4`):

```sh
docker run -d --name anvil029-lora-<size> --platform linux/arm64 --memory <memory> --memory-swap <memory> --cpus 4 \
  -e MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1 -v <anvil-029 worktree>:/src:ro -v <harness>:/harness:ro -v <out>:/out \
  python:3.12-slim-bookworm@sha256:<pinned digest in harness/run_m1.sh> \
  sh /harness/m1-inner.sh lora 56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7
# inside (harness/m1-inner.sh):
apt-get update -qq && apt-get install -y -qq --no-install-recommends git time make ca-certificates
cd /src && /usr/bin/time -v -o /out/time-v.txt sh scripts/golden_path.sh 56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7 --steps 3
cat /sys/fs/cgroup/memory.peak
```

`/src` is this worktree at `56b35cc`. `golden_path.sh` cloned that SHA from `https://github.com/nirtuttnauer/ModelAnvil.git` into `/tmp`, ran only the README install block (Python 3.12.16, `torch 2.13.0+cpu`, `transformers 5.14.0`, `peft 0.21.2`), trained 3 CPU LoRA steps on the pinned SmolLM2-135M, and loaded the export in two separate processes. Each process returned 8 tokens. GNU time is Debian's `time` 1.9-0.2. Its `--version` prints `UNKNOWN`. `make` is installed because the README install block runs `make migrate` and `make check`.

The supplementary SmolLM2 full SFT used the same container, with `sh /harness/fullsft.sh <sha>` in place of `scripts/golden_path.sh`. That script does the same clone, README install block and README train command. The only difference is one edit in the cloned `scripts/golden_path.py`, before training: `recipe="lora_adapter"` becomes `recipe="full_sft"`. The log shows the patched line (`278:        recipe="full_sft",`). The run still prints `completed 3 SmolLM2-135M CPU LoRA steps`, because that text is fixed in `run_steps`. The process peak RSS confirms that the full model was trained: 2.79 GiB, against 1.41 GiB for LoRA. That increase is about the size of full-parameter gradients plus AdamW moments for 135M FP32 parameters.

Stack (`harness/run_m2.sh <size> <memory> 4 <release> <worktree>/scripts`):

```sh
docker run -d --privileged --name anvil029-stack-<size> --platform linux/arm64 --memory <memory> --memory-swap <memory> --cpus 4 \
  -v anvil029-dind-<size>:/var/lib/docker -v ~/.cache/modelanvil-selfhost/releases/0.1.0:/release:ro \
  -v <anvil-029 worktree>/scripts:/qual:ro -v <harness>:/harness:ro -v <out>:/out \
  docker:dind@sha256:<pinned digest in harness/run_m2.sh>
docker exec anvil029-stack-<size> sh /harness/m2-inner.sh
# inside (harness/m2-inner.sh), inner engine Docker 29.9.3, Compose v5.7.0:
apk add python3 time            # Python 3.14.10, GNU time 1.10
/usr/bin/time -v -o /out/time-v.txt python3 /qual/qualify_selfhost.py --release /release --output /work/qualification
cat /sys/fs/cgroup/memory.peak
```

The Docker-in-Docker approach worked at both sizes, so the fallback (`docker stats` on the unconstrained engine) was not needed. The controller loaded `images.tar` into the inner engine and ran Compose there. Inner containers live in cgroups below the size-limited container, so the limit and `memory.peak` cover the engine, every stack container and the qualification script. The published ports exist only in the inner engine's network namespace, so no host port was used.

## Stack release

`m2-release-0.1.0.json` is a copy of the release's `release.json`: version `0.1.0`, source revision `fe9a94c5d04e82769f87217672b9ef3eb58beb9c` (branch `claude/anvil-024-selfhost-install`, one commit on top of `56b35cc`), images api `sha256:20b2a07b…`, web `sha256:d82a908d…`, db `sha256:7b822b0a…`, qualified recipe `modelanvil.general-transformer-sft.v1` `full_sft`. At `56b35cc` and `fe9a94c`, the git blobs of `scripts/qualify_selfhost.py` (`6c7ebd5f`) and `deploy/selfhost/modelanvil.py` (`6666e0b1`) are the same. The release's `modelanvil.py` and `compose.yaml` have the same SHA-256 as the `56b35cc` files.

## Timeline, lock and concurrent activity

All times are UTC on 12 November 2026.

- `m1-lora-7.5g` ran 14:08:07–14:11:23 in its own hold of the test lock (lock acquired 14:06:51). The harness waited 75 s for the ANVIL-024 image build (`build_selfhost_release.py`) to finish before starting. During the run, the ANVIL-024 work started two self-host stacks on the same Docker Desktop VM, without the lock: Compose projects `modelanvil-local-0ed3435685da` and `modelanvil-local-a7cf9659dbae`, built from the release 0.1.0 images. This run is kept but labeled as disturbed. The harness was then changed to wait for any `modelanvil-local-*` container as well, and the LoRA 7.5 GiB run was repeated as `m1-lora-7.5g-rerun`.
- The other six runs ran back to back, from 15:54:42 to 16:12:20, inside one hold of the lock (`harness/batch.sh`). The test-suite queue had held the lock for about an hour per premerge suite, so one hold was used instead of six. In order: `m1-lora-4g`, `m1-fullsft-7.5g`, `m1-fullsft-4g`, `m1-lora-7.5g-rerun`, `m2-7.5g`, `m2-4g`. In the batch, the two `run_m2.sh` lines failed at once with "permission denied" because the file was not executable, so no container was started. A block appended to `run_m1.sh` (see the end of `harness/run_m1.sh`) then ran both stack measurements at the end of the same lock hold.
- During those six runs, the only other containers in the VM were two long-running `mosscms` containers, using 170–345 MiB together (`host-before.txt`). No build, qualification or test-suite process was seen. Each run's `concurrency.txt` lists what its samples saw. The Mac itself was busy with work outside the lock. The host load average reached 40.5 during the stack and full-SFT runs. After the runs, Xcode `swift-frontend` and another project's UI harness were seen among the busiest processes. Host load can stretch wall times, but it does not change the memory limits inside the VM.
- After the measurements, one sub-second `python3 --version` container ran outside the lock, to record the image's Python version.
- All `anvil029-*` containers and the `anvil029-dind-*` volumes were removed.

## Files

- `report.md`: this report.
- `m1-lora-7.5g/`, `m1-lora-7.5g-rerun/`, `m1-lora-4g/`, `m1-fullsft-7.5g/`, `m1-fullsft-4g/`, `m2-7.5g/`, `m2-4g/`: per run, `time-v.txt` (raw GNU `time -v`), `exit-code.txt`, `memory.peak.txt`, `memory.events.txt`, `memory.stat-end.txt`, `cgroup-limits.txt`, `cgroup-samples.txt`, `hostconfig.txt`, `state.json`, `run-times.txt`, `summary.json` and `concurrency.txt`. Golden-path runs also have `container-log.txt` (Docker-timestamped stdout and stderr), `apt-log.txt` and `memory.peak-after-apt.txt`. Stack runs also have `exec-log.txt`, `dind-log.txt`, `apk-log.txt`, `qualification.json`, `qualification-files.txt`, `inner-leftovers.txt`, `tool-versions.txt`, `engine-init.memory.peak.txt` and `memory.peak-after-engine-start.txt`. The logs are stored as `*-log.txt` because the repository's `.gitignore` excludes `*.log`. Their content is unchanged.
- `m2-release-0.1.0.json`: the release manifest that was measured.
- `harness/`: the scripts that ran.
- `gates.md`: the shared gate records for this branch.

The qualification's private credentials and logs stayed in the scratch output and are not committed.
