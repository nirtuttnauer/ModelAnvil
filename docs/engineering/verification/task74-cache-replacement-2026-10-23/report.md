# TASK-74: remove the DiskCache dependency

23 October 2026 · Explicit human authorization to replace the cache dependency and continue CPU-first implementation, with hardware/customer qualification separate and history rewriting held.

## Delivered change

`requirements.inference.txt` replaces `llama-cpp-python==0.3.36` with `xllamacpp==2026.10.11549`. The old binding required DiskCache even when the application did not enable it. The new binding has no mandatory Python dependencies. It retains llama.cpp GGUF execution through a bounded adapter instead of importing or suppressing the vulnerable package. No audit ignore, installed-package monkeypatch, fake dependency version or pickle cache is introduced.

The [upstream binding API](https://github.com/xorbitsai/xllamacpp) and [native server API](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) supply actual template rendering, tokenization, streaming and measured counters. ModelAnvil retains project/tenant access, exact verified artifact staging and the existing inference/device leases before constructing the engine.

The adapter uses one CPU generation thread/slot, no GPU/operator/KV offload, at most 1 GiB of weights and 2,048 context tokens. Prompt/disk cache paths are empty; idle/prompt/RAM caches are disabled. Its private ephemeral `127.0.0.1` listener requires a freshly generated bearer key, inherits no HTTP proxy configuration and accepts no redirects. Model loading/generation downloads nothing. The key, listener and model are scoped to that session and disappear on unload. User-facing APIs retain the existing authority boundary and never expose the native URL or key.

Native template rendering and tokenization reserve the requested output before generation; overflow is refused without truncation. Stream closure stops native generation, waits for idle and reads actual generated-token counters. Cancellation can compute more tokens than reach the consumer: in the saved reference, one delivered token corresponded to three computed tokens. Accounting records three. Normal streaming, already-cancelled requests and generator-disconnect cleanup are separately checked.

## Actual bounded reference

[Actual output/usage receipt](actual-gguf.json): public Apache-2.0 `HuggingFaceTB/SmolLM2-135M-Instruct`, revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`, using the existing seven verified decoder files. The official llama.cpp converter at commit `f5027fb21307eb264aed483242603d68c87b0fe3` produced the locally hashed FP16 GGUF. Model bytes, conversion state, databases and caches remain outside Git.

Actual CPU results on this Mac: two same-seed runs produced the same decoded eight-token output; prompt usage was 38 tokens and completion usage eight. Cancellation stopped before the 64-token reserve; context overflow was refused; closing the generator left no active native request; anonymous access to native completion returned 401; unloading closed the listener. These are execution/lifecycle checks, with no assertion of arithmetic correctness, customer quality, GPU support or production readiness.

Reproduce with a locally verified/licensed GGUF and updated inference environment:

```sh
MODELANVIL_GGUF_TEST_MODEL=/absolute/path/to/verified.gguf python manage.py test modelanvil.runners.test_gguf_runtime --noinput
```

## Validation

[Fresh independent group audits](audits.json) contain zero reported vulnerabilities and no ignores for base, production, documents, GPU, specialists and inference. The inference graph contains 45 packages, with `xllamacpp` present and both `diskcache` and `llama-cpp-python` absent. Audit results are dated dependency observations; native model/runtime and hardware behavior have their own evidence.

Local backend: 1,046 tests passed with six optional skips before the final additional weight-admission guard and metadata-error normalization. Final affected/native suite: 37 passed, including the actual GGUF run, admission/accounting/cancellation/disconnect regressions and existing model-workspace/local-ML API checks. Generated README consistency and `git diff --check` pass. The final PR must pass all six current backend/frontend/pgvector push/PR checks before merge; its final head/merge receipts are recorded in Aftur.

The original dependency upgrade delivery remains PR19; this separately authorized cache follow-up closes its residual finding. Existing optional environments should be recreated so removed packages do not linger. GPU/MLX/vendor qualification, customer-dependent work and history rewriting retain their separate gates. Original worktrees, data and history are preserved.
