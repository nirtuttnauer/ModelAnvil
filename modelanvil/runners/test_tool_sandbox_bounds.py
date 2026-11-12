"""User and model fields may supply Python source, never a command.

A command string or argv list planted where the code or seconds field goes
must be refused as a process command. The Docker invocation stays the
operator binary resolved as ``docker`` plus the fixed interpreter
``/usr/local/bin/python``.
"""
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from modelanvil.runners import tool_sandbox as sandbox


SHELL_COMMANDS = (
    '; rm',
    '$(uname)',
    '`uname`',
    'sh -c "uname"',
    '; rm -rf /',
)
DECOY = '/tmp/modelanvil-command-probe/docker'


class _Stdin:
    def __init__(self):
        self.buf = bytearray()
        self.closed = False

    def write(self, data):
        self.buf.extend(data)
        return len(data)

    def close(self):
        self.closed = True


class _Process:
    def __init__(self, args, report):
        self.args = args
        self.returncode = None
        self.stdin = _Stdin()
        stdout_r, stdout_w = os.pipe()
        stderr_r, stderr_w = os.pipe()
        os.write(stdout_w, report)
        os.close(stdout_w)
        os.close(stderr_w)
        self.stdout = open(stdout_r, 'rb', buffering=0)
        self.stderr = open(stderr_r, 'rb', buffering=0)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def kill(self):
        self.returncode = -9


