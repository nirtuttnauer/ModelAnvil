"""Inference-only llama.cpp Vulkan GGUF backend, qualified only on the Apple GPU through MoltenVK.

TASK-41 selects this backend explicitly as ``vulkan:0``. The operator builds the pinned llama.cpp
commit with Vulkan on and Metal off, installs Homebrew's Vulkan loader and MoltenVK, and sets
``MODELANVIL_VULKAN_INFERENCE``. Every session re-verifies the host, server binary, ICD manifest,
MoltenVK and loader bytes and the single visible Vulkan device before loading weights, then
requires llama.cpp to report every layer offloaded to that device. Anything else is refused.
CPU execution happens only through the operator's explicit opt-in and is labelled CPU.
Qualification evidence: docs/engineering/verification/task41-moltenvk-2026-11-15/.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from django.conf import settings

from modelanvil.runners.gguf_runtime import GGUFSession, MAX_WEIGHT_BYTES, read_metadata

SELECTOR = 'vulkan:0'
BACKEND = 'llama.cpp-vulkan'
LLAMA_COMMIT = 'f5027fb21307eb264aed483242603d68c87b0fe3'
LLAMA_VERSION = 'version: 0.7.0-dev (build 11836, commit f5027fb21)'
# GGUF general.file_type values measured on this device; other quantizations are not claimed.
QUALIFIED_FILE_TYPES = {1: 'F16', 7: 'Q8_0', 15: 'Q4_K_M'}
QUALIFIED_ARCHITECTURES = ('llama',)
QUALIFIED_HOST = {'system': 'Darwin', 'machine': 'arm64', 'macos': '27.2.1'}
QUALIFIED_DEVICE = 'Apple M5 Pro'
QUALIFIED_RUNTIME = {
    'icd_manifest': {'package': 'molten-vk 1.4.2', 'api_version': '1.4.0',
                     'sha256': 'b514f51690582fb783383154b7a33c7816cc47e98ee1a1f652dccd3e996f0bf1'},
    'driver': {'name': 'MoltenVK', 'package': 'molten-vk 1.4.2',
               'sha256': 'e21bceade8d0638bb2bc041f3166fbd54da19fa0958d8bbaff584afd7958d542'},
    'loader': {'name': 'Khronos Vulkan loader', 'package': 'vulkan-loader 1.4.363.0',
               'sha256': '6453921b5e0562364d60a4d742fb2db12c3e4e8c2ac2fb6d5938b6453a644208'},
}
QUALIFICATION = ('Inference only: pinned llama.cpp Vulkan build on the Apple M5 Pro GPU through MoltenVK 1.4.2 '
                 'on macOS 27.2.1 arm64 for llama-architecture F16, Q8_0 and Q4_K_M GGUF. No discrete, '
                 'cross-vendor, Linux, Windows or DirectML claim; no Vulkan training.')
INFERENCE_ONLY = ('Vulkan is an inference-only GGUF backend in ModelAnvil; Vulkan training is not supported. '
                  'Select a qualified training device such as cpu, mps:0 or mlx:0.')
MAX_LIFETIME_SECONDS = 1800
STARTUP_SECONDS = 120
_WRAPPER = Path(__file__).with_name('vulkan_server_process.py')


class VulkanUnavailable(ValueError):
    """The Vulkan backend cannot serve this request; CPU is used only by explicit operator opt-in."""


def is_vulkan(selector):
    return isinstance(selector, str) and re.fullmatch(r'vulkan(?::(?:0|[1-9][0-9]*))?', selector) is not None


def cpu_fallback_opted_in():
    config = getattr(settings, 'MODELANVIL_VULKAN_INFERENCE', {})
    return isinstance(config, dict) and config.get('cpu_fallback') is True


@functools.lru_cache(maxsize=16)
def _digest(path, size, modified):
    sha = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(1024 * 1024):
            sha.update(block)
    return sha.hexdigest()


def _sha256(path):
    info = os.stat(path)
    return _digest(str(path), info.st_size, info.st_mtime_ns)


def verify_installation():
    """Check host and installed bytes without starting a process or loading a model."""
    if (platform.system() != QUALIFIED_HOST['system'] or platform.machine() != QUALIFIED_HOST['machine']
            or platform.mac_ver()[0] != QUALIFIED_HOST['macos']):
        raise VulkanUnavailable('This Vulkan backend is qualified only for the Apple GPU through MoltenVK on macOS '
                                f"{QUALIFIED_HOST['macos']} arm64; this host is not qualified.")
    config = getattr(settings, 'MODELANVIL_VULKAN_INFERENCE', {})
    try:
        server = Path(config['server']['path']).resolve(strict=True)
        manifest = Path(config['icd'])
        loader = Path(config['loader']).resolve(strict=True)
        if _sha256(server) != config['server']['sha256'] or not os.access(server, os.X_OK):
            raise VulkanUnavailable('The configured llama.cpp Vulkan server checksum changed; rebuild and requalify it.')
        if _sha256(manifest.resolve(strict=True)) != QUALIFIED_RUNTIME['icd_manifest']['sha256']:
            raise VulkanUnavailable('The Vulkan ICD manifest is not the qualified MoltenVK manifest.')
        icd = json.loads(manifest.read_text())
        library = (manifest.parent / icd['ICD']['library_path']).resolve(strict=True)
        if _sha256(library) != QUALIFIED_RUNTIME['driver']['sha256']:
            raise VulkanUnavailable('The Vulkan driver is not the qualified MoltenVK 1.4.2 library; requalify it.')
        if _sha256(loader) != QUALIFIED_RUNTIME['loader']['sha256']:
            raise VulkanUnavailable('The Vulkan loader is not the qualified 1.4.363.0 library; requalify it.')
    except VulkanUnavailable:
        raise
    except (KeyError, TypeError, OSError, ValueError):
        raise VulkanUnavailable('Install and checksum the pinned llama.cpp Vulkan build, Vulkan loader and MoltenVK '
                                'first (MODELANVIL_VULKAN_INFERENCE).') from None
    return {'server': {'path': str(server), 'sha256': config['server']['sha256'], 'llama_commit': LLAMA_COMMIT},
            'icd_manifest': {'path': str(manifest), 'sha256': QUALIFIED_RUNTIME['icd_manifest']['sha256'],
                             'api_version': icd['ICD'].get('api_version'),
                             'portability_driver': icd['ICD'].get('is_portability_driver') is True},
            'driver': {**QUALIFIED_RUNTIME['driver'], 'path': str(library)},
            'loader': {**QUALIFIED_RUNTIME['loader'], 'path': str(loader)},
            'host': {'system': platform.system(), 'machine': platform.machine(), 'macos': platform.mac_ver()[0]}}


def installed():
    try:
        verify_installation()
        return True
    except VulkanUnavailable:
        return False


def runtime_identity():
    """Installed-byte identity for load receipts; None when the backend is not installed."""
    try:
        value = verify_installation()
    except VulkanUnavailable:
        return None
    return {name: value[name]['sha256'] for name in ('server', 'icd_manifest', 'driver', 'loader')}


def environment(installation, directory):
    """No inherited LLAMA_ARG_*/VK_* settings: only the qualified ICD, no layers, one device."""
    manifest = installation['icd_manifest']['path']
    return {'PATH': '/usr/bin:/bin', 'HOME': directory, 'TMPDIR': directory, 'LANG': 'C', 'LC_ALL': 'C',
            'VK_DRIVER_FILES': manifest, 'VK_ICD_FILENAMES': manifest, 'VK_LOADER_LAYERS_DISABLE': '~all~',
            'GGML_VK_VISIBLE_DEVICES': '0'}


def _run(installation, directory, *args, timeout=30):
    try:
        result = subprocess.run([installation['server']['path'], *args], env=environment(installation, directory),
                                cwd=directory, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise VulkanUnavailable('The llama.cpp Vulkan server could not be inspected within its bound.') from None
    return result.returncode, (result.stdout + result.stderr)[-65536:]


def probe_device(installation, directory):
    """Enumerate devices through the qualified ICD; no model or tensors are created."""
    code, text = _run(installation, directory, '--version')
    if code or LLAMA_VERSION not in text:
        raise VulkanUnavailable('The configured server is not the pinned llama.cpp build.')
    code, text = _run(installation, directory, '--list-devices')
    devices = re.findall(r'^\s+(\S+): (.+) \((\d+) MiB, (\d+) MiB free\)\s*$', text, re.M)
    if code or len(devices) != 1 or devices[0][0] != 'Vulkan0' or devices[0][1] != QUALIFIED_DEVICE:
        raise VulkanUnavailable('Exactly one qualified Vulkan device (Apple M5 Pro through MoltenVK) must be visible.')
    return {'id': 'Vulkan0', 'name': devices[0][1], 'reported_memory_bytes': int(devices[0][2]) * 1024**2,
            'reported_free_bytes': int(devices[0][3]) * 1024**2,
            'memory_scope': 'Unified memory heap reported by MoltenVK through llama.cpp; not dedicated VRAM or a reservation.'}


def inspect():
    """Read-only support check: installed bytes, pinned build and the visible device."""
    installation = verify_installation()
    directory = tempfile.mkdtemp(prefix='modelanvil-vulkan-probe-')
    try:
        return {**installation, 'device': probe_device(installation, directory)}
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _mib(pattern, text):
    return {device: round(float(value) * 1024**2) for device, value in re.findall(pattern, text, re.M)}


def load_evidence(text):
    """llama.cpp's own load report: offloaded layers, device buffers and graph placement."""
    offload = re.findall(r'load_tensors: offloaded (\d+)/(\d+) layers to GPU', text)
    using = re.findall(r'using device (Vulkan\d+) \((.+?)\)(?: \(.*?\))? - (\d+) MiB free', text)
    splits = re.findall(r'graph splits = (\d+)', text)
    nodes = re.findall(r'graph nodes\s*=\s*(\d+)', text)
    flash = re.findall(r'flash_attn\s*=\s*(\S+)', text)
    return {'offloaded_layers': int(offload[-1][0]) if offload else None,
            'model_layers': int(offload[-1][1]) if offload else None,
            'devices_used': [{'id': d, 'name': n, 'free_bytes_at_load': int(f) * 1024**2} for d, n, f in using],
            'model_buffer_bytes': _mib(r'load_tensors:\s+(\S+) model buffer size =\s+([\d.]+) MiB', text),
            'kv_buffer_bytes': _mib(r'llama_kv_cache:\s+(\S+) KV buffer size =\s+([\d.]+) MiB', text),
            'compute_buffer_bytes': _mib(r'(?:llama_context|sched_reserve):\s+(\S+) compute buffer size =\s+([\d.]+) MiB', text),
            'graph_splits': int(splits[-1]) if splits else None, 'graph_nodes': int(nodes[-1]) if nodes else None,
            'flash_attention': 'enabled' if 'Flash Attention enabled' in text else flash[-1] if flash else None,
            'memory_scope': ('llama.cpp-reported buffers; Vulkan_Host is host-visible unified memory holding the token '
                             'embedding table, whose lookup llama.cpp keeps on the CPU by design.')}


