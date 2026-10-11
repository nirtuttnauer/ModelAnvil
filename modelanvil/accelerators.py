"""Optional PyTorch GPU inventory and bounded diagnostics, independent of Django.

Run ``python -m modelanvil.accelerators`` on the worker host. Availability and
primitive diagnostics do not qualify a model or authorize worker capacity.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import re
import time


BACKENDS = {"cuda": "NVIDIA", "rocm": "AMD", "xpu": "Intel", "mps": "Apple"}


class AcceleratorError(ValueError):
    pass


def _load_torch():
    return importlib.import_module("torch")


def _positive_bytes(value):
    return value if type(value) is int and value > 0 else None


def inventory():
    """Inspect the installed framework's visible devices; never allocate tensors."""
    report = {
        "schema_version": 1,
        "host": {"system": platform.system(), "machine": platform.machine(),
                 "release": platform.release()},
        "framework": {"name": "torch", "version": None, "cuda_version": None,
                      "hip_version": None},
        "backends": {},
        "model_qualified": False,
        "production_qualified": False,
    }
    for backend, vendor in BACKENDS.items():
        report["backends"][backend] = {
            "vendor": vendor, "status": "unavailable", "devices": [],
            "reason": "Install a compatible PyTorch build and vendor driver on the worker host.",
        }
    try:
        torch = _load_torch()
    except Exception as exc:
        for entry in report["backends"].values():
            entry["reason"] = (f"PyTorch could not be imported ({type(exc).__name__}). "
                               "Install a compatible worker runtime; driver detection alone is insufficient.")
        return report

    version = getattr(torch, "version", None)
    hip = getattr(version, "hip", None)
    cuda = getattr(version, "cuda", None)
    report["framework"].update(version=str(getattr(torch, "__version__", "unknown")),
                               cuda_version=cuda, hip_version=hip)
    for backend, entry in report["backends"].items():
        try:
            if backend in {"cuda", "rocm"}:
                # PyTorch exposes AMD HIP devices through the cuda namespace.
                if backend != ("rocm" if hip else "cuda") or not (hip or cuda):
                    entry["reason"] = f"Installed PyTorch was not built for {backend}; install the matching runtime."
                    continue
                api = getattr(torch, "cuda", None)
            elif backend == "mps":
                api = getattr(getattr(torch, "backends", None), "mps", None)
            else:
                api = getattr(torch, "xpu", None)
            if api is None or not api.is_available():
                entry["reason"] = (f"PyTorch reports {backend} unavailable. Check the compatible "
                                   "runtime, OS, driver, device permissions and visibility settings.")
                continue
            if backend == "mps":
                device = {"id": "mps:0", "backend": "mps", "torch_device": "mps:0",
                          "name": "Metal Performance Shaders device", "vendor": entry["vendor"],
                          "total_memory_bytes": None, "memory_scope": "shared_unified",
                          "runtime_recommended_memory_bytes": None}
                recommended = getattr(getattr(torch, "mps", None), "recommended_max_memory", None)
                if recommended:
                    try:
                        device["runtime_recommended_memory_bytes"] = _positive_bytes(recommended())
                    except Exception:
                        pass  # Unknown capacity must not be promoted to a measured limit.
                entry["devices"].append(device)
            else:
                devices = []
                for index in range(api.device_count()):
                    props = api.get_device_properties(index)
                    device = {"id": f"{backend}:{index}", "backend": backend,
                              "torch_device": f"{'cuda' if backend == 'rocm' else backend}:{index}",
                              "name": str(props.name), "vendor": entry["vendor"],
                              "total_memory_bytes": _positive_bytes(getattr(props, "total_memory", None)),
                              "memory_scope": "device_reported",
                              "uuid": str(props.uuid) if getattr(props, "uuid", None) is not None else None}
                    devices.append(device)
                # An incomplete enumeration cannot authorize selecting another device.
                entry["devices"] = devices
            entry["status"] = "available" if entry["devices"] else "unavailable"
            entry["reason"] = ("Framework-visible devices; model and operation qualification is still required."
                               if entry["devices"] else "No visible devices. Check driver and visibility settings.")
        except Exception as exc:
            entry.update(status="error", devices=[],
                         reason=f"{backend} inventory failed ({type(exc).__name__}). Repair the driver/runtime before selection.")
    return report


