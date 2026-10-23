# Bounded CPU weight exports

Completed `modelanvil.smollm2-cpu-sft.v1` runs export verified native checkpoint files, adapter-only weights, merged FP32 Safetensors and Q8_0 GGUF. The supported base is `HuggingFaceTB/SmolLM2-135M` revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. This local POSIX operator workflow uses one CPU lease, one numerical thread and a five-minute deadline per conversion subprocess. Other models, accelerators and production capacity need separate qualification.

Adapter-only ZIPs exclude base weights and include tokenizer/configuration. The adapter's base reference points to the exact public source/revision; exported checksums identify the rewritten configuration separately from the original checkpoint references. Provision the verified base before loading the adapter offline. ZIPs include the source license. Optimizer state stays in checkpoints.

## Prepare and download

```sh
python manage.py prepare_cpu_export --project PROJECT_UUID --run RUN_UUID --format merged
python manage.py prepare_cpu_export --project PROJECT_UUID --run RUN_UUID --format gguf-q8
```

Install the optional pinned inference dependencies. For GGUF, build official llama.cpp commit `f5027fb21307eb264aed483242603d68c87b0fe3`, with Metal/CUDA/Vulkan/BLAS and OpenSSL disabled. Build `llama-quantize`, `llama-completion` and `llama-perplexity`; the measured Mac build used CMake 4.1.3 and two build jobs. Install converter dependencies separately; measured conversion additionally used sentencepiece 0.2.1. Set operator-owned `MODELANVIL_CPU_EXPORT_TOOLS` JSON:

```json
{"source":"/absolute/path/to/pinned/llama.cpp","quantize":{"path":"/absolute/path/to/llama-quantize","sha256":"ACTUAL_BINARY_SHA256"},"cli":{"path":"/absolute/path/to/llama-completion","sha256":"ACTUAL_BINARY_SHA256"}}
```

The source commit, clean tracked tree and binary hashes are checked. Web requests cannot supply commands or tool paths. Conversion creates an F16 intermediate and actual Q8_0 tensors, then removes the intermediate after verification. A fresh Transformers loader generates from merged weights; an independently built llama.cpp completion process generates from the GGUF. Structural metadata and numerical load evidence remain distinct.

Each request binds the checkpoint, current model/tokenizer identities, implementation and tool hashes. Private recovery receipts checksum completed phases. Repeat the identical command after interruption: verified phases are reused, incomplete phases rebuilt privately. Numerical children inherit the CPU lease descriptor, so killing the operator cannot admit another conversion while its child still runs. Partial archives never appear in download options. Atomic artifact storage and checksum verification publish the final archive. A crash between object creation and metadata commit recovers by verifying the existing object before committing its original identity. Changed inputs or corrupted recovery bytes refuse publication. Implementation/input changes create a new request.

The Training picker lists prepared formats. `GET /api/v1/training-runs/RUN_UUID/download/?export_format=merged` or `gguf-q8` rechecks project access, source identity and archive bytes, then returns the committed ZIP with checksum ETag and artifact ID. ZIP entries have fixed timestamps. Browsers without direct disk streaming retain the 256 MiB fallback limit: choose a smaller export or a browser supporting disk streaming for larger files.

## Independent consumers and measurements

```sh
python -I scripts/verify_cpu_export.py --archive EXPORT.zip --sha256 ARCHIVE_SHA256
python -I scripts/verify_cpu_export.py --archive ADAPTER.zip --sha256 ARCHIVE_SHA256 --base /verified/base
python scripts/qualify_cpu_quantization.py --baseline BASELINE_F16.gguf --quantized model-q8_0.gguf \
  --perplexity /installed/llama-perplexity --completion /installed/llama-completion \
  --heldout test.txt --heldout-manifest heldout.json --output comparison.json
```

Measure with exclusive local CPU use. This comparison profile accepts only the checksum-pinned first 32,000 Unicode characters of concatenated rows from the published Salesforce/wikitext test shard, at revision `b08601e04326c79dfdd32d625aee71d232d685c3`. Both the original shard and selected text hashes are pinned in code. A nonfixture flag alone cannot qualify another corpus. The held-out manifest also records source license metadata. The comparison runs eight 128-token chunks and three cold-process generations per format sequentially. Each native sample gets a fresh wrapper; peak RSS is not inherited from previous samples. Wall time includes process startup/model loading. OS file caches were not flushed; three repetitions do not establish a throughput guarantee. The fixed 5% perplexity regression check refuses fixture-labelled evidence and retains actual decoded output. `production_qualified` stays false even when it passes. Independently verify corpus provenance: a manifest cannot establish absence from pretraining or domain quality.

[Actual CPU evidence](verification/task27-cpu-exports-2026-10-23/report.md) records full/LoRA updates, independent loading, recovery, browser downloads and measurements. The earlier MLX 4-bit validation failure remains a failure for its own format/device; CPU Q8_0 does not replace it.

## Explicit private Hub publication

Publication is a separate trusted operator action. Preparation/download never uploads. No live Hub upload was performed in this qualification.

Configure `MODELANVIL_HUB_EXPORT_TARGETS` with an exact `TENANT_UUID:PROJECT_UUID` entry containing `repo_id`, a dedicated fine-grained repository write `token`, and exact HTTPS blob `origins` needed by that repository. Acquisition/ambient workstation credentials are not used. Installation/project policy must permit online Hub access. Keep configuration server-side; no API/archive carries the secret.

Only after owner authorization of the repository and exact archive:

```sh
python manage.py publish_cpu_export --project PROJECT_UUID --run RUN_UUID --format gguf-q8 \
  --repo owner/private-model --authorize-sha256 EXACT_ARCHIVE_SHA256
```

The bounded profile requires an existing private repository and fine-grained credential. It adds one archive at `exports/SHA256.zip`, without creating repositories, changing visibility, overwriting other exports or approving releases. A separate transport process has its own ten-minute deadline and strips ambient proxy/netrc, cookies and cross-origin bearer credentials. Installed destinations and exact repository mutation paths constrain uploads. A parent-commit condition protects concurrent updates. Retry first checks the remote LFS SHA-256/size, reconciling an already committed archive after an unknown outcome. Success receipts bind an immutable Hub commit. Missing authorization/configuration, offline policy, public repositories, conflicting bytes and unconfirmed transport fail closed. Actual Hub interoperability remains proposed qualification gate TASK-78 and requires separate authorization.
