"""Backend fixtures test detection policy; they are not hardware qualification."""
import contextlib
import io
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from modelanvil import accelerators as gpu


def framework(*, cuda=None, hip=None, available=True, mps=False, xpu=False):
    def api(enabled):
        return NS(is_available=lambda: enabled,
                  device_count=lambda: 2,
                  get_device_properties=lambda index: NS(name=f"GPU {index}",
                                                         total_memory=8 * 1024 ** 3, uuid=f"gpu-{index}"))
    return NS(__version__="test-runtime", version=NS(cuda=cuda, hip=hip),
              cuda=api(available), xpu=api(xpu), backends=NS(mps=api(mps)),
              mps=NS(recommended_max_memory=lambda: 12 * 1024 ** 3))


class AcceleratorInventoryTests(unittest.TestCase):
    def probe(self, torch):
        with patch.object(gpu, "_load_torch", return_value=torch):
            return gpu.inventory()

    def test_missing_or_broken_framework_never_advertises_capacity(self):
        for exc in (ModuleNotFoundError("torch"), OSError("driver load failed")):
            with self.subTest(exc=type(exc).__name__), patch.object(gpu, "_load_torch", side_effect=exc):
                report = gpu.inventory()
            self.assertFalse(report["production_qualified"])
            for entry in report["backends"].values():
                self.assertEqual(entry["status"], "unavailable")
                self.assertEqual(entry["devices"], [])
                self.assertIn("Install", entry["reason"])

    def test_cpu_build_does_not_invent_cuda_from_driver_inventory(self):
        report = self.probe(framework(available=False))
        self.assertTrue(all(e["status"] == "unavailable" for e in report["backends"].values()))

    def test_cuda_enumerates_visible_devices_and_identity(self):
        report = self.probe(framework(cuda="12.8"))
        device = gpu.select_device(report, "cuda:1", min_memory_bytes=1024)
        self.assertEqual(device["torch_device"], "cuda:1")
        self.assertEqual(device["uuid"], "gpu-1")
        self.assertEqual(device["total_memory_bytes"], 8 * 1024 ** 3)
        self.assertEqual(report["framework"]["cuda_version"], "12.8")
        self.assertEqual(report["backends"]["rocm"]["status"], "unavailable")

    def test_rocm_retains_amd_identity_in_cuda_namespace(self):
        report = self.probe(framework(hip="6.4"))
        device = gpu.select_device(report, "rocm:0")
        self.assertEqual(device["vendor"], "AMD")
        self.assertEqual(device["torch_device"], "cuda:0")
        with self.assertRaises(gpu.AcceleratorError):
            gpu.select_device(report, "cuda:0")

    def test_xpu_does_not_require_cuda_runtime(self):
        report = self.probe(framework(available=False, xpu=True))
        self.assertEqual(gpu.select_device(report, "xpu:1")["vendor"], "Intel")

    def test_mps_unified_memory_is_not_dedicated_vram(self):
        report = self.probe(framework(available=False, mps=True))
        device = gpu.select_device(report, "mps")
        self.assertEqual(device["torch_device"], "mps:0")
        self.assertIsNone(device["total_memory_bytes"])
        self.assertEqual(device["memory_scope"], "shared_unified")
        self.assertEqual(device["runtime_recommended_memory_bytes"], 12 * 1024 ** 3)
        with self.assertRaisesRegex(gpu.AcceleratorError, "unknown"):
            gpu.select_device(report, "mps:0", min_memory_bytes=1)

    def test_missing_optional_namespaces_and_memory_are_unknown(self):
        torch = framework(cuda="12.8")
        del torch.xpu
        torch.cuda.get_device_properties = lambda index: NS(name="GPU")
        report = self.probe(torch)
        self.assertEqual(report["backends"]["xpu"]["status"], "unavailable")
        self.assertIsNone(gpu.select_device(report, "cuda:0")["total_memory_bytes"])

    def test_partial_enumeration_error_rejects_entire_backend(self):
        torch = framework(cuda="12.8", xpu=True)
        def props(index):
            if index:
                raise RuntimeError("device vanished")
            return NS(name="GPU", total_memory=1024)
        torch.cuda.get_device_properties = props
        report = self.probe(torch)
        self.assertEqual(report["backends"]["cuda"]["status"], "error")
        self.assertEqual(report["backends"]["cuda"]["devices"], [])
        self.assertEqual(report["backends"]["xpu"]["status"], "available")
        with self.assertRaisesRegex(gpu.AcceleratorError, "Repair"):
            gpu.select_device(report, "cuda:0")

    def test_selection_fails_closed_on_malformed_missing_or_insufficient_device(self):
        report = self.probe(framework(cuda="12.8"))
        for selector in ("cpu", "auto", "cuda", "cuda:-1", "cuda:00", "mps:1", "vulkan:0", None):
            with self.subTest(selector=selector), self.assertRaises(gpu.AcceleratorError):
                gpu.select_device(report, selector)
        with self.assertRaisesRegex(gpu.AcceleratorError, "not visible"):
            gpu.select_device(report, "cuda:2")
        with self.assertRaisesRegex(gpu.AcceleratorError, "insufficient"):
            gpu.select_device(report, "cuda:0", min_memory_bytes=9 * 1024 ** 3)
        for memory in (-1, True, 1.2):
            with self.assertRaises(gpu.AcceleratorError):
                gpu.select_device(report, "cuda:0", min_memory_bytes=memory)

    def test_no_implicit_mps_cpu_kernel_fallback_in_diagnostic(self):
        with patch.object(gpu, "_load_torch", return_value=framework(mps=True)), \
                patch.dict("os.environ", {"PYTORCH_ENABLE_MPS_FALLBACK": "1"}):
            with self.assertRaisesRegex(gpu.AcceleratorError, "Unset"):
                gpu.diagnose("mps:0")

    def test_diagnostic_never_allocates_on_missing_devices_or_invalid_step_count(self):
        for steps in (0, 11, True, 1.2):
            with self.assertRaises(gpu.AcceleratorError):
                gpu.diagnose("cuda:0", steps=steps)
        torch = framework(available=False)
        with patch.object(gpu, "_load_torch", return_value=torch):
            with self.assertRaises(gpu.AcceleratorError):
                gpu.diagnose("cuda:0")

    def test_cli_outputs_machine_readable_inventory_and_selection_errors(self):
        for argv, expected in (([], 0), (["--device", "cuda:0"], 2),
                               (["--diagnostic-steps", "1"], 2),
                               (["--min-memory-bytes", "-1"], 2),
                               (["--diagnostic-steps", "11"], 2)):
            output = io.StringIO()
            with patch.object(gpu, "_load_torch", side_effect=ModuleNotFoundError), contextlib.redirect_stdout(output):
                self.assertEqual(gpu.main(argv), expected)
            result = json.loads(output.getvalue())
            self.assertFalse(result["production_qualified"])
            self.assertEqual("error" in result, expected == 2)

    def test_runtime_failure_during_diagnostic_is_actionable_and_does_not_fallback(self):
        torch = framework(cuda="12.8")
        torch.device = lambda selector: selector
        torch.nn = NS(Parameter=lambda value: value)
        torch.float32 = "float32"
        def allocate(*args, **kwargs):
            raise RuntimeError("unsupported device kernel")
        torch.ones = allocate
        with patch.object(gpu, "_load_torch", return_value=torch):
            with self.assertRaisesRegex(gpu.AcceleratorError, "GPU diagnostic failed.*RuntimeError"):
                gpu.diagnose("cuda:0")


if __name__ == "__main__":
    unittest.main()
