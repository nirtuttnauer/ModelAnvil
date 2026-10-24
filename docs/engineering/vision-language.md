# Bounded vision-language training and chat

The supported source is Apache-2.0 `HuggingFaceTB/SmolVLM-256M-Instruct`, revision `7e3e67edbbed1bf9888184d9df282b700a323964`. Its twelve exact model, tokenizer, chat-template and processor files are pinned in `vlm_math.py`. Other models and media formats require their own execution and qualification evidence.

Install `requirements.vision.txt` in the API and worker environments. Use a host with at least 16 GiB of known memory, shared local artifact storage and a dedicated single-slot worker. Choose explicit `cpu` or `mps:0`; MPS requires an available Apple GPU, process memory headroom and disabled CPU fallback. The two devices have separate runtime contracts. This profile does not download models or use remote inference services.

Upload images through `POST /api/v1/inference/models/upload-image/` (multipart `file`). Admission verifies actual image bytes before storage: one PNG/JPEG frame, at most 2 MiB, dimensions at most 1024 by 1024, decoded with EXIF transpose and RGB conversion. It returns the committed project-scoped artifact UUID, SHA-256 and decoded dimensions. Artifact access, current bytes and deletion tombstones are rechecked during training and generation. Remote URLs, paths, video, GIF and PDF are unsupported by this training profile.

Prepare 3–32 canonical sample envelopes. Each row has exactly three blocks: a user image with `asset_ref: "artifact:UUID"`, a user text question (up to 512 characters), and an assistant text answer (up to 256 characters). Retain the real `source_group_id` and paired source provenance. Optional declared image SHA and MIME must match the committed image. Published train, validation and test splits must all be nonempty; source groups and identical image hashes cannot cross splits. Use representative independent groups; renaming duplicates does not create independent examples.

Register verified local snapshot files and paired JSONL:

```sh
python manage.py setup_vlm_training --tenant-id UUID --project-id UUID \
  --name visual-experiment --model-dir /absolute/smolvlm-snapshot \
  --samples /absolute/paired-samples.jsonl --device cpu --steps 3
```

The command prints the normal training-launch payload, worker ID and source/device observation. It publishes the dataset, exact processor/tokenizer, base, runner, pool and lifetime `training_steps` budget; it does not launch training. Use Training → Configure → Advanced, select LoRA and these matching resources, review the encoded preflight, then queue. Selecting the vision base sets a three-step custom plan. Run the registered worker through the existing `run_worker` command with `modelanvil.runners.training.executor.training_worker_executor` as executor.

Numerical scope is FP32 rank-eight q/v LoRA on the text decoder: 460,800 trainable parameters, frozen vision encoder/connector/base, AdamW at 0.00002, clipping at 1, initialization seed 42 and 1–20 updates. The pinned PIL Idefics3 processor disables image splitting and uses one 512px tile / 64 image tokens. Combined sequences fit within 128 tokens without truncation; labels cover only the native assistant response, including its end marker. Validation reports assistant-token-weighted loss.

Each committed update stores real loss, gradient/change counts, image SHA, CPU/wall measurements, device residency and available process memory observations. Checkpoints pin the base, processor, image assets, sample order, adapter and Adam moments. Automatic lease retry reloads the latest fenced checkpoint; stale attempts cannot publish. Cancellation discards unpublished updates. Accounting uses committed optimizer updates, including when an uncommitted update ran before cancellation or lease loss; it does not claim to meter elapsed compute. Terminal self-service recovery remains limited to the existing CPU reference runtimes.

A fixed offline CPU subprocess independently loads base and candidate with their exact processors and protected image hashes. It compares visual exact-match and assistant response likelihood against the frozen base. A failed or unavailable check remains explicit; all outputs remain draft with `production_qualified=false`. Authored color fixtures demonstrate mechanics, not customer quality or general visual understanding. Native ZIP download contains base, adapter, processor, tokenizer, license and provenance. The complete snapshot exceeds the existing 256 MiB browser-memory fallback: use a browser with native disk-stream saving (Chrome/Edge) or stream the authenticated download API to disk. The fallback refuses oversized transfers instead of buffering the model in memory. `scripts/vlm_candidate_infer.py` loads that snapshot without Django or ModelAnvil imports.

Chat lists verified vision bases and successful candidates. Attach a supported image, ask one visual question and generate greedily with native formatting and 1–16 output tokens within the 128-token context. Each question uses the attached image; earlier turns are retained for display, while generation receives the current question. System prompts, template overrides, image comparisons and external image providers are not supported. Current processor, image, model and project access are checked before output and replay. Switching images after a saved response requires a new conversation. Saved conversations retain an artifact reference, never raw image bytes in browser storage.

Named Apple GPU execution and CPU execution qualify only the measured operation/device envelope. Other accelerator vendors, larger models, quantized or full-model vision training, customer quality and production release keep their separate gates.
