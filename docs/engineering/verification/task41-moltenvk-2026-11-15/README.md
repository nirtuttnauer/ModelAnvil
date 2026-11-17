# TASK-41 (MA-GPU-06): Vulkan GGUF inference through MoltenVK on this Mac's Apple GPU

15 November 2026. Nir chose this path in chat on the same day: install Homebrew's Vulkan loader and MoltenVK, build llama.cpp with Vulkan, and qualify only the Apple GPU through that translation layer. This report covers exactly that one device and software stack. It makes no discrete-GPU, other-vendor, Linux, Windows/DirectML or Vulkan-training claim.

## Verdict

ModelAnvil now has a separately named, inference-only backend, `vulkan:0`. It runs GGUF chat completions on the pinned llama.cpp Vulkan build, configured and built with CMake. That build reaches the Apple M5 Pro through MoltenVK 1.4.2, and Metal is not compiled into it.

On this Mac, all three measured formats (F16, Q8_0 and Q4_K_M) load with 31/31 layers and the KV cache on `Vulkan0`, and they decode deterministically. F16 output matches the CPU-only build of the same commit character for character on all three pinned prompts. Q8_0 and Q4_K_M are deterministic on each backend, but their output departs from the CPU build after a shared prefix. That difference is measured and reported below.

Training on Vulkan is refused before any allocation. CPU fallback happens only by explicit operator opt-in, and a fallback run is recorded and labelled CPU.

## Environment

| Item | Value |
|---|---|
| Host | Apple M5 Pro (18 CPU cores, 48 GiB unified memory), macOS 27.2.1 build 26B131, arm64 |
| GPU through Vulkan | `vulkaninfo --summary` GPU0: `deviceName = Apple M5 Pro`, `deviceType = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU`, `vendorID = 0x106b`, `deviceID = 0x1b02020a`, `driverID = DRIVER_ID_MOLTENVK`, `driverName = MoltenVK`, `driverInfo = 1.4.2`, `apiVersion = 1.4.357`, `driverVersion = 0.2.2210`, `conformanceVersion = 1.4.4.0`. Vulkan instance version 1.4.363 |
| Installed (Homebrew 7.0.13, bottles, homebrew/core) | `molten-vk` 1.4.2, `vulkan-loader` 1.4.363.0, `vulkan-headers` 1.4.363.0, `vulkan-tools` 1.4.363.0, `shaderc` 2026.4 (glslc), plus the dependencies `glslang` 16.6.0, `spirv-tools` 1.4.363.0 and `spirv-headers` 1.4.363.0. Command: `brew install molten-vk vulkan-loader vulkan-headers vulkan-tools shaderc` |
| Driver bytes | ICD manifest `/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json` (`api_version` 1.4.0, portability driver) sha256 `b514f516…0bf1`; `libMoltenVK.dylib` sha256 `e21bcead…d542`; `libvulkan.1.4.363.dylib` sha256 `6453921b…4208`. Full values are in [toolchain.json](toolchain.json) |
| llama.cpp's own device listing | `Vulkan0: Apple M5 Pro (49152 MiB, 38338 MiB free)`. This is the unified-memory heap MoltenVK reports, not dedicated VRAM |
| Compiler | Apple clang 21.0.0 (clang-2100.4.1.1), macOS SDK from the Command Line Tools |

`vulkan-tools` also installs a mock ICD. Every measured child process therefore receives only the MoltenVK manifest (`VK_DRIVER_FILES` and `VK_ICD_FILENAMES`), sees one device (`GGML_VK_VISIBLE_DEVICES=0`) and has implicit layers disabled (`VK_LOADER_LAYERS_DISABLE=~all~`). No other variables are inherited.

## llama.cpp pin and build

