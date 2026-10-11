# Accelerator inventory and diagnostics

TASK-36 adds a standalone worker-host tool, independent of Django and server
credentials. It checks the optional installed PyTorch runtime rather than treating
display adapters or `nvidia-smi` output as usable training capacity.

```sh
python -m modelanvil.accelerators
python -m modelanvil.accelerators --device cuda:0
python -m modelanvil.accelerators --device rocm:0
python -m modelanvil.accelerators --device xpu:0
python -m modelanvil.accelerators --device mps:0
```

Run with the worker's Python environment. Install a compatible, pinned PyTorch
build and vendor driver following the [official installation instructions](https://pytorch.org/get-started/locally/).
PyTorch is optional and is not added to the control-plane requirements. Missing
or broken runtimes return unavailable backends with corrective actions. Inventory
can initialize a device runtime to enumerate properties but does not allocate
model weights, training tensors or jobs. Selection errors return JSON and exit 2;
inventory without a selection exits 0 even when every backend is unavailable.

| Backend ID | Framework device | Detection |
| --- | --- | --- |
| `cuda:N` | `cuda:N` | Available CUDA build and visible devices |
| `rocm:N` | `cuda:N` | Available HIP build and visible AMD devices |
| `xpu:N` | `xpu:N` | Available Intel XPU runtime and visible devices |
| `mps:0` | `mps:0` | Available Apple Metal Performance Shaders runtime |

The [HIP runtime uses PyTorch's CUDA API](https://docs.pytorch.org/docs/2.14/notes/hip.html)
but the report preserves AMD/ROCm identity. [XPU](https://docs.pytorch.org/docs/2.14/notes/get_start_xpu.html)
and [MPS](https://docs.pytorch.org/docs/2.14/notes/mps.html) have their own availability checks.
Device indices refer to this process's visible devices, including any visibility
restrictions; they are not persistent hardware identifiers. UUID is included when
the framework exposes it. Driver versions and device-specific model support still
need a backend qualification report.

`total_memory_bytes` is the framework-reported device capacity, not free memory or
a reservation. Missing capacity is `null`. Apple unified memory is reported as
shared; its runtime-recommended memory budget is a separate field and is never
converted to dedicated VRAM. `--min-memory-bytes N` rejects insufficient or unknown
reported capacity, including MPS. This check cannot guarantee future allocation.

To run the bounded, opt-in FP32 diagnostic:

```sh
python -m modelanvil.accelerators --device mps:0 --diagnostic-steps 3
```

One through ten steps are permitted. The tool performs a 4×4 matrix forward pass,
backward pass and SGD update, checking finite tensors, device residency and changed
weights. It synchronizes the selected device and records measured losses and wall
seconds. Wall time includes initialization and is not a throughput benchmark.
No CPU fallback is selected. MPS diagnostics reject
`PYTORCH_ENABLE_MPS_FALLBACK=1` to prevent unsupported kernels running on CPU.
The report always retains `model_qualified: false` and
`production_qualified: false`, even when this primitive diagnostic passes.

This tool does not register workers, grant capacity, reserve devices or enable GPU
training in the browser. TASK-42 owns that integration and launch/claim revalidation.
TASK-37–TASK-40 own named-hardware training/inference qualification for the four
vendors. TASK-41 owns portable Vulkan inference; Vulkan, MLX, DirectML and other
vendor runtimes are not advertised by this PyTorch probe. TASK-17 owns multi-GPU
execution. Each model, operation, precision and adapter method requires its own
evidence; GPU detection does not qualify LoRA, QLoRA or mixed-vendor distribution.
