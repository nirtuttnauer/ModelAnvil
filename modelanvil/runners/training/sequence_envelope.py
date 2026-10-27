"""Admit a larger SmolLM2 CPU envelope only from a measured report.

The guided GPU profile keeps its own limit. A missing or invalid report leaves
the historical 128-token / 32-generated-token ceiling in place.
"""
from __future__ import annotations

import json
from pathlib import Path

from modelanvil.runners.training.hf_runtime import FILE_HASHES, GUIDED_FILE_HASHES, PACKAGES

REPORT_PATH = Path(__file__).resolve().parents[3] / 'docs/engineering/verification/sequence-envelope-2026-10-28/report.json'
HISTORICAL_SEQUENCE_TOKENS = 128
HISTORICAL_GENERATED_TOKENS = 32
PROFILE = 'modelanvil.smollm2-cpu-sft.v1'
ALLOWED_HASHES = {FILE_HASHES['model.safetensors'], GUIDED_FILE_HASHES['model.safetensors']}


def load_committed_report():
    if not REPORT_PATH.is_file():
        return None
    return json.loads(REPORT_PATH.read_text())


def admit_report(report):
    """Return admitted CPU sequence and memory limits, plus the generation ceiling."""
    if not isinstance(report, dict):
        raise ValueError('Sequence envelope report must be an object.')
    if report.get('profile') != PROFILE or report.get('device') != 'cpu':
        raise ValueError('Only the pinned CPU SmolLM2 profile can admit a measured sequence envelope.')
    if report.get('packages') != PACKAGES:
        raise ValueError('Sequence envelope report must use the current package pins.')
    if report.get('model_sha256') not in ALLOWED_HASHES:
        raise ValueError('Sequence envelope report must name a pinned SmolLM2-135M weight file.')
    steps = report.get('completed_steps')
    sequence = report.get('sequence_tokens')
    generated = report.get('generated_tokens', HISTORICAL_GENERATED_TOKENS)
    peak = report.get('peak_rss_bytes')
    host = report.get('host_memory_bytes')
    rows = report.get('rows_measured')
    if type(steps) is not int or steps < 1:
        raise ValueError('Sequence envelope admission requires at least one completed optimizer step.')
    if type(sequence) is not int or not HISTORICAL_SEQUENCE_TOKENS < sequence <= 2048:
        raise ValueError('Admitted sequences must be above 128 tokens and at most 2048.')
    if type(generated) is not int or not 1 <= generated <= sequence:
        raise ValueError('Admitted generation length must fit inside the measured sequence.')
    if report.get('truncated') is not False or report.get('recovery') != 'parameter_state_roundtrip':
        raise ValueError('The measured step must refuse truncation and reload its updated parameter bytes.')
    if type(peak) is not int or type(host) is not int or peak <= 0 or host < peak + peak // 4:
        raise ValueError('Host memory must cover the measured peak RSS plus 25 percent headroom.')
    if type(rows) is not int or rows < 1:
        raise ValueError('The report must name how many rows the probe consumed.')
    if report.get('production_qualified') is not False or report.get('hardware_qualified') is not False:
        raise ValueError('A CPU sequence probe cannot set production or hardware qualification.')
    return {
        'sequence_tokens': sequence,
        'generated_tokens': generated,
        'memory_bytes': peak + peak // 4,
        'rows_measured': rows,
    }


def apply_cpu_measurement(limits, report=None):
    """Copy training limits, replacing sequence and memory only when a report admits them."""
    updated = dict(limits)
    if report is None:
        try:
            report = load_committed_report()
        except (OSError, json.JSONDecodeError):
            return updated
    if report is None:
        return updated
    try:
        admitted = admit_report(report)
    except ValueError:
        return updated
    updated['sequence_tokens'] = admitted['sequence_tokens']
    updated['memory_bytes'] = admitted['memory_bytes']
    return updated


def generated_token_ceiling(report=None):
    if report is None:
        try:
            report = load_committed_report()
        except (OSError, json.JSONDecodeError):
            return HISTORICAL_GENERATED_TOKENS
    if report is None:
        return HISTORICAL_GENERATED_TOKENS
    try:
        return admit_report(report)['generated_tokens']
    except ValueError:
        return HISTORICAL_GENERATED_TOKENS