def require_full_offload(evidence):
    """Partial offload would silently run layers on CPU; only all layers on Vulkan0 is accepted."""
    used = evidence['devices_used']
    if (not evidence['offloaded_layers'] or evidence['offloaded_layers'] != evidence['model_layers']
            or [d['id'] for d in used] != ['Vulkan0'] or used[0]['name'] != QUALIFIED_DEVICE
            or not evidence['model_buffer_bytes'].get('Vulkan0') or not evidence['kv_buffer_bytes'].get('Vulkan0')
            or set(evidence['kv_buffer_bytes']) != {'Vulkan0'}):
        raise VulkanUnavailable('llama.cpp did not place every layer and the KV cache on the qualified Vulkan device.')
    return evidence


class VulkanGGUFSession(GGUFSession):
    """GGUFSession's bounded HTTP generation against a private pinned Vulkan llama-server process."""

    def __init__(self, path, *, lease_descriptor=None):
        path = Path(path)
        if not 0 < path.stat().st_size <= MAX_WEIGHT_BYTES:
            raise ValueError('GGUF weights must fit within the verified 1 GiB limit.')
        installation = verify_installation()
        try:
            import gguf  # noqa: F401
            import requests
        except ImportError:
            raise VulkanUnavailable('Install requirements.inference.txt for GGUF metadata and the local HTTP client.') from None
        metadata = read_metadata(path)
        if metadata['architecture'] not in QUALIFIED_ARCHITECTURES or metadata['file_type'] not in QUALIFIED_FILE_TYPES:
            raise VulkanUnavailable('Vulkan inference is qualified only for llama-architecture F16, Q8_0 and Q4_K_M GGUF.')
        self.context_limit, self.has_chat_template = metadata['context_limit'], metadata['has_chat_template']
        self.process = self.http = None
        self.directory = tempfile.mkdtemp(prefix='modelanvil-vulkan-')
        try:
            device = probe_device(installation, self.directory)
            key = secrets.token_urlsafe(32)
            key_file = Path(self.directory) / 'api-key'
            key_file.touch(mode=0o600)
            key_file.write_text(key)
            log_path = Path(self.directory) / 'server.log'
            command = [sys.executable, str(_WRAPPER), str(MAX_LIFETIME_SECONDS), installation['server']['path'],
                       '--model', str(path), '--host', '127.0.0.1', '--port', '0', '--api-key-file', str(key_file),
                       '--offline', '--device', 'Vulkan0', '--n-gpu-layers', 'all', '--split-mode', 'none',
                       '--fit', 'off', '--ctx-size', str(self.context_limit), '--parallel', '1', '--n-predict', '256',
                       '--threads', '1', '--threads-batch', '1', '--threads-http', '2', '--no-warmup',
                       '--no-context-shift', '--cache-ram', '0', '--no-cache-idle-slots', '--no-webui',
                       '--metrics', '--slots',
                       # Trace level carries llama.cpp's own load report (offload, buffers); prompts stay at debug.
                       '--log-verbosity', '4', '--log-colors', 'off']
            with log_path.open('wb') as log:
                self.process = subprocess.Popen(command, env=environment(installation, self.directory), cwd=self.directory,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                    pass_fds=() if lease_descriptor is None else (lease_descriptor,))
            self.http = requests.Session()
            self.http.trust_env = False
            self.http.headers['Authorization'] = 'Bearer ' + key
            self.base_url = self._wait_ready(log_path)
            key_file.unlink()
            evidence = require_full_offload(load_evidence(log_path.read_text(errors='replace')))
        except BaseException:
            self.close()
            raise
        self.evidence = {'backend': BACKEND, 'gpu_execution': True, 'selected_device': SELECTOR,
                         'gguf_file_type': QUALIFIED_FILE_TYPES[metadata['file_type']],
                         'architecture': metadata['architecture'], 'device': device, **evidence,
                         'gpu_layers': evidence['offloaded_layers'], 'kv_offload': 'Vulkan0' in evidence['kv_buffer_bytes'],
                         'op_offload': True, 'runtime': {k: installation[k] for k in ('server', 'icd_manifest', 'driver', 'loader', 'host')},
                         'qualification': QUALIFICATION}

    def _wait_ready(self, log_path):
        import requests
        deadline = time.monotonic() + STARTUP_SECONDS
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise VulkanUnavailable('The llama.cpp Vulkan server exited while loading; check the driver and model format.')
            match = re.search(r'listening on (http://127\.0\.0\.1:\d+)', log_path.read_text(errors='replace'))
            if match:
                address = urlsplit(match.group(1))
                if address.hostname != '127.0.0.1' or not address.port:
                    raise VulkanUnavailable('The Vulkan server did not bind to a private loopback port.')
                try:
                    with self.http.get(match.group(1) + '/health', timeout=(2, 5), allow_redirects=False) as response:
                        if response.status_code == 200:
                            return match.group(1)
                except requests.RequestException:
                    pass
            time.sleep(0.05)
        raise VulkanUnavailable('The llama.cpp Vulkan server did not become ready within its bound.')

    def close(self):
        super().close()
        process = getattr(self, 'process', None)
        if process is not None and process.poll() is None:
            for sent in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sent)
                    process.wait(timeout=10)
                    break
                except ProcessLookupError:
                    break
                except subprocess.TimeoutExpired:
                    continue
        self.process = None
        if getattr(self, 'directory', None):
            shutil.rmtree(self.directory, ignore_errors=True)
            self.directory = None
