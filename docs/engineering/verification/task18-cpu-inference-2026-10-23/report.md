# TASK-18 — verified local CPU inference and current authority

23 October 2026. The human approved CPU-first implementation with separate GPU/MLX qualification gates. TASK-18 now covers bounded verified Safetensors and GGUF CPU inference. Its original GPU/MLX criteria remain preserved in TASK-76; this report does not complete that gate.

## Change and trust boundary

The existing local loaders verify model, tokenizer/template and immutable artifact bytes before actual allocation. Safetensors text snapshots are bounded to 1 GiB of weights and 300 million parameters (a separately declared large guided profile has its own limits). GGUF CPU weights are bounded to 1 GiB using the newly replaced native llama.cpp binding. Both reserve generated output within a 2,048-token maximum context. Unsupported architectures, formats, quantization and device combinations remain unavailable. These static bounds are not a measurement or reservation of currently free host RAM.

The remaining access bug allowed a loaded stream to keep sending text after its key, project grant or model inputs were withdrawn. The completion API now reuses current authentication and role checks and validates frozen model/tokenizer identities, artifact availability and project access before publishing generated parts. It also rechecks before the initial stream event and optional usage event. Archived/rejected models cannot load. Buffered completions withhold their accumulated text when authority changes during generation.

Each stream resumes and closes in its captured request context, so subsequent requests cannot substitute a different active tenant/project and stream authentication cannot overwrite another request's context. Generator close and failure still release both process and physical-device admission and unload native/model resources. A failed access check emits a generic inference error without the prefetched text; it never replaces model output with a fixture.

## Actual bounded execution

The [structured receipt](actual-report.json) binds both changed runtime source files by SHA-256, against merged-main base `d772ea61f515ab0d8fe3e23bd00c2e7c315a635b`. It exercised real authenticated API views through Django's test client, actual model loaders and generation on this Mac. It is not browser/network transport evidence or a model-quality benchmark.

The Safetensors reference is the exact public Apache-2.0 SmolLM2-135M base revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`; all five fixed files were checksum-verified. The GGUF reference is the official llama.cpp conversion of the pinned SmolLM2-135M-Instruct snapshot documented in [TASK-74](../task74-cache-replacement-2026-10-23/report.md). Source model, converter and output hashes are retained there; this receipt verifies the actual imported GGUF bytes again. These two references have different weights/templates, so cross-format output equality is not asserted.

For each format, the real import API initially exposed `load_tested: false`. Two actual greedy eight-token requests produced identical decoded text and usage; the catalog then exposed `load_tested: true`. The model stayed in `draft`; successful loading does not establish task quality, hardware or production qualification. Safetensors used four prompt/eight completion tokens; GGUF used 36 prompt/eight completion tokens. Streamed content and the separate usage event exactly matched buffered execution.

Closing an active response unloaded the model, marked that request cancelled and released CPU admission. An oversized context was refused without leaving admission held. Actual stored weight bytes were temporarily corrupted in the disposable test artifact and restored in `finally`; generation refused the changed bytes. Revoking the real key after a stream's assistant-role event withheld all prefetched content, reported failure and unloaded the runtime. No original model cache, customer data or workspace database was modified.

Runtime versions are recorded in the receipt: Torch 2.13.0, Transformers 5.14.0, Safetensors 0.8.0, Tokenizers 0.22.2 and xllamacpp 2026.10.11549. This is bounded physical-Mac CPU execution. GPU and MLX execution remain separate gates, with no CPU fallback or support inference from these results.

## Regression evidence

After integrating the merged CPU training implementation, 60 focused workspace/import/project/device/GGUF/CPU-profile tests passed (one opt-in native-model skip). Before that documentation/source integration, the complete backend passed 1,052 tests (seven optional skips), including the final buffered-completion regression. The added cases withdraw a key, expire it, lower its role, archive the model, change tokenizer compatibility, withdraw an artifact or remove a cross-project grant after actual loading; they verify that content is withheld and the request fails. Another case verifies that an interleaved request cannot overwrite stream context. The full backend run also includes a real-generation wrapper that revokes the key during a buffered completion and checks that no choices are returned.

The focused regressions use a real tiny local Llama, with controlled withdrawal timing. The separate public 135M/GGUF receipt above supplies actual reference-model execution. Raw qualification scripts, logs and before-fix failure evidence are retained under private project evidence `takeover-2026-10-23/cpu-inference`. Model weights, databases and credentials remain outside Git.

A separate [actual training/inference integration receipt](trained-integration.json) verifies that this guarded API loads the exact pretrained CPU full-SFT and LoRA base/candidate artifacts produced by TASK-15 and generates decoded output. It retains the existing adapter/base compatibility and immutable checkpoint checks.