- **Commit.** `f5027fb21307eb264aed483242603d68c87b0fe3` (build 11836, 2026-10-23). The repository already pins this commit for GGUF: `cpu_exports.LLAMA_COMMIT`, the TASK-27 CPU tools and the converter that produced the F16 fixture. Its Vulkan backend has MoltenVK handling, including the portability enumeration, the MoltenVK `external_memory_host` and sigmoid-fusion workarounds, and same-UUID de-duplication, so no newer commit was needed.
- **Build system.** Homebrew `cmake` 4.5.0 (bottle; `brew install cmake`, authorised by Nir on 15 November). An earlier version of this report used binaries from a hand-written clang script that reproduced the CMake configuration while CMake was unavailable; that build and its numbers were replaced by this CMake build and full requalification before any merge.
- **Configure** (source checkout at `~/.cache/modelanvil-tools/src/llama.cpp-f5027fb`, tracked tree clean):
  `cmake -S ~/.cache/modelanvil-tools/src/llama.cpp-f5027fb -B ~/.cache/modelanvil-tools/llama.cpp-vulkan-f5027fb-cmake -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_VULKAN=ON -DGGML_METAL=OFF -DGGML_BLAS=OFF -DLLAMA_OPENSSL=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF`
  and the same with `-DGGML_VULKAN=OFF -B ~/.cache/modelanvil-tools/llama.cpp-cpu-f5027fb-cmake` for the CPU-only reference. The two UI options keep the configure and build offline; the server runs with `--no-webui`.
- **Build:** `cmake --build <build dir> --config Release -j 8 --target llama-server llama-completion llama-bench llama-quantize test-backend-ops`.
- **What CMake resolved.** The native ARM probes gave `-U__ARM_FEATURE_SVE -mcpu=native+dotprod+i8mm+nosve+sme`; Accelerate, llamafile and CPU repack are on. OpenMP is not found by Apple clang, so it is not used, although the cache keeps `GGML_OPENMP=ON`. KleidiAI, RPC, CUDA, BLAS and Metal are off. Vulkan was found at `/opt/homebrew/lib/libvulkan.dylib` (1.4.363) with glslc from shaderc 2026.4, and all seven glslc extension tests passed (cooperative matrix 1 and 2, decode vector, integer dot, bfloat16, E2M1, E4M3). The device decides at run time which of them it uses. 155 shader sources are compiled.
- **Build records.** [build-record-vulkan.json](build-record-vulkan.json) and [build-record-cpu.json](build-record-cpu.json) were written by [record_cmake_build.py](record_cmake_build.py). They hold the configure and build commands, CMakeCache values, ggml-cpu and ggml-vulkan compile flags, compile-database size (483 and 325 entries), linked libraries, Metal symbol counts and SHA-256 values.
- **Metal is absent.** No `ggml-metal` source is in either compile database. The Vulkan binaries link only Accelerate, libSystem, libc++ and Homebrew's `libvulkan.1.dylib`, with 0 Metal symbols in every binary. The CPU-only binaries link only libSystem, Accelerate and libc++, and their `llama-server --list-devices` lists no device. Both report `version: 0.7.0-dev (build 11836, commit f5027fb21)`.

| Binary | Vulkan build sha256 | CPU-only build sha256 |
|---|---|---|
| `llama-server` | `4163f614da82e461430598f03b0c51bf84bf03f43429bbeac5ccc074b739e7f7` | `1101140b2d8b099f3b5ee1c35900cf566a42627f9b50fc65c33057fa94e786fc` |
| `llama-completion` | `dfe5e2a6f2eb46bc7218db056ae200aa9c3732f57368141f95a4547455d3349f` | `63ac979c8e2af038226c6ea21e77cc6b55bcf87176bf37c822acdaa1a59d7e4b` |
| `llama-bench` | `62653c9e2f6282c15ba3d0c5ed2089680eb2c65ae9cb21d27e135e824e97873e` | `1963820b9b66da42e820aa10894830eea6628165b7c32d4bd2c5d2afb078abce` |
| `llama-quantize` | `94325f2016a634053e67854136ee12214236a0147572d0879665b12ea4f623de` | `da27544a69c5b5ba9b3faf0f7a4f1c215fd03f8a3c60c8876841bb7b8f7a41e5` |
| `test-backend-ops` | `8fd58d2f8aeda762ce08d3a39019dbbaac2c7bcf824922b9c10c5e3bd6d2a53c` | `fd3830592584a39440e90a7035adb3bc9f22efb7888078a761cc6cc826af4048` |

## Model files