class ToolSandboxCommandBoundsTests(SimpleTestCase):
    def setUp(self):
        import tempfile
        self.temp = Path(tempfile.mkdtemp(prefix='modelanvil-sandbox-bounds-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(self.temp, ignore_errors=True))
        operator = self.temp / 'operator'
        operator.mkdir()
        self.operator = operator / 'docker'
        self.operator.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        self.operator.chmod(0o755)
        self.socket_path = str(self.temp / 'docker.sock')
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.socket_path)
        self.addCleanup(self.sock.close)
        self.processes = []
        self.run_calls = []
        self.which_names = []

    def tearDown(self):
        for proc in self.processes:
            for stream in (proc.stdout, proc.stderr):
                if not stream.closed:
                    stream.close()

    def _container(self):
        return {
            'Config': {'Image': sandbox.IMAGE, 'User': '0:0'},
            'Mounts': [],
            'HostConfig': {
                'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False, 'Binds': None,
                'Devices': [], 'Memory': 128 * 1024 ** 2, 'MemorySwap': 128 * 1024 ** 2,
                'NanoCpus': 10 ** 9, 'PidsLimit': 32, 'CapDrop': ['ALL'],
                'CapAdd': ['SETUID', 'SETGID', 'KILL'], 'SecurityOpt': ['no-new-privileges'],
                'Tmpfs': sandbox.TMPFS, 'LogConfig': {'Type': 'none'},
            },
        }

    def _report(self):
        return json.dumps({
            'schema_version': 'modelanvil.python-sandbox.v1', 'status': 'completed', 'exit_code': 0,
            'stdout': '', 'stderr': '', 'stdout_bytes': 0, 'stderr_bytes': 0, 'wall_seconds': 0.01,
            'cpu_seconds': None, 'execution_uid': 65534, 'network': 'none', 'persistent_files': False,
        }).encode()

    def _fake_run(self, argv, **kwargs):
        self._refuse_shell(argv, kwargs)
        self.run_calls.append(list(argv))
        text = bool(kwargs.get('text') or kwargs.get('universal_newlines'))
        if 'context' in argv and 'inspect' in argv:
            body = json.dumps('unix://' + self.socket_path)
        elif 'image' in argv and 'inspect' in argv:
            body = json.dumps([{
                'Id': 'sha256:fixed', 'RepoDigests': [sandbox.IMAGE], 'Os': 'linux', 'Architecture': 'amd64',
            }])
        elif 'info' in argv:
            body = json.dumps({
                'OSType': 'linux', 'SecurityOptions': ['name=seccomp,profile=builtin'], 'ServerVersion': '27.5.1',
            })
        elif argv.count('inspect') == 1 and 'image' not in argv and 'context' not in argv:
            body = json.dumps([self._container()])
        elif 'rm' in argv or 'kill' in argv:
            body = ''
        else:
            raise AssertionError(argv)
        stdout = body if text else body.encode()
        stderr = '' if text else b''
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

    def _fake_popen(self, argv, **kwargs):
        self._refuse_shell(argv, kwargs)
        self.assertEqual(kwargs.get('pass_fds', ()), ())
        proc = _Process(list(argv), self._report())
        self.processes.append(proc)
        return proc

    def _which(self, name, *args, **kwargs):
        self.which_names.append(name)
        if name != 'docker':
            return None
        return os.path.realpath(self.operator)

    def _refuse_shell(self, argv, kwargs):
        self.assertIsInstance(argv, list)
        self.assertFalse(kwargs.get('shell', False))

    def _patches(self):
        denied = AssertionError
        return (
            patch.dict(os.environ, {'PATH': str(self.operator.parent)}),
            patch.object(sandbox.shutil, 'which', self._which),
            patch.object(sandbox.subprocess, 'run', self._fake_run),
            patch.object(sandbox.subprocess, 'Popen', self._fake_popen),
            patch.object(sandbox.subprocess, 'call', side_effect=denied),
            patch.object(sandbox.subprocess, 'check_call', side_effect=denied),
            patch.object(sandbox.subprocess, 'check_output', side_effect=denied),
            patch.object(sandbox.subprocess, 'getoutput', side_effect=denied),
            patch.object(sandbox.subprocess, 'getstatusoutput', side_effect=denied),
            patch.object(sandbox.os, 'system', side_effect=denied),
            patch.object(sandbox.os, 'popen', side_effect=denied),
        )

    def _run(self, code, seconds=1):
        contexts = self._patches()
        for ctx in contexts:
            ctx.__enter__()
        try:
            return sandbox.run(code, seconds=seconds)
        finally:
            for ctx in reversed(contexts):
                ctx.__exit__(None, None, None)

    def _reset(self):
        self.run_calls.clear()
        self.processes.clear()
        self.which_names.clear()

    def _expected_argv(self, name):
        work, tmp = sandbox.TMPFS['/work'], sandbox.TMPFS['/tmp']
        return [
            os.path.realpath(self.operator), '--host', 'unix://' + self.socket_path,
            'run', '-i', '--name', name, '--pull=never', '--network=none', '--read-only', '--user=0:0',
            '--cpus=1', '--memory=128m', '--memory-swap=128m', '--pids-limit=32', '--cap-drop=ALL',
            '--cap-add=SETUID', '--cap-add=SETGID', '--cap-add=KILL', '--security-opt=no-new-privileges',
            '--workdir=/work', f'--tmpfs=/work:{work}', f'--tmpfs=/tmp:{tmp}', '--log-driver=none',
            sandbox.IMAGE, '/usr/local/bin/python', '-I', '-S', '-B', '-c', sandbox.GUARD.read_text(),
        ]

    def _assert_operator_command(self, planted):
        self.assertEqual(self.which_names, ['docker'])
        self.assertEqual(len(self.processes), 1)
        argv = self.processes[0].args
        name = argv[argv.index('--name') + 1]
        self.assertRegex(name, r'^modelanvil-tool-[0-9a-f-]{36}$')
        self.assertEqual(argv, self._expected_argv(name))
        self.assertTrue(str(argv[0]).endswith('/docker'))
        self.assertNotEqual(argv[0], DECOY)
        self.assertNotIn(planted, argv)
        self.assertNotIn(DECOY, argv)
        for part in argv:
            self.assertNotIn(planted, str(part))
        for call in self.run_calls:
            self.assertEqual(call[0], os.path.realpath(self.operator))
            self.assertNotIn(planted, call)
        payload = json.loads(bytes(self.processes[0].stdin.buf))
        self.assertEqual(payload, {'code': planted, 'wall_seconds': 1})
        names = [Path(str(part)).name for part in argv]
        self.assertNotIn('sh', names)
        self.assertNotIn('bash', names)
        self.assertEqual(argv[argv.index('-c') + 1], sandbox.GUARD.read_text())

    def test_argv_list_is_refused_before_a_process(self):
        payloads = (
            ['/bin/sh', '-c', 'uname'],
            ['rm', '-rf', '/'],
            ('sh', '-c', '; rm'),
            {'argv': ['/bin/sh', '-c', '$(uname)']},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                self._reset()
                with self.assertRaises(ValueError):
                    sandbox.validate(payload, 1)
                with self.assertRaises(ValueError):
                    self._run(payload, seconds=1)
                self.assertEqual(self.run_calls, [])
                self.assertEqual(self.processes, [])
                self.assertEqual(self.which_names, [])

    def test_non_text_command_is_refused_before_a_process(self):
        for payload in (b'; rm', bytearray(b'$(uname)'), b'`uname`'):
            with self.subTest(payload=payload):
                self._reset()
                with self.assertRaises(ValueError):
                    sandbox.validate(payload, 1)
                with self.assertRaises(ValueError):
                    self._run(payload, seconds=1)
                self.assertEqual(self.which_names, [])
                self.assertEqual(self.processes, [])

    def test_seconds_field_command_is_refused_before_a_process(self):
        for seconds in ('; rm', '$(uname)', '`uname`', ['/bin/sh', '-c', 'uname'], '1', 1.5, True):
            with self.subTest(seconds=seconds):
                self._reset()
                with self.assertRaises(ValueError):
                    sandbox.validate('print(1)', seconds)
                with self.assertRaises(ValueError):
                    self._run('print(1)', seconds=seconds)
                self.assertEqual(self.which_names, [])
                self.assertEqual(self.processes, [])
                self.assertEqual(self.run_calls, [])

    def test_shell_command_string_is_not_a_process_command(self):
        for planted in SHELL_COMMANDS:
            with self.subTest(planted=planted):
                self._reset()
                try:
                    sandbox.validate(planted, 1)
                except ValueError:
                    with self.assertRaises(ValueError):
                        self._run(planted, seconds=1)
                    self.assertEqual(self.processes, [])
                    self.assertEqual(self.run_calls, [])
                    continue
                result = self._run(planted, seconds=1)
                self._assert_operator_command(planted)
                self.assertEqual(result['status'], 'completed')
                self.assertTrue(result['container_removed'])

    def test_operator_command_ignores_a_planted_binary_path(self):
        planted = f'print({DECOY!r})'
        self._reset()
        sandbox.validate(planted, 1)
        result = self._run(planted, seconds=1)
        self._assert_operator_command(planted)
        self.assertEqual(result['isolation']['network'], 'none')

    def test_quoted_command_text_stays_python_source_on_stdin(self):
        planted = 'text = "; rm $(uname) `uname`"; print(text)'
        self._reset()
        sandbox.validate(planted, 1)
        self._run(planted, seconds=1)
        self._assert_operator_command(planted)
