"""Actual POSIX contention/release tests; these do not qualify other GPU hardware."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import skipUnless

from django.test import SimpleTestCase, override_settings
from modelanvil.device_admission import DeviceBusy, device_available, device_key, device_lease


@skipUnless(os.name == 'posix', 'POSIX local device admission')
class DeviceAdmissionTests(SimpleTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'devices'
        settings = override_settings(MODELANVIL_DEVICE_LOCK_ROOT=str(self.root))
        settings.enable(); self.addCleanup(settings.disable)

    def test_aliases_contend_but_distinct_devices_do_not(self):
        self.assertEqual(device_key('mps:0'), device_key('mlx:0'))
        with device_lease('mps:0'):
            self.assertFalse(device_available('mlx:0'))
            with self.assertRaises(DeviceBusy):
                with device_lease('mlx:0'):
                    self.fail('Apple GPU allocated twice')
            with device_lease('cpu'), device_lease('cuda:1'):
                self.assertFalse(device_available('cpu'))
                self.assertTrue(device_available('cuda:0'))
        self.assertTrue(device_available('mlx:0'))
        for selector in ('mps', '../cpu', 'cuda:-1', None, []):
            with self.assertRaises(ValueError):
                device_key(selector)

    def test_failure_releases_and_unsafe_lock_paths_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            with device_lease('cpu'):
                raise RuntimeError('injected')
        self.assertTrue(device_available('cpu'))
        lock = self.root / 'apple-0.lock'
        lock.symlink_to(self.root / 'cpu.lock')
        with self.assertRaises(OSError):
            with device_lease('mlx:0'):
                self.fail('Symlinked lock used')
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private'):
            device_available('cpu')

    def test_second_process_is_excluded_and_process_death_releases(self):
        code = "from modelanvil.device_admission import device_lease\nwith device_lease('mps:0'):\n print('held', flush=True)\n input()\n"
        child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'modelanvil.settings',
                'MODELANVIL_DEVICE_LOCK_ROOT': str(self.root)})
        def stop():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        self.addCleanup(stop)
        self.assertEqual(child.stdout.readline().strip(), 'held')
        self.assertFalse(device_available('mlx:0'))
        child.terminate(); child.wait(timeout=10)
        self.assertTrue(device_available('mlx:0'))

    def test_child_keeps_lease_after_parent_closes_until_child_deadline(self):
        import signal
        code="import signal,time\nsignal.alarm(1)\nprint('held',flush=True)\ntime.sleep(10)\n"
        with device_lease('mps:0', pass_descriptor=True) as descriptor:
            self.assertFalse(os.get_inheritable(descriptor))
            child=subprocess.Popen([sys.executable,'-I','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,pass_fds=(descriptor,))
            def stop():
                if child.poll() is None:child.kill()
                child.communicate(timeout=5)
            self.addCleanup(stop)
            self.assertEqual(child.stdout.readline().strip(),'held')
        # The API's close/death does not free admission while its GPU child still lives.
        self.assertFalse(device_available('mlx:0'))
        self.assertEqual(child.wait(timeout=5),-signal.SIGALRM)
        self.assertTrue(device_available('mlx:0'))
