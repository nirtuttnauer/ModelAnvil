"""Inventory and diagnostics do not claim that hardware or a model is qualified."""
import contextlib
import io
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from modelanvil import accelerators as gpu


# A false flag records that qualification was not granted. Any other value is a claim.
_CLAIM_KEY = re.compile(r"qualified|production[-_]ready", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"""['"]?(?P<key>[A-Za-z_]*(?:qualified|production[-_]ready)[A-Za-z_]*)['"]?"""
    r"""\s*[:=]\s*(?P<value>True|False|None|true|false|null)\b"""
)
_FORBIDDEN_PHRASE = re.compile(r"production-ready", re.IGNORECASE)
_FORBIDDEN_WORD = re.compile(r"\b(?:best|first)\b", re.IGNORECASE)
_POSITIVE_QUALIFIED = re.compile(r"\bqualified\b", re.IGNORECASE)
_NEGATED = re.compile(r"\b(?:not|never|no)\s+$", re.IGNORECASE)
_MESSAGE_KEYS = {"reason", "error", "operation", "status"}


def _framework(*, cuda=None, hip=None, available=True, mps=False, xpu=False):
    def api(enabled):
        return NS(
            is_available=lambda: enabled,
            device_count=lambda: 1,
            get_device_properties=lambda index: NS(
                name=f"GPU {index}", total_memory=1024, uuid=f"gpu-{index}"
            ),
            synchronize=lambda *args, **kwargs: None,
        )

    return NS(
        __version__="test-runtime",
        version=NS(cuda=cuda, hip=hip),
        cuda=api(available),
        xpu=api(xpu),
        backends=NS(mps=api(mps)),
        mps=NS(recommended_max_memory=lambda: 2048, synchronize=lambda: None),
    )


class _Tensor:
    def __init__(self, device):
        self.device = device
        self.generation = 0
        self.grad = self

    def detach(self):
        return self

    def clone(self):
        copied = _Tensor(self.device)
        copied.generation = self.generation
        return copied

    def square(self):
        return self

    def mean(self):
        return self

    def backward(self):
        return None

    def item(self):
        return 1.0

    def __matmul__(self, other):
        return _Tensor(self.device)


class _Finite:
    def all(self):
        return self

    def item(self):
        return True


class _SGD:
    def __init__(self, params, lr):
        self.params = list(params)

    def zero_grad(self):
        return None

    def step(self):
        for param in self.params:
            param.generation += 1


def _diagnostic_torch(**kwargs):
    torch = _framework(**kwargs)
    torch.device = lambda selector: selector
    torch.float32 = "float32"
    torch.nn = NS(Parameter=lambda value: value)
    torch.ones = lambda shape, device=None, dtype=None: _Tensor(device)
    torch.optim = NS(SGD=_SGD)
    torch.isfinite = lambda tensor: _Finite()
    torch.equal = lambda left, right: left.generation == right.generation
    return torch


def _wording_problems(text):
    """Return positive-claim phrases. 'do not qualify' is the allowed negation."""
    problems = []
    if _FORBIDDEN_PHRASE.search(text):
        problems.append("production-ready")
    word = _FORBIDDEN_WORD.search(text)
    if word:
        problems.append(word.group(0))
    scrubbed = text.replace("do not qualify", "")
    for match in _POSITIVE_QUALIFIED.finditer(scrubbed):
        prefix = scrubbed[max(0, match.start() - 24) : match.start()]
        if _NEGATED.search(prefix):
            continue
        problems.append("qualified")
    return problems


def _positive_marks(node, path="$"):
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}"
            if _CLAIM_KEY.search(str(key)) and value:
                found.append(f"{here}={value!r}")
            if key in _MESSAGE_KEYS and isinstance(value, str):
                found.extend(f"{here}: {problem}" for problem in _wording_problems(value))
            else:
                found.extend(_positive_marks(value, here))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_positive_marks(item, f"{path}[{index}]"))
    return found


