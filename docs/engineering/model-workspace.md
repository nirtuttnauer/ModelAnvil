# Model acquisition and local chat

ModelAnvil now acquires immutable model snapshots, runs local text inference and streams actual responses in Chat. These capabilities are independently implemented in ModelAnvil.

## Start locally

Install the existing application requirements, then the optional runtime in the same API and worker environment:

```sh
.venv/bin/pip install -r requirements.inference.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_model_import --tenant-id TENANT_UUID --run
```

Keep that dedicated import worker running. In Models, search Hugging Face, inspect a pinned 40-character commit, review its license and select the import pool. Downloads retain partial bytes, resume with HTTP Range and verify each file before registering a draft version. Cancellation and worker lease expiry prevent candidate publication. Reconciliation can retry an interrupted worker attempt; repeat the same import key to retrieve an existing import.

Local imports accept selected Safetensors weights plus config/tokenizer files, or one GGUF file. Select MLX for compatible Apple Silicon snapshots. Uploads become project-scoped committed artifacts; the server computes hashes and rechecks bytes before loading. Files never supply arbitrary server paths or executable model code. Each snapshot is limited to 64 files and 8 GiB, with an 8 MiB limit for auxiliary files.

Private/gated access uses operator-managed `MODELANVIL_HUB_TOKENS`, a JSON object keyed by `TENANT_UUID:PROJECT_UUID`. Put the secret in the service environment; do not send it in browser imports or commit it to source. The client ignores ambient Hugging Face credentials. Access permission and license acceptance remain the operator/user's responsibility.

## Chat and API

Chat offers an explicit device, bounded generation controls, system prompt, imported template or fixed ChatML override, cancellation, regeneration, JSON export and project-scoped saved conversations. The arena runs two models sequentially on the same input; each has an explicit device. It reports actual input/output tokens and elapsed time including loading. Completed imported or trained transformer candidates can be selected. Saved comparisons retain both actual outputs, exact input and inference references; generation settings must match except for device. External providers remain pending.

`POST /api/v1/chat-comparisons/` verifies each output against the completed inference record’s digest and requires the creating principal’s accessible requests. Retrying the same pair, even in reversed input order, returns its original comparison. A stable randomized A/B assignment hides identities in the comparison response until an engineer records A, B, tie or neither at `/api/v1/chat-comparisons/COMPARISON_UUID/vote/`. The same-voter exact retry is idempotent; changing an existing vote fails with a conflict. The browser saves comparisons, reopens them with conversations and exports their recorded preferences. This is an informal arena preference: the generating user chose the models and saw sequential generation, so it is not a formally blinded held-out review or release qualification. Independent annotation review and training-data snapshot publication remain pending.

The compatible endpoints are `GET /api/v1/inference/models` and `POST /api/v1/inference/chat/completions`. Use a project-scoped API key and, for a tenant-wide key, an accessible `X-Project-ID`. The model identifier is the imported or completed transformer candidate version UUID. The body accepts `model`, text `messages`, `max_tokens` (1–256), `temperature` (0–2), `seed`, `stream` and `stream_options.include_usage`. ModelAnvil extensions are `device` (`cpu`, `mps:0`, `mlx:0`) and `prompt_format` (`model`, `plain`, `chatml`). Unknown options fail explicitly.

```sh
curl --fail http://127.0.0.1:8000/api/v1/inference/chat/completions \
  -H "Authorization: Bearer $MODELANVIL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"MODEL_VERSION_UUID","messages":[{"role":"user","content":"Once upon a time"}],"max_tokens":12,"device":"cpu","stream":true,"stream_options":{"include_usage":true}}'
```

Streaming sends standard completion chunks, optional measured usage and `[DONE]`. The runtime unloads and releases its process slot before `[DONE]`; disconnect also closes it. A never-consumed response releases its model on close. Completed usage is recorded once per request with input/output digests; raw prompts are not stored in the inference ledger. Saving a conversation explicitly stores its messages. A retried HTTP completion creates a new request and may generate/charge usage again; HTTP replay idempotency is pending.

Safetensors inference supports bounded Llama, Qwen2, Mistral, Gemma and GPT-2 models, loads at most 300 million parameters/1 GiB of weights in FP32, verifies complete finite weights and checks GPU capacity before allocation. Context is limited to the model capacity or 2,048 tokens, whichever is smaller; overflow fails without truncation. MLX supports compatible Llama/Qwen2/Mistral/Gemma snapshots on `mlx:0` with recommended memory headroom checks. GGUF uses llama.cpp on CPU; GPU GGUF requires a qualified build and is deliberately unavailable here. Base models without a chat template accept a single raw user prompt.

Admission currently allows one model per API process. Multiple API processes and training workers do not share a device reservation yet (TASK-42). Run a single inference API process with isolated compute until shared admission is implemented. The local Django development server is for loopback use; authenticated TLS deployment and verification from a second machine remain pending. Completed ModelAnvil LoRA candidates use a verified local-base loader; arbitrary imported adapters and quantized Safetensors remain unsupported. Imported versions stay draft; a successful completion records load evidence, not production qualification.

## Evidence and reproduction

The Mac pilot imported the pinned SmolLM2-135M snapshot through the worker after priming 1 MiB of partial weights. CPU PyTorch, MPS, MLX and a real F16 GGUF conversion produced the same 12-token greedy completion. The browser streamed a CPU/MLX pair and saved the conversation. See [recorded evidence](verification/model-workspace-mac-2026-10-11.json).

```sh
.venv/bin/python scripts/qualify_model_workspace.py \
  --output /private/tmp/modelanvil-workspace-new-pilot --mlx \
  --resume-source /absolute/path/to/pinned-Smollm2-snapshot \
  --gguf /absolute/path/to/converted-model.gguf
```

The output directory must be new; the command creates its own database and artifacts. GGUF conversion must use an architecture-compatible llama.cpp converter and retains source provenance in the separate conversion record. Automated API tests additionally exercise real tiny transformer weights, corrupt bytes, scoped access, upload references, lease fencing, exact streamed/framework output and immediate arena handoff. NVIDIA, AMD and Intel qualification remain pending; this pilot covers only this Mac and this bounded model.