| Label | File | sha256 | Bytes | Tensor types |
|---|---|---|---|---|
| F16 | `smollm2-135m-instruct-f16.gguf` (existing fixture, see `~/.cache/modelanvil-fixtures/PROVENANCE.md`) | `8a74026b949a60575f3f23c5fd4a94915814d40c057134e3c4c2588e966655cb` | 270,886,400 | 211 F16, 61 F32 |
| Q8_0 | `smollm2-135m-instruct-q8_0.gguf` | `099b9a731e9eab4bf72402dca4fc70fee21d22d5b41f7b17dc6464bf5d21228d` | 144,811,520 | 211 Q8_0, 61 F32 |
| Q4_K_M | `smollm2-135m-instruct-q4_k_m.gguf` | `310b730e0ae3f8306952ab2edccef5308e1b32fd6ef5cdc43d45cbc9ae6ca234` | 105,454,592 | 16 Q4_K, 166 Q5_0, 14 Q6_K, 15 Q8_0, 61 F32 |

The quantized files were derived with the CPU-only `llama-quantize`: `env -i PATH=/usr/bin:/bin HOME=<tmp> llama-quantize smollm2-135m-instruct-f16.gguf OUT.gguf Q8_0|Q4_K_M 4`. For Q4_K_M, llama-quantize reported that 180 of 272 tensors required fallback quantization, because this model's 576 columns are not divisible by the 256-wide K-quant rows. That is why Q5_0 dominates the file. Re-running the same commands with the CMake-built CPU-only `llama-quantize` reproduced both files byte for byte (same SHA-256). Model bytes stay outside Git.

## Qualification measurements

The measurement script is [qualify_vulkan_inference.py](../../../../scripts/qualify_vulkan_inference.py), and its output is [qualification-summary.json](qualification-summary.json). The run used the CMake builds, lasted from 19:21:13 to 19:22:58 +0200 and was taken behind the host compute lock.

- **Prompts.** Three pinned ChatML prompts: "What is 2 + 2?", "Name three primary colors." and "Write one sentence about the ocean."
- **Generation settings.** Each prompt ran twice per build with `-n 64 --temp 0 --seed 42 -c 2048 -t 1 -tb 1 -no-cnv --fit off -lv 4`. The Vulkan runs added `-ngl all -dev Vulkan0` and the CPU runs used `-ngl 0`.
- **Seed.** With greedy decoding, llama.cpp prints `sampler seed: 4294967295` because the chain has no random sampler.
- **Throughput.** Tokens per second come from `llama-bench -p 128 -n 64 -r 5 -t 1` (mean ± standard deviation over 5 repetitions).
- **Peak RSS.** Taken from `/usr/bin/time -l` for the `llama-completion` process. The figures are not a reservation and not a throughput guarantee.

