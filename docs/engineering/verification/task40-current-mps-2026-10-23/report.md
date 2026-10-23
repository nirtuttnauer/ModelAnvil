# TASK-40: current-stack bounded Apple MPS qualification

23 October 2026 · The human explicitly authorized using this Mac for bounded tests while separating implementation from qualification. These new observations supersede the old package-set evidence only for the operation envelope stated here.

## Exact tested envelope

Apple M5 Pro, 48 GiB unified memory, macOS 27.0.1/Darwin 27.0.0, Python 3.12.15; PyTorch 2.13.0, Transformers 5.14.0, Safetensors 0.8.0, Tokenizers 0.22.2 and the pinned PEFT 0.21.2 LoRA dependency. Explicit `mps:0`, FP32, no CPU fallback. Public Apache-2.0 `HuggingFaceTB/SmolLM2-135M`, revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`, with all five fixed model/config/tokenizer file hashes verified before import. Source main at measurement was `42210f96beb1b310f7c1a54ed0f12584c8473398`; runtime/script file hashes and contract/build digests are in the [actual report](actual-report.json).

Two independent new disposable databases/artifact directories ran the existing three-step worker qualification. The original installation, projects, databases, workers, branches and worktrees were not changed.

| Recipe | Actual trainable parameters | Final candidate weights SHA256 | Maximum observed allocated bytes |
| --- | ---: | --- | ---: |
| Full SFT | 134,515,008 | `f9f7c24c2787a4f871dc0ad718184bd5148223c5851b1ef80fdb0e9dd3955eef` | 2,240,704,000 |
| Rank-8 q/v LoRA | 460,800 | `266058817e89632f3023feb7507e15b268367e1227c51dd4973d440da67d1f55` | 551,370,496 |

Every recorded step checks real MPS tensor residency and records measured loss, gradient norm, elapsed time and allocated/driver memory. Maximum observed allocation is the largest recorded step sample. Peak allocated/reserved memory and GPU utilization are unavailable and remain null. Process headroom is the framework's process allowance, with driver/cache allocations; it is not a system-wide free-memory measurement or reservation.

## Load, fencing and accounting evidence

Both candidates were loaded in separate CPU and MPS consumer processes which import neither ModelAnvil nor Django. Each pair produced identical eight-token greedy outputs and matching candidate/file hashes. This is a bounded reload/decoding comparison, with no inference-quality or speed claim.

For each recipe, an expired lease stopped at committed step one; a second attempt restored optimizer/sampler/checkpoint state and finished step three with exactly the uninterrupted candidate bytes. Cancellation settled one committed step without publishing a candidate. Corrupt input was refused with zero committed work and zero settlement. Busy-device and unsupported precision/adapter/quantization requests created no jobs or budget reservations. Full runs reserved and settled three training steps. Raw report hashes are public; full raw receipts and logs are durably attached to TASK-40, with model weights/databases retained outside Git.

## Reproduction

Install the current base and GPU requirements in a separate environment. Supply the five locally verified files named by `hf_runtime.FILE_HASHES` and use new output directories:

```sh
python scripts/qualify_hf_gpu.py --model-dir /absolute/path/to/verified-smollm2-base --device mps:0 --recipe full_sft --output /new/path/full-sft
python scripts/qualify_hf_gpu.py --model-dir /absolute/path/to/verified-smollm2-base --device mps:0 --recipe lora_adapter --output /new/path/lora
```

The command creates synthetic correctness fixtures, new isolated state and local bounded jobs. It never supplies a customer outcome or uses the existing installation's database. Run one qualification at a time. Recheck exact package/device/model pins before using a receipt.

## Remaining gates

This qualifies the named three-step FP32 correctness/recovery envelope on this physical Mac. Other Apple generations, larger workloads, mixed precision, quantization/QLoRA, MLX, CUDA/ROCm/XPU, distributed training, representative task quality and production operations require their own evidence. CPU software completion does not imply those qualifications. TASK-76/77 preserve separate inference/training hardware criteria; customer-dependent work and history rewriting remain held.

Documentation validation checks raw-receipt hashes and all actual-report assertions, resolves local links, preserves the report-generated README table and passes `git diff --check`. Required final documentation-PR CI gates merge; exact final head and merge evidence are attached in Aftur. No new software feature or changed runtime code is claimed by this documentation-only PR.
