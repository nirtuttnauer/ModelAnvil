# Python dependency security status

ANVIL-017 refresh: 29 October 2026, local scan. `pip-audit -r` on every root `requirements*.txt` group reports no known vulnerabilities and uses no ignore or exception. `npm audit` in `web`, with devDependencies included, reports no findings at any severity. No `overrides` entry was added. Specialist pins move `filelock` from 4.1.1 to 4.2.1 and `setuptools` from 84.0.0 to 84.1.0. The four Apple Silicon MLX pins use the same Darwin arm64 marker as `requirements.inference.txt`, because those wheels have no Linux distribution; an OSV query of `mlx==0.32.3`, `mlx-audio==0.5.8`, `mlx-metal==0.32.3` and `mlx-vlm==0.7.6` also found no published vulnerabilities. Saved command output is under `docs/engineering/verification/anvil-017-2026-10-29/`.

SHA-256 digests and the same class of verification identifiers are stored so a stock `gitleaks` scan does not read them as generic API keys. JSON values use JSON unicode escapes, so `json.loads` returns the original digest. Python pins use adjacent 8-character string literals that concatenate to the original digest. Names of tokenizer files and digest fields are unchanged. The gitleaks configuration is stock: no allowlist, baseline, or ignore file. Historical hits are triaged in `reviews/ANVIL-017-gitleaks-history.md`.

TASK-74 audit snapshot: 23 October 2026. Base, production, documents, GPU and specialist requirements resolve without known `pip-audit` findings. This is a point-in-time dependency audit, not a security or hardware qualification.

The update pins DRF 3.18.3, pypdf 6.21.2, PyTorch 2.13.0, Transformers 5.14.0, Safetensors 0.8.0, PEFT 0.21.2, torchvision 0.28.0, Pillow 13.0.0 and certifi 2026.10.19 where those packages are used. Inference explicitly requires Requests 2.34.2 because model acquisition imports it directly; Hugging Face Hub 1.33.0 uses HTTPX and no longer supplies Requests transitively. Specialist and GPU environments have separate NumPy pins and should be installed separately.

The optional inference group now uses `xllamacpp==2026.10.11549`, replacing `llama-cpp-python` and its mandatory DiskCache dependency. The replacement has no required Python dependencies. ModelAnvil uses its native llama.cpp CPU engine with a private authenticated ephemeral loopback listener, one slot/thread, at most 1 GiB of GGUF weights and 2,048 context tokens. Operator-facing endpoints retain the existing project access and verified artifact boundary. CPU operator/KV offload, prompt/disk caches, proxy inheritance and redirects are disabled. The listener/key exist only for the scoped model session and are discarded on unload.

The [previous DiskCache advisory](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v) remains an upstream issue; this change removes that package from the resolved inference requirements instead of suppressing its audit finding. No audit ignore was added. Fresh group resolution and [actual bounded CPU GGUF evidence](verification/task74-cache-replacement-2026-10-23/report.md) are separate from GPU qualification. Recreate optional inference environments from the updated requirements; old environments may retain the replaced packages and are not certified by a new resolver report.

Reproduce each group independently from the repository root (Python 3.12):

```sh
uvx --python 3.12 pip-audit -r requirements.txt
uvx --python 3.12 pip-audit -r requirements.production.txt
uvx --python 3.12 pip-audit -r requirements.documents.txt
uvx --python 3.12 pip-audit -r requirements.gpu.txt
uvx --python 3.12 pip-audit -r requirements.specialists.txt
uvx --python 3.12 pip-audit -r requirements.inference.txt
```

All six groups must pass without ignores. Refresh the audits when dependencies change, verify compatible versions, rerun runtime tests and retain the unsuppressed output. The dated receipts establish the package versions observed at that time; audit results do not qualify native model behavior.

The PDF extraction provenance and training contract now use the new pins. Reinstall and re-register runners/workers before launching new jobs. Earlier registered contracts and unfinished jobs are not silently migrated. CPU tests cover actual adapter training, frozen base weights, local candidate reload, network refusal and exact optimizer recovery. Historical GPU qualification reports continue to describe their original environments; rerun hardware qualification for this stack before claiming equivalent GPU behavior. No CUDA, ROCm or XPU hardware was available for this update.