| Format | Build | Offloaded (llama.cpp's own report) | llama.cpp buffers, MiB | Peak RSS, MiB | pp128 tok/s | tg64 tok/s | Greedy output vs CPU-only build |
|---|---|---|---|---|---|---|---|
| F16 | Vulkan | 31/31 layers | model Vulkan0 256.63 + Vulkan_Host 54; KV Vulkan0 45; compute Vulkan0 102.52 + Vulkan_Host 6.52 | 175 | 10059 ± 62 | 311 ± 3 | **3/3 prompts identical** (201, 263, 193 characters) |
| F16 | CPU-only | none | model CPU_Mapped 256.63; KV CPU 45; compute CPU 104.77 | 332 | 399 ± 10 | 254 ± 1 | reference |
| Q8_0 | Vulkan | 31/31 layers | model Vulkan0 136.40 + Vulkan_Host 28.69; KV Vulkan0 45; compute Vulkan0 102.52 + Vulkan_Host 6.52 | 149 | 8197 ± 67 | 370 ± 2 | 0/3 identical; shared prefixes of 21, 24 and 116 characters |
| Q8_0 | CPU-only | none | model CPU_REPACK 136.27; KV CPU 45; compute CPU 104.77 | 348 | 1291 ± 6 | 461 ± 30 | reference |
| Q4_K_M | Vulkan | 31/31 layers | model Vulkan0 98.87 + Vulkan_Host 28.69; KV Vulkan0 45; compute Vulkan0 102.52 + Vulkan_Host 6.52 | 152 | 7966 ± 72 | 363 ± 3 | 1/3 identical; shared prefixes of 37 and 139 characters, third prompt identical (142) |
| Q4_K_M | CPU-only | none | model CPU_Mapped 1.16 + CPU_REPACK 47.54; KV CPU 45; compute CPU 104.77 | 222 | 376 ± 2 | 288 ± 2 | reference |

### How to read the table

- **Compared with the replaced hand-written build.** Every decoded text (all prompts, both repeats, all three formats, both builds), the output-match results and shared prefixes, offloaded layers, llama.cpp buffer sizes, graph placement, `test-backend-ops` results and the unsupported-case table are identical. Only timing and peak RSS moved, within run-to-run noise on a shared host: Vulkan pp128 10059 vs 9925 (F16), 8197 vs 7865 (Q8_0), 7966 vs 7995 (Q4_K_M) tok/s; Vulkan tg64 311 vs 299, 370 vs 371, 363 vs 375; CPU tg64 254 vs 233, 461 vs 431, 288 vs 274; Vulkan peak RSS +2 to +3 MiB. The table shows only the CMake measurements.

- **Determinism.** Every build repeated its own greedy output exactly.
- **Quantized divergence.** Q8_0 and Q4_K_M diverge from the CPU build because Vulkan's quantized matrix kernels round and accumulate differently from the CPU kernels. `test-backend-ops` accepts those kernels within its error bound, but greedy decoding of a 135M model amplifies small logit differences into different tokens. The decoded texts are in the summary. No quality claim is made either way.
- **Throughput comparison.** Vulkan is much faster at prompt processing. With one CPU thread, generation is faster on Vulkan for F16 and Q4_K_M, but slower than the CPU for Q8_0.
- **Device memory accounting.** llama.cpp's breakdown for F16 is `Vulkan0 (Apple M5 Pro) | 49152 = 37872 + (404 = 256 + 45 + 102) + 10875`. That is total = free + (self = model + context + compute) + memory other processes use. The `Vulkan_Host` buffers are host-visible unified memory.

### Graph placement and unsupported operations

A `GGML_SCHED_DEBUG=2` trace was recorded for each format, covering 5,190 non-view node assignments across an eight-token run. It shows two splits: a CPU split for the token-embedding lookup, then one `Vulkan0` split for everything else.

- **On the CPU.** The only CPU nodes are the input `GET_ROWS` (20 per run). llama.cpp keeps the input layer's embedding table on the host for every GPU backend, so this does not indicate an unsupported operation.
- **On Vulkan0.** Every other node ran on `Vulkan0`: `MUL_MAT` 2,110, `ADD` 600, `MUL` 610, `RMS_NORM` 610, `ROPE` 600, `FLASH_ATTN_EXT` 300 (flash attention enabled), `SWIGLU` 300, `GET_ROWS` 20, `SET_ROWS` 10 and `DUP` 10.

Results from `test-backend-ops` on the Vulkan build:

- **Correctness of the graph's ops.** `test -b Vulkan0 -o ADD,DUP,GET_ROWS,MUL,MUL_MAT,RMS_NORM,ROPE,SET_ROWS,SWIGLU` passed **3601/3601** cases against the CPU backend. Separately, `FLASH_ATTN_EXT -p 'hsk=64,hsv=64,.*type_K=f16,type_V=f16'`, the model's 64-wide f16 heads, passed **231/231**.
- **Unsupported combinations.** `support -b Vulkan0` probed 117 ops and lists the type/shape combinations this device does not support, per op, in the summary. Examples: `CPY` 325 of 600 cases, `SET_ROWS` 408 of 727, `MUL_MAT` 398 of 2,864, `OUT_PROD` 1,344 of 1,415, `CONV_2D` 1,178 of 3,144, `TOP_K_MASK` all 24, and 4 of 12 cases of most unary ops.
- **Scope.** The qualified model graph uses none of the unsupported combinations. A model that needs them, or any other architecture, is outside this qualification.

## ModelAnvil integration evidence

| Requirement | Evidence |
|---|---|
| Actual load and generation through ModelAnvil, with device and driver evidence in the run record | [session-evidence.json](session-evidence.json), produced by [session_evidence.py](session_evidence.py), drives `VulkanGGUFSession` for each format. It records the server's own load report (`offloaded 31/31 layers to GPU`, `Vulkan0 model buffer size = 256.63/136.40/98.87 MiB`, `Vulkan0 KV buffer size = 45.00 MiB`, `Flash Attention enabled`), the chat-template output (F16: "2 + 2 is a classic arithmetic operation that can be understood by converting it"), identical repeats, cancellation after 3 computed tokens, 401 without the session key, and the listener closed after unload. The tagged `VulkanNativeChat` test runs a real `/api/v1/inference/chat/completions` request on `vulkan:0` and checks that the stored `InferenceRequest` receipt carries `backend llama.cpp-vulkan`, `gpu_execution true`, 31/31 layers, `Apple M5 Pro`, `MoltenVK`, `F16`, buffers and runtime hashes |
| Formats, quantization and OS/driver pinned; other inputs refused | `vulkan_runtime.QUALIFIED_*` pins macOS 27.2.1 arm64, the ICD, MoltenVK and loader SHA-256, `general.file_type` F16/Q8_0/Q4_K_M, llama architecture, 1 GiB and 2,048 tokens. Unit tests refuse a changed binary, manifest, driver, loader or OS, and Q4_0, Q5_K_M and Q6_K files, all before any process starts. [support-gguf-inference-vulkan.json](support-gguf-inference-vulkan.json) is the read-only support report |
| Training refused on the inference-only backend | `select_device('vulkan:0')`, `setup_gpu_training --device vulkan:0` (no model, worker or pool rows created) and every training row of the support report refuse with the inference-only message ([support-full-sft-vulkan-refused.txt](support-full-sft-vulkan-refused.txt)) |
| Fallback only by explicit operator opt-in, recorded, and never billed or labelled GPU | Without `"cpu_fallback": true` (including `"yes"` or `1`), an unavailable backend fails closed, and callers that cannot label fallback never get one. With opt-in, the GPU lease is released and the CPU lease taken. The response reports `device: cpu`, `requested_device: vulkan:0` and a `fallback` record (`operator_opt_in`, reason, `gpu_execution: false`, `billing_device: cpu`). The receipt's signature is CPU, so it never load-tests `vulkan:0`, and no `UsageEvent` is created |
| Recovery | The native test kills the server mid-stream: that generation fails with `ValueError`, and a fresh session then serves the next request. At API level, a mid-stream native failure records `failed`, releases admission, and the next request completes. A busy shared Apple lease (`mps:0`/`mlx:0`) refuses `vulkan:0` without a CPU substitute. The server child inherits the GPU lease and a 30-minute hard lifetime, so an orphan cannot overlap another GPU user |
| Tenant and project boundaries | Another project's key gets 404 for the model, sees no catalog entry, and gets no load receipt. Each session's server, port and bearer key belong to one request and are removed on unload |

The test commands and counts are in [tests.txt](tests.txt); every run used the CMake builds. The focused backend suite passed 139 tests. The tagged native Vulkan tests passed 2 of 2, covering F16, Q8_0 and Q4_K_M, recovery, and the API receipt. The Node OpenAPI test passed 3 of 3.

## Acceptance criteria

0. **Met for the one named device.** The pinned model loads and generates on the Apple M5 Pro through MoltenVK, with measured offload (31/31 layers and KV on `Vulkan0`), buffers, device and driver identity, output and throughput, both in the native tool runs and through ModelAnvil's API.
1. **Met for this stack.** The exact formats (GGUF F16, Q8_0, Q4_K_M; llama architecture), the OS and driver versions, and the unsupported operations are recorded, and training on Vulkan is refused. **Not covered:** other devices, operating systems, vendors or quantizations. In particular there is no discrete-GPU, AMD, NVIDIA or Intel, Linux, Windows or DirectML evidence; the ticket's cross-vendor scope needs its own hardware.
2. **Met.** CPU fallback is explicit operator opt-in, recorded, labelled CPU, unbilled and never a GPU receipt. Recovery and tenant/project boundaries are tested. The web chat page shows only the device the user selected and does not yet surface the `fallback` record. The API response and the stored receipt carry it.

## Limits

- The evidence covers one 135M model on one Mac. It is not a model-quality, production or throughput guarantee, and other workloads were running on the host.
- The qualified binaries are the CMake builds above. A rebuild gives a new server hash that the operator configuration must name; requalify it with the same commands.
- A Homebrew upgrade of `molten-vk` or `vulkan-loader`, a macOS update, or a rebuilt server changes pinned bytes. The backend then refuses until it is requalified.
- Raw logs (`llama-completion`, `llama-bench`, `test-backend-ops`, scheduler traces) remain in the private output directory `~/.cache/modelanvil-private/task41-cmake-qualification-20261115T192111/ (test logs: task41-cmake-tests-20261115T192111/)`. The summary in this directory is the publishable record.
