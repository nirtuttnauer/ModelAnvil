"""Prove paid providers stay off unless an operator turns them on.

These checks are static. They run under Django's test runner and under pytest.
They do not call Runpod, an external model provider, or S3.

The import graph is what Python loads by importing each entry point: module-level
imports, imports executed while defining a class, Django ``include("...")``
literals, and module-level ``import_module`` / ``__import__`` literals. Imports
inside functions are not part of that graph. Opt-in provider calls may import
``modelanvil.runners.external_inference`` only when that view runs.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

PAID_MODULES = (
    'modelanvil.compute.runpod',
    'modelanvil.runners.external_inference',
)

# Default local server, local training, and the worker. The URL conf is loaded
# by Django from modelanvil.urls via include(), so both modules are entry points.
GOLDEN_PATH = (
    'modelanvil.wsgi',
    'modelanvil.asgi',
    'modelanvil.urls',
    'modelanvil.api.urls',
    'modelanvil.runners.management.commands.run_local',
    'modelanvil.runners.management.commands.run_managed_training',
    'modelanvil.runners.inference',
    'modelanvil.runners.local_execution',
    'modelanvil.worker_agent',
    'modelanvil.jobs.management.commands.run_worker',
)

EVAL_ENTRY_POINTS = (
    'modelanvil.runners.eval_executor',
    'modelanvil.runners.eval_worker',
    'modelanvil.runners.guided_evaluation',
    'modelanvil.api.views.models_evals',
)

# Hosted chat and GPU-rental client libraries. boto3 stays allowed: it is the
# S3 client, and the settings check proves S3 is not selected by default.
PAID_PROVIDER_SDKS = frozenset({
    'openai',
    'anthropic',
    'cohere',
    'groq',
    'mistralai',
    'together',
    'fireworks-ai',
    'replicate',
    'runpod',
    'modal',
    'google-generativeai',
    'google-cloud-aiplatform',
    'vertexai',
})

# Standard GitHub-hosted runner labels from
# https://docs.github.com/en/actions/reference/runners/github-hosted-runners
# as published on 2026-10-29. Larger runners, GPU runners, and self-hosted
# labels are not in this set.
STANDARD_GITHUB_HOSTED_RUNNERS = frozenset({
    'ubuntu-slim',
    'ubuntu-latest',
    'ubuntu-22.04',
    'ubuntu-24.04',
    'ubuntu-26.04',
    'ubuntu-22.04-arm',
    'ubuntu-24.04-arm',
    'ubuntu-26.04-arm',
    'windows-latest',
    'windows-2022',
    'windows-2025',
    'windows-2025-vs2026',
    'windows-11-arm',
    'windows-11-vs2026-arm',
    'macos-14',
    'macos-15',
    'macos-26',
    'macos-latest',
    'macos-15-intel',
    'macos-26-intel',
    'xcode-27',
})

_REQUIREMENT_NAME = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?')
_SKIPPED_DIRS = {'.git', '.venv', '.venv-gpu', 'node_modules', '__pycache__'}


def module_file(name):
    base = ROOT.joinpath(*name.split('.'))
    file_path = base.with_suffix('.py')
    if file_path.is_file():
        return file_path
    init = base / '__init__.py'
    if init.is_file():
        return init
    return None


def is_paid(name):
    return any(name == paid or name.startswith(paid + '.') for paid in PAID_MODULES)


def _type_checking(test):
    if isinstance(test, ast.Name):
        return test.id == 'TYPE_CHECKING'
    if isinstance(test, ast.Attribute):
        return test.attr == 'TYPE_CHECKING'
    return False


def resolve_from(current, node):
    if node.level == 0:
        return node.module
    parts = current.split('.')
    path = module_file(current)
    if path is not None and path.name != '__init__.py':
        parts = parts[:-1]
    climb = node.level - 1
    if climb:
        if climb > len(parts):
            return None
        parts = parts[:-climb]
    prefix = '.'.join(parts)
    if node.module:
        return f'{prefix}.{node.module}' if prefix else node.module
    return prefix or None


def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base:
            return base + '.' + node.attr
    return None


def _calls(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        return
    if isinstance(node, ast.Call):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _calls(child)


def load_time_imports(source, current):
    """Return (module, lineno) pairs loaded by importing ``current``."""
    tree = ast.parse(source)
    found = []

    def add_import(node):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
            return
        base = resolve_from(current, node)
        if not base:
            return
        saw_submodule = False
        for alias in node.names:
            if alias.name == '*':
                found.append((base, node.lineno))
                saw_submodule = True
                continue
            candidate = f'{base}.{alias.name}'
            if module_file(candidate) or is_paid(candidate):
                found.append((candidate, node.lineno))
                saw_submodule = True
            else:
                found.append((base, node.lineno))
        if not saw_submodule:
            found.append((base, node.lineno))

    def add_dynamic(node):
        for call in _calls(node):
            name = _dotted_name(call.func)
            if not name or not call.args:
                continue
            leaf = name.rsplit('.', 1)[-1]
            if leaf not in {'import_module', '__import__', 'include'}:
                continue
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append((arg.value, call.lineno))

    def visit(nodes):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                add_import(node)
                continue
            if isinstance(node, ast.ClassDef):
                visit(node.body)
                continue
            if isinstance(node, ast.If):
                if _type_checking(node.test):
                    continue
                visit(node.body)
                visit(node.orelse)
                continue
            if isinstance(node, ast.Try):
                visit(node.body)
                for handler in node.handlers:
                    visit(handler.body)
                visit(node.orelse)
                visit(node.finalbody)
                continue
            if isinstance(node, (ast.For, ast.While, ast.With)):
                visit(node.body)
                visit(node.orelse)
                continue
            add_dynamic(node)

    visit(tree.body)
    return found


def import_graph(roots):
    """Walk load-time imports. Return paid hits as (module, chain) pairs."""
    seen = set()
    parent = {}
    stack = [(name, None, 0) for name in roots]
    hits = []
    while stack:
        name, via, line = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        parent[name] = (via, line)
        if is_paid(name):
            hits.append((name, _chain(parent, name)))
            continue
        path = module_file(name)
        if path is None:
            continue
        for imported, lineno in load_time_imports(path.read_text(encoding='utf-8'), name):
            if module_file(imported) is None and not is_paid(imported):
                continue
            parts = imported.split('.')
            for index in range(1, len(parts) + 1):
                prefix = '.'.join(parts[:index])
                if prefix in seen:
                    continue
                if module_file(prefix) is None and not is_paid(prefix):
                    continue
                stack.append((prefix, name if prefix == imported else via, lineno if prefix == imported else line))
    return hits


def _chain(parent, name):
    steps = []
    seen = set()
    while name and name not in seen:
        seen.add(name)
        via, line = parent.get(name, (None, None))
        if via is None:
            steps.append(name)
            break
        steps.append(f'{name} from {via}:{line}')
        name = via
    return ' <- '.join(steps)


def clean_environment():
    env = {'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
    for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR'):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def requirement_files():
    found = []
    for path in ROOT.rglob('requirements*.txt'):
        if any(part in _SKIPPED_DIRS for part in path.parts):
            continue
        found.append(path)
    return tuple(sorted(found))


def requirement_names(text):
    names = []
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        line = line.split(';', 1)[0].split('@', 1)[0].split('[', 1)[0].strip()
        match = _REQUIREMENT_NAME.match(line)
        if match:
            names.append(re.sub(r'[-_.]+', '-', match.group(0)).lower())
    return names


def strip_yaml_comment(line):
    single = False
    double = False
    for index, char in enumerate(line):
        if char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif char == '#' and not single and not double:
            return line[:index]
    return line


def _indent(text):
    return len(text.replace('\t', '    '))


def _unquote(text):
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def workflow_runs_on(text):
    """Return each runs-on value as (kind, payload). kind is label, list, or other."""
    lines = text.splitlines()
    values = []
    index = 0
    while index < len(lines):
        code = strip_yaml_comment(lines[index])
        match = re.match(r'^([ \t]*)runs-on:[ \t]*(.*)$', code)
        if not match:
            index += 1
            continue
        indent = _indent(match.group(1))
        rest = match.group(2).strip()
        index += 1
        if rest in {'', '|', '>', '|-', '>-', '|+', '>+'}:
            block = []
            while index < len(lines):
                raw = strip_yaml_comment(lines[index])
                if raw.strip() == '':
                    index += 1
                    continue
                width = _indent(raw[:len(raw) - len(raw.lstrip(' \t'))])
                if width <= indent:
                    break
                block.append(raw.strip())
                index += 1
            values.append(_interpret_block(block))
        else:
            values.append(_interpret_scalar(rest))
    return values


def _interpret_scalar(text):
    if text.startswith('[') and text.endswith(']'):
        items = [_unquote(item.strip()) for item in text[1:-1].split(',') if item.strip()]
        return ('list', items)
    if text.startswith('{'):
        return ('other', text)
    label = _unquote(text.strip())
    if label.startswith('${{'):
        return ('other', label)
    return ('label', label)


def _interpret_block(lines):
    if not lines:
        return ('other', '')
    if all(line.startswith('- ') for line in lines):
        return ('list', [_unquote(line[2:].strip()) for line in lines])
    if len(lines) == 1 and ':' not in lines[0]:
        return _interpret_scalar(lines[0])
    return ('other', ' '.join(lines))


def standard_runner(value):
    kind, payload = value
    return kind == 'label' and '${{' not in payload and payload in STANDARD_GITHUB_HOSTED_RUNNERS


def workflow_files():
    directory = ROOT / '.github' / 'workflows'
    return tuple(sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix in {'.yml', '.yaml'}
    )) if directory.is_dir() else ()


_SETTINGS_PROBE = r'''
import json, os
from modelanvil import settings as settings_module
names = (
    "MODELANVIL_PLUGINS",
    "MODELANVIL_EXTERNAL_PROVIDERS",
    "MODELANVIL_EXTERNAL_PROVIDER_KEYS",
    "MODELANVIL_ARTIFACT_BACKEND",
    "MODELANVIL_S3_ENDPOINT",
    "MODELANVIL_S3_BUCKET",
    "MODELANVIL_S3_REGION",
    "MODELANVIL_S3_ACCESS_KEY",
    "MODELANVIL_S3_SECRET_KEY",
)
print(json.dumps({
    "env": {name: os.environ.get(name) for name in names},
    "plugins": settings_module.MODELANVIL_PLUGINS,
    "providers": settings_module.MODELANVIL_EXTERNAL_PROVIDERS,
    "keys": settings_module.MODELANVIL_EXTERNAL_PROVIDER_KEYS,
    "backend": settings_module.MODELANVIL["artifact_backend"],
    "s3_endpoint_url": settings_module.MODELANVIL["s3_endpoint_url"],
    "s3_bucket": settings_module.MODELANVIL["s3_bucket"],
    "s3_region": settings_module.MODELANVIL["s3_region"],
    "s3_access_key": settings_module.MODELANVIL["s3_access_key"],
    "s3_secret_key": settings_module.MODELANVIL["s3_secret_key"],
}))
'''


class PaidDefaultsTests(unittest.TestCase):
    def test_paid_settings_default_to_empty_with_a_clean_environment(self):
        polluted = {
            'MODELANVIL_PLUGINS': '{"runpod": {"kind": "compute"}}',
            'MODELANVIL_EXTERNAL_PROVIDERS': '{"tenant:project": {"vendor": {}}}',
            'MODELANVIL_EXTERNAL_PROVIDER_KEYS': '{"tenant:project": {"vendor": "secret"}}',
            'MODELANVIL_ARTIFACT_BACKEND': 's3',
            'MODELANVIL_S3_ENDPOINT': 'https://s3.example',
            'MODELANVIL_S3_BUCKET': 'paid-bucket',
            'MODELANVIL_S3_REGION': 'eu-west-1',
            'MODELANVIL_S3_ACCESS_KEY': 'AKIATEST',
            'MODELANVIL_S3_SECRET_KEY': 'secret-test',
        }
        previous = {key: os.environ.get(key) for key in polluted}
        os.environ.update(polluted)
        try:
            result = subprocess.run(
                [sys.executable, '-c', _SETTINGS_PROBE],
                env=clean_environment(), cwd=ROOT, capture_output=True, text=True, timeout=60,
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed['env'], {key: None for key in polluted})
        self.assertEqual(observed['plugins'], {})
        self.assertEqual(observed['providers'], {})
        self.assertEqual(observed['keys'], {})
        self.assertEqual(observed['backend'], 'filesystem')
        self.assertEqual(observed['s3_endpoint_url'], '')
        self.assertEqual(observed['s3_bucket'], '')
        self.assertEqual(observed['s3_access_key'], '')
        self.assertEqual(observed['s3_secret_key'], '')
        self.assertEqual(observed['s3_region'], 'us-east-1')

    def test_golden_path_and_eval_do_not_import_paid_modules(self):
        for name in GOLDEN_PATH + EVAL_ENTRY_POINTS:
            self.assertIsNotNone(module_file(name), f'missing entry point {name}')
        function_only = 'def load():\n    from modelanvil.runners import external_inference\n'
        self.assertNotIn(
            'modelanvil.runners.external_inference',
            [name for name, _line in load_time_imports(function_only, 'modelanvil.example')],
        )
        module_level = 'from modelanvil.runners import external_inference\n'
        self.assertIn(
            'modelanvil.runners.external_inference',
            [name for name, _line in load_time_imports(module_level, 'modelanvil.example')],
        )
        hits = import_graph(GOLDEN_PATH + EVAL_ENTRY_POINTS)
        self.assertEqual(hits, [], 'Paid modules are on the default import graph: ' + '; '.join(chain for _name, chain in hits))

    def test_requirements_do_not_list_paid_provider_sdks(self):
        files = requirement_files()
        self.assertTrue(files, 'no requirements*.txt files found')
        self.assertIn('openai', requirement_names('openai==1.40.0\n'))
        self.assertIn('anthropic', requirement_names('Anthropic>=0.1\n'))
        self.assertIn('runpod', requirement_names('runpod[async]==1.0\n'))
        self.assertEqual(requirement_names('# openai==1\n-r requirements.txt\n'), [])
        found = {}
        for path in files:
            names = requirement_names(path.read_text(encoding='utf-8'))
            paid = sorted(set(names) & PAID_PROVIDER_SDKS)
            if paid:
                found[str(path.relative_to(ROOT))] = paid
        base = requirement_names((ROOT / 'requirements.txt').read_text(encoding='utf-8'))
        self.assertIn('django', base)
        self.assertIn('boto3', base)
        self.assertEqual(found, {})

    def test_workflow_runners_are_standard_github_hosted(self):
        self.assertTrue(standard_runner(('label', 'ubuntu-latest')))
        self.assertTrue(standard_runner(('label', 'ubuntu-24.04')))
        self.assertFalse(standard_runner(('label', 'self-hosted')))
        self.assertFalse(standard_runner(('label', 'ubuntu-latest-8-cores')))
        self.assertFalse(standard_runner(('list', ['self-hosted', 'linux'])))
        self.assertFalse(standard_runner(('other', 'group: gpu')))
        self.assertFalse(standard_runner(_interpret_scalar('${{ matrix.os }}')))
        files = workflow_files()
        self.assertTrue(files, '.github/workflows has no workflow files')
        offenders = []
        seen = 0
        for path in files:
            for value in workflow_runs_on(path.read_text(encoding='utf-8')):
                seen += 1
                if not standard_runner(value):
                    offenders.append(f'{path.relative_to(ROOT)}: {value[1]}')
        self.assertGreater(seen, 0, '.github/workflows has no runs-on values')
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
