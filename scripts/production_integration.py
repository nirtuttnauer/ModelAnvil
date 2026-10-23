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
from modelanvil.identity.models import Tenant, User, Membership, Role, Team, Project, ApiKey, generate_api_key
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
import base64, hashlib, io
from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion
from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
from modelanvil.runners.training.runtime import RUNTIME_ID
team = Team.all_objects.create(tenant_id=tenant.pk, slug='protocol', name='Protocol fixture')
project = Project.all_objects.create(tenant_id=tenant.pk, team=team, slug='protocol', name='Authored protocol fixture')
tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef \\n')]
policy = CausalTextModel(len(tokens), n_embd=4, lora_r=2, lora_alpha=4, seed=42)
for _ in range(4): policy.compute_loss_and_step([1,4,5,2], .15)
raw, manifest = pack_safetensors(policy.export_tensors())
bundle = {'config.json': {'runtime': RUNTIME_ID, 'vocab_size': len(tokens), 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
    'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(),
    'tokenizer_config.json': {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}}
payload = json.dumps(bundle).encode()
artifact = Artifact.all_objects.create(tenant_id=tenant.pk, project=project, storage_location_id='local',
    object_key='protocol/base.json', sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
tokenizer = TokenizerVersion.all_objects.create(tenant_id=tenant.pk, project=project, name='Authored character',
    vocabulary_size=len(tokens), compatibility={'character_v1': {'tokens': tokens}})
model = Model.all_objects.create(tenant_id=tenant.pk, project=project, name='Actual protocol weights')
version = ModelVersion.all_objects.create(tenant_id=tenant.pk, project=project, model=model, revision_no=1,
    tokenizer=tokenizer, architecture_ref=RUNTIME_ID, artifact_manifest_id=str(artifact.artifact_id), metadata={'weights_sha256': manifest['weights_sha256']})
secret, hashed = generate_api_key()
ApiKey.objects.create(tenant=tenant, project=project, name='Private protocol fixture', role=Role.ENGINEER, secret_hash=hashed)
print(json.dumps({'key': secret, 'project_id': str(project.pk), 'model': str(version.model_version_id)}))
"""
            fixture_result = compose('run', '--rm', '-T', '--no-deps', 'migrate', 'python', '-c', fixture,
                    input=json.dumps(credentials), text=True, capture_output=True)
            protocol_credentials = json.loads(fixture_result.stdout.splitlines()[-1])
            protocol_file = directory / 'protocol-credentials.json'
            protocol_file.write_text(json.dumps(protocol_credentials)); protocol_file.chmod(0o600)
            print('Fresh database, non-root API, private files excluded, staging account and real numerical model fixture verified')
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
            ca.chmod(0o644)  # Public trust anchor must be readable by the separate non-root client.
            connection = http.client.HTTPConnection('127.0.0.1', http_port, timeout=10)
            connection.request('GET', '/training', headers={'Host': f'localhost:{http_port}'})
            response = connection.getresponse()
            assert response.status == 308 and response.getheader('Location') == origin + '/training'
            connection.close()
            smoke = [sys.executable, str(ROOT / 'scripts/production_smoke.py'),
                     '--origin', origin, '--ca', str(ca), '--credentials', str(credential_file)]
            subprocess.run(smoke, cwd=ROOT, check=True)
            protocol = [sys.executable, str(ROOT / 'scripts/inference_protocol_client.py'),
                '--origin', origin, '--ca', str(ca), '--credentials', str(protocol_file), '--key-prefix', 'host']
            subprocess.run(protocol, cwd=ROOT, check=True)
            # A separate network namespace uses the same verified hostname/CA at the web service's private address.
            remote_protocol = ['docker', 'run', '--rm', '-i', '--read-only', '--memory', '256m', '--cpus', '1',
                '--network', project + '_edge', '--mount', f'type=bind,source={ca},target=/tmp/protocol-ca.crt,readonly',
                '--entrypoint', 'python', 'modelanvil-api:' + project, '-I', '/app/scripts/inference_protocol_client.py',
                '--origin', origin, '--ca', '/tmp/protocol-ca.crt', '--credentials', '-', '--connect-host', 'web',
                '--connect-port', '443', '--key-prefix', 'namespace']
            subprocess.run(remote_protocol, input=json.dumps(protocol_credentials), text=True, cwd=ROOT, check=True)
            compose('restart', 'api')
            compose('up', '-d', '--wait', '--wait-timeout', '60', 'api', 'web')
            subprocess.run(smoke, cwd=ROOT, check=True)
            subprocess.run(remote_protocol + ['--expect-replay'], input=json.dumps(protocol_credentials), text=True, cwd=ROOT, check=True)
            compose('exec', '-T', 'api', 'python', '-c', """import django; django.setup()
from modelanvil.runners.models import InferenceRequest
from modelanvil.core.models import IdempotencyKey
completed = InferenceRequest.all_objects.filter(status='completed')
assert completed.count() == 4, 'HTTP retries or restart re-executed inference'
assert all(row.usage and row.usage['completion_tokens'] > 0 for row in completed)
assert IdempotencyKey.all_objects.filter(principal__startswith='inference:', response_status=200).count() == 4
print('Four actual measured inferences; host/network retries and restart replay introduced no duplicate usage')
""")
            compose('exec', '-T', 'api', 'python', '-c',
                    "from pathlib import Path; assert Path('/app/storage/artifacts/production-smoke').read_text() == 'persisted artifact'")
            print(json.dumps({'status': 'passed', 'project': project,
                              'checks': ['migration', 'deployment settings', 'HTTPS redirect',
                                         'authenticated browser session', 'actual compatible HTTPS inference',
                                         'independent network namespace client', 'stream/JSON retry identity',
                                         'measured inference ledger without duplicate retries', 'restart persistence']}))
        finally:
            compose('down', '--volumes', '--remove-orphans', '--timeout', '10')


if __name__ == '__main__':
    main()
