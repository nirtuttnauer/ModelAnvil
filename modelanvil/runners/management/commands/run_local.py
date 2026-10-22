"""Start the local API and managed GPU service together with one lifecycle."""
import os
import subprocess
import sys
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Start ModelAnvil and its managed local training service; end users need only the browser.'

    def add_arguments(self, parser):
        parser.add_argument('addrport', nargs='?', default='127.0.0.1:8000')
        parser.add_argument('--device', default='mps:0')

    def handle(self, *args, **options):
        call_command('migrate', interactive=False, stdout=self.stdout)
        manage = str(settings.BASE_DIR / 'manage.py')
        processes = []
        try:
            processes.append(subprocess.Popen([sys.executable, manage, 'run_managed_training', '--device', options['device']]))
            processes.append(subprocess.Popen([sys.executable, manage, 'runserver', options['addrport'], '--noreload']))
            while all(p.poll() is None for p in processes):
                time.sleep(1)
            if any(p.returncode for p in processes if p.returncode is not None):
                raise CommandError('A local service stopped. See the service error above.')
        except KeyboardInterrupt:
            pass
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