def select_device(report, selector, *, min_memory_bytes=0):
    """Resolve an explicit device in this process's visibility namespace."""
    if type(min_memory_bytes) is not int or min_memory_bytes < 0:
        raise AcceleratorError("Required memory must be a nonnegative integer number of bytes.")
    if not isinstance(selector, str) or not re.fullmatch(r"(?:cuda|rocm|xpu):(?:0|[1-9][0-9]*)|mps(?::0)?", selector):
        raise AcceleratorError("Select cuda:N, rocm:N, xpu:N or mps:0 explicitly; CPU fallback is disabled.")
    selector = "mps:0" if selector == "mps" else selector
    backend = selector.split(":")[0]
    entry = report["backends"][backend]
    if entry["status"] != "available":
        raise AcceleratorError(entry["reason"])
    device = next((item for item in entry["devices"] if item["id"] == selector), None)
    if device is None:
        raise AcceleratorError(f"{selector} is not visible. Select a listed device; indices are process-local.")
    capacity = device["total_memory_bytes"]
    if min_memory_bytes and (capacity is None or capacity < min_memory_bytes):
        raise AcceleratorError("Requested device memory is unknown or insufficient. Reduce the requirement or use a measured device.")
    return dict(device)


def diagnose(selector, *, steps=3):
    """Run a tiny FP32 optimizer check on freshly selected hardware, with no fallback."""
    if type(steps) is not int or not 1 <= steps <= 10:
        raise AcceleratorError("Diagnostic steps must be an integer from 1 through 10.")
    report = inventory()
    device = select_device(report, selector)
    if device["backend"] == "mps" and os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1":
        raise AcceleratorError("Unset PYTORCH_ENABLE_MPS_FALLBACK before GPU diagnostics to prevent CPU kernel fallback.")
    started = time.perf_counter()
    try:
        torch = _load_torch()
        expected = torch.device(device["torch_device"])
        api = getattr(torch, "cuda" if device["backend"] == "rocm" else device["backend"])
        weights = torch.nn.Parameter(torch.ones((4, 4), device=expected, dtype=torch.float32))
        inputs = torch.ones((4, 4), device=expected, dtype=torch.float32)
        before = weights.detach().clone()
        optimizer = torch.optim.SGD([weights], lr=0.01)
        losses = []
        for _ in range(steps):
            optimizer.zero_grad()
            output = inputs @ weights
            loss = output.square().mean()
            loss.backward()
            for tensor in (inputs, weights, output, loss, weights.grad):
                if tensor is None or tensor.device != expected or not torch.isfinite(tensor).all().item():
                    raise AcceleratorError("Diagnostic produced non-finite values or left the selected GPU.")
            optimizer.step()
            losses.append(float(loss.detach().item()))
        if device["backend"] == "mps":
            api.synchronize()
        else:
            api.synchronize(expected)
        if not torch.isfinite(weights).all().item() or torch.equal(before, weights.detach()):
            raise AcceleratorError("Optimizer did not change the device weights.")
    except AcceleratorError:
        raise
    except Exception as exc:
        raise AcceleratorError(f"GPU diagnostic failed ({type(exc).__name__}); check runtime, driver and supported operations.") from exc
    return {"device": device, "framework": report["framework"], "host": report["host"],
            "operation": "fp32_matrix_forward_backward_sgd", "steps": steps,
            "losses": losses, "wall_seconds": time.perf_counter() - started,
            "weights_changed": True, "device_residency_checked": True,
            "model_qualified": False, "production_qualified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="Explicit cuda:N, rocm:N, xpu:N or mps:0")
    parser.add_argument("--min-memory-bytes", type=int, default=0)
    parser.add_argument("--diagnostic-steps", type=int, default=0, help="Opt-in FP32 check (1–10 steps)")
    args = parser.parse_args(argv)
    try:
        if args.min_memory_bytes < 0 or not 0 <= args.diagnostic_steps <= 10:
            raise AcceleratorError("Memory must be nonnegative; diagnostic steps must be from 0 through 10.")
        if not args.device and (args.min_memory_bytes or args.diagnostic_steps):
            raise AcceleratorError("Select --device before requesting memory checks or diagnostics.")
        report = inventory()
        if args.device:
            report["selected_device"] = select_device(report, args.device, min_memory_bytes=args.min_memory_bytes)
        if args.diagnostic_steps:
            report["diagnostic"] = diagnose(args.device, steps=args.diagnostic_steps)
        print(json.dumps(report, indent=2))
        return 0
    except AcceleratorError as exc:
        print(json.dumps({"error": str(exc), "production_qualified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
