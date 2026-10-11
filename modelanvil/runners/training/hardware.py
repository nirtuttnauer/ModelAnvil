"""Measured host and runtime inventory for training capability reporting.

TASK-13 requires a reproducible hardware/runtime report that matches the exact
tested scope. Host measurements use the standard library; accelerator detection
uses an optional tensor framework. It reports what it actually observed and refuses to describe a capability
it could not observe:

- ``graphics_devices`` lists display/graphics adapters seen by the operating
  system. They are *not* training accelerators.
- ``accelerators`` lists devices usable by a tensor framework. An adapter only
  appears here when a supported backend (CUDA, ROCm, MPS, XPU) is present, so an
  graphics adapter alone is never reported as training capacity.
- Every report carries ``production_qualified: false`` and
  ``hardware_qualified: false``; nothing here qualifies a model or a release.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ACCELERATOR_BACKENDS = ("cuda", "rocm", "mps", "xpu")
_UNAVAILABLE = "unavailable"


def _first_line(path: str) -> Optional[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    text = text.strip()
    return text or None


def cpu_brand() -> Optional[str]:
    if sys.platform == "darwin":
        result = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                capture_output=True, text=True, check=False)
        return result.stdout.strip() or None
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    match = re.search(r"^model name\s*:\s*(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return platform.processor() or None


def logical_cores() -> Optional[int]:
    return os.cpu_count()


def physical_cores() -> Optional[int]:
    if sys.platform == "darwin":
        for name in ("hw.physicalcpu", "hw.physicalcpu_max"):
            result = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, check=False)
            try:
                return int(result.stdout.strip())
            except ValueError:
                continue
        return None
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    ids = set(re.findall(r"^core id\s*:\s*(\d+)$", text, re.MULTILINE))
    return len(ids) or None


def total_memory_bytes() -> Optional[int]:
    if sys.platform == "darwin":
        result = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                capture_output=True, text=True, check=False)
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^MemTotal:\s+(\d+)\s*kB$", text, re.MULTILINE)
    return int(match.group(1)) * 1024 if match else None


def graphics_devices() -> list[dict[str, Any]]:
    """Graphics adapters reported by the operating system."""
    if sys.platform == "darwin" and shutil.which("system_profiler"):
        output = subprocess.run(["system_profiler", "-json", "SPDisplaysDataType"],
                                capture_output=True, text=True, check=False).stdout
        try:
            entries = json.loads(output).get("SPDisplaysDataType", [])
        except (ValueError, AttributeError):
            return []
        devices = []
        for entry in entries:
            devices.append({
                "name": entry.get("sppci_model") or entry.get("_name"),
                "vendor": entry.get("spdisplays_vendor"),
                "cores": entry.get("sppci_cores"),
                "metal": entry.get("spdisplays_metal"),
                "source": "system_profiler:SPDisplaysDataType",
            })
        return devices
    if sys.platform.startswith("linux"):
        devices = []
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
            vendor = _first_line(str(card / "device" / "vendor"))
            name = None
            uevent = None
            try:
                uevent = (card / "device" / "uevent").read_text(encoding="utf-8", errors="replace")
            except OSError:
                uevent = None
            if uevent:
                match = re.search(r"^DRIVER=(.*)$", uevent, re.MULTILINE)
                name = match.group(1).strip() if match else None
            if vendor or name:
                devices.append({"name": name, "vendor": vendor, "cores": None,
                                "metal": None, "source": "/sys/class/drm"})
        return devices
    return []


def accelerators() -> tuple[list[dict[str, Any]], str]:
    """Framework-visible GPU devices; availability does not qualify training."""
    from modelanvil.accelerators import inventory
    report = inventory()
    devices = [device for entry in report['backends'].values()
               if entry['status'] == 'available' for device in entry['devices']]
    reason = (f"Detected {len(devices)} framework-visible GPU device(s); model qualification is separate."
              if devices else "No available framework GPU backend; graphics adapters are not training capacity. Install a compatible runtime and driver.")
    return devices, reason


def dependency_inventory() -> list[dict[str, Any]]:
    """Pinned repository requirements against what is actually installed here."""
    import importlib.metadata

    requirements = Path(__file__).resolve().parents[3] / "requirements.txt"
    if not requirements.exists():
        return []
    inventory = []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, pinned = line.split("==", 1)
        distribution = name.split("[", 1)[0].split(";", 1)[0].strip()
        try:
            installed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        inventory.append({
            "requirement": distribution,
            "pinned_version": pinned.strip(),
            "installed_version": installed,
            "matches_pin": installed == pinned.strip(),
        })
    return inventory


def runtime_inventory() -> list[dict[str, Any]]:
    """Registered training runtime contracts, their digests and declared envelope."""
    from modelanvil.runners.training import registry

    entries = []
    for module in registry.runtime_modules():
        manifest = module.runner_manifest()
        resources = manifest.get("resources", {})
        entries.append({
            "runtime_id": module.RUNTIME_ID,
            "contract_digest": module.CONTRACT_DIGEST,
            "build_digest": module.build_digest(),
            "declared_gpu_count": resources.get("gpu_count"),
            "declared_distributed": resources.get("distributed"),
            "declared_memory_bytes": resources.get("memory_bytes"),
            "declared_cpu_cores": resources.get("cpu_cores"),
            "optimizer": module.CONTRACT.get("optimizer"),
            "tokenizer": module.CONTRACT.get("tokenizer"),
            "limitations": manifest.get("limitations", []),
        })
    return entries


def host_report() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "system": platform.system(),
        "release": platform.release(),
        "cpu_brand": cpu_brand(),
        "logical_cores": logical_cores(),
        "physical_cores": physical_cores(),
        "total_memory_bytes": total_memory_bytes(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "compiler": platform.python_compiler(),
            "executable": sys.executable,
        },
    }


def hardware_report() -> dict[str, Any]:
    """Reproducible measurement of this host and the runtimes installed on it."""
    devices, reason = accelerators()
    return {
        "report_version": "1.0",
        "host": host_report(),
        "accelerator_backends_checked": list(ACCELERATOR_BACKENDS),
        "accelerators": devices,
        "accelerator_status": "available" if devices else _UNAVAILABLE,
        "accelerator_reason": reason,
        "graphics_devices": graphics_devices(),
        "graphics_devices_are_training_capacity": False,
        "dependencies": dependency_inventory(),
        "runtimes": runtime_inventory(),
        "production_qualified": False,
        "hardware_qualified": False,
        "scope_note": ("Measured on the current host; GPU detection uses the optional tensor framework. This report "
                       "describes framework-visible devices; it does not qualify any model, checkpoint or release."),
    }