def _source_problems(source):
    problems = list(_wording_problems(source))
    for match in _ASSIGNMENT.finditer(source):
        if match.group("value") not in {"False", "false"}:
            problems.append(match.group(0))
    return problems


class AcceleratorWordingTests(unittest.TestCase):
    def assertNoPositiveClaim(self, payload):
        self.assertEqual(_positive_marks(payload), [])

    def test_inventory_without_framework_does_not_mark_qualification(self):
        for exc in (ModuleNotFoundError("torch"), OSError("driver")):
            with self.subTest(exc=type(exc).__name__):
                with patch.object(gpu, "_load_torch", side_effect=exc):
                    report = gpu.inventory()
                self.assertNoPositiveClaim(report)
                for entry in report["backends"].values():
                    self.assertEqual(entry["status"], "unavailable")
                    self.assertEqual(entry["devices"], [])

    def test_visible_devices_do_not_mark_hardware_or_a_model_qualified(self):
        cases = (
            {"cuda": "12.8"},
            {"hip": "6.4"},
            {"available": False, "xpu": True},
            {"available": False, "mps": True},
            {"available": False},
        )
        for kwargs in cases:
            with self.subTest(**kwargs):
                with patch.object(gpu, "_load_torch", return_value=_framework(**kwargs)):
                    report = gpu.inventory()
                self.assertNoPositiveClaim(report)
                for entry in report["backends"].values():
                    for device in entry["devices"]:
                        self.assertNoPositiveClaim(device)

    def test_inventory_error_reason_is_not_a_qualification_claim(self):
        torch = _framework(cuda="12.8")

        def props(index):
            raise RuntimeError("device vanished")

        torch.cuda.get_device_properties = props
        with patch.object(gpu, "_load_torch", return_value=torch):
            report = gpu.inventory()
        self.assertEqual(report["backends"]["cuda"]["status"], "error")
        self.assertEqual(report["backends"]["cuda"]["devices"], [])
        self.assertNoPositiveClaim(report)

    def test_diagnose_does_not_mark_hardware_or_a_model_qualified(self):
        torch = _diagnostic_torch(cuda="12.8")
        with patch.object(gpu, "_load_torch", return_value=torch):
            result = gpu.diagnose("cuda:0", steps=2)
        self.assertNoPositiveClaim(result)
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["weights_changed"], True)
        self.assertEqual(result["device"]["id"], "cuda:0")

    def test_diagnostic_failure_message_is_not_a_qualification_claim(self):
        torch = _diagnostic_torch(cuda="12.8")

        def unavailable(*args, **kwargs):
            raise RuntimeError("unsupported device kernel")

        torch.ones = unavailable
        with patch.object(gpu, "_load_torch", return_value=torch):
            with self.assertRaises(gpu.AcceleratorError) as caught:
                gpu.diagnose("cuda:0")
        self.assertEqual(_wording_problems(str(caught.exception)), [])

    def test_cli_default_messages_do_not_claim_qualification(self):
        cases = (
            [],
            ["--device", "cuda:0"],
            ["--diagnostic-steps", "1"],
            ["--min-memory-bytes", "-1"],
            ["--diagnostic-steps", "11"],
        )
        for argv in cases:
            output = io.StringIO()
            with self.subTest(argv=argv):
                with (
                    patch.object(gpu, "_load_torch", side_effect=ModuleNotFoundError),
                    contextlib.redirect_stdout(output),
                ):
                    status = gpu.main(argv)
                result = json.loads(output.getvalue())
                self.assertIn(status, (0, 2))
                self.assertNoPositiveClaim(result)

    def test_module_source_has_no_positive_claim_wording(self):
        source = Path(gpu.__file__).read_text(encoding="utf-8")
        self.assertEqual(_source_problems(source), [])
        self.assertIn("do not qualify", gpu.__doc__)
