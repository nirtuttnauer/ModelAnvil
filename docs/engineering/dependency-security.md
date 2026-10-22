# Python dependency security status

TASK-74 audit snapshot: 23 October 2026. Base, production, documents, GPU and specialist requirements resolve without known `pip-audit` findings. This is a point-in-time dependency audit, not a security or hardware qualification.

The update pins DRF 3.18.3, pypdf 6.21.2, PyTorch 2.13.0, Transformers 5.14.0, Safetensors 0.8.0, PEFT 0.21.2, torchvision 0.28.0, Pillow 13.0.0 and certifi 2026.10.19 where those packages are used. Inference explicitly requires Requests 2.34.2 because model acquisition imports it directly; Hugging Face Hub 1.33.0 uses HTTPX and no longer supplies Requests transitively. Specialist and GPU environments have separate NumPy pins and should be installed separately.

The optional inference group still resolves `diskcache==5.6.3` through `llama-cpp-python==0.3.36`. [CVE-2025-69872](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v) covers unsafe pickle deserialization when an attacker can write the cache directory. The [upstream issue](https://github.com/grantjenks/python-diskcache/issues/362) has no released fix, and the audit reports no fixed version. No audit ignore was added. Keep TASK-74 open for this residual finding; do not describe the complete inference environment as clean. This update neither enables a disk cache nor changes its trust boundary.

Reproduce each group independently from the repository root (Python 3.12):

```sh
uvx --python 3.12 pip-audit -r requirements.txt
uvx --python 3.12 pip-audit -r requirements.production.txt
uvx --python 3.12 pip-audit -r requirements.documents.txt
uvx --python 3.12 pip-audit -r requirements.gpu.txt
uvx --python 3.12 pip-audit -r requirements.specialists.txt
uvx --python 3.12 pip-audit -r requirements.inference.txt
```

The last command is expected to fail while the DiskCache advisory remains unresolved. Refresh all groups when an upstream fix becomes available, verify compatible versions, rerun runtime tests and retain the unsuppressed audit output.

The PDF extraction provenance and training contract now use the new pins. Reinstall and re-register runners/workers before launching new jobs. Earlier registered contracts and unfinished jobs are not silently migrated. CPU tests cover actual adapter training, frozen base weights, local candidate reload, network refusal and exact optimizer recovery. Historical GPU qualification reports continue to describe their original environments; rerun hardware qualification for this stack before claiming equivalent GPU behavior. No CUDA, ROCm or XPU hardware was available for this update.
