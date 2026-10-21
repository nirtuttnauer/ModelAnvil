"""Build and test an isolated production stack, then remove only its resources."""
import http.client
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main():
    project = 'modelanvil-production-test-' + uuid.uuid4().hex[:8]
    http_port, https_port = free_port(), free_port()
    while https_port == http_port:
        https_port = free_port()
    origin = f'https://localhost:{https_port}'
    with tempfile.TemporaryDirectory(prefix='modelanvil-production-') as directory:
        directory = Path(directory)
        env_file = directory / '.env'
        env_file.write_text(f'MODELANVIL_IMAGE_TAG={project}\nMODELANVIL_BUILD_REVISION={project}\n'
            f'MODELANVIL_DOMAIN=localhost\nMODELANVIL_PUBLIC_ORIGIN={origin}\n'
            f'MODELANVIL_BIND_ADDRESS=127.0.0.1\nMODELANVIL_HTTP_PORT={http_port}\n'
            f'MODELANVIL_HTTPS_PORT={https_port}\nDJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n'
            f'POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n')
        env_file.chmod(0o600)
        command = ['docker', 'compose', '--env-file', str(env_file), '-p', project,
                   '-f', str(ROOT / 'deploy/production/compose.yaml')]

        def compose(*args, **kwargs):
            return subprocess.run(command + list(args), cwd=ROOT, check=True, **kwargs)

        try:
            compose('config', '--quiet')
            compose('build', '--quiet', 'api', 'web')
            compose('up', '-d', '--wait', '--wait-timeout', '60', 'db')
            unapplied = subprocess.run(command + ['run', '--rm', '-T', '--no-deps', 'api'],
                                       cwd=ROOT, capture_output=True, text=True, timeout=30)
            assert unapplied.returncode == 1 and 'Traceback' not in unapplied.stderr, 'API must refuse unapplied migrations'
            compose('run', '--rm', '-T', 'migrate')
            compose('run', '--rm', '-T', '--no-deps', 'migrate', 'python', 'manage.py',
                    'check', '--deploy', '--fail-level', 'ERROR')
            credentials = {'email': 'staging@example.test', 'password': secrets.token_urlsafe(32)}
            credential_file = directory / 'credentials.json'
            credential_file.write_text(json.dumps(credentials))
            credential_file.chmod(0o600)
            fixture = """import django, json, os, sys
from pathlib import Path
django.setup()
from modelanvil.identity.models import Tenant, User, Membership, Role
assert not Tenant.objects.exists() and not User.objects.exists(), 'Development accounts were seeded'
assert os.getuid() != 0, 'API must not run as root'
assert not Path('/app/business').exists() and not Path('/app/.env').exists()
assert not Path('/app/modelanvil/identity/management/commands/bootstrap_dev.py').exists()
Path('/app/storage/artifacts/production-smoke').write_text('persisted artifact')
credentials = json.load(sys.stdin)
tenant = Tenant.objects.create(slug='production-smoke', name='Production smoke')
user = User(email=credentials['email'], name='Staging user')
user.set_password(credentials['password']); user.save()
Membership.objects.create(tenant=tenant, user=user, role=Role.OWNER)
print('Fresh database, non-root API, private files excluded, and staging account verified')
"""
            compose('run', '--rm', '-T', '--no-deps', 'migrate', 'python', '-c', fixture,
                    input=json.dumps(credentials), text=True)
            compose('up', '-d', '--wait', '--wait-timeout', '60', 'api', 'web')
            ca = directory / 'staging-ca.crt'
            for attempt in range(15):
                result = subprocess.run(command + ['cp', 'web:/data/caddy/pki/authorities/local/root.crt', str(ca)],
                                        cwd=ROOT, capture_output=True, text=True)
                if result.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Staging CA was not generated')
            connection = http.client.HTTPConnection('127.0.0.1', http_port, timeout=10)
            connection.request('GET', '/training', headers={'Host': f'localhost:{http_port}'})
            response = connection.getresponse()
            assert response.status == 308 and response.getheader('Location') == origin + '/training'
            connection.close()
            smoke = [sys.executable, str(ROOT / 'scripts/production_smoke.py'),
                     '--origin', origin, '--ca', str(ca), '--credentials', str(credential_file)]
            subprocess.run(smoke, cwd=ROOT, check=True)
            compose('restart', 'api')
            compose('up', '-d', '--wait', '--wait-timeout', '60', 'api', 'web')
            subprocess.run(smoke, cwd=ROOT, check=True)
            compose('exec', '-T', 'api', 'python', '-c',
                    "from pathlib import Path; assert Path('/app/storage/artifacts/production-smoke').read_text() == 'persisted artifact'")
            print(json.dumps({'status': 'passed', 'project': project,
                              'checks': ['migration', 'deployment settings', 'HTTPS redirect',
                                         'authenticated browser session', 'restart persistence']}))
        finally:
            compose('down', '--volumes', '--remove-orphans', '--timeout', '10')


if __name__ == '__main__':
    main()
