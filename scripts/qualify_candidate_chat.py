"""Check completed hardware-pilot candidates through the project-scoped chat API."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification', type=Path, required=True)
    args = parser.parse_args()
    directory = args.qualification.resolve()
    report = json.loads((directory / 'task13-gpu-pilot.json').read_text())
    expected = json.loads((directory / 'task13-gpu-independent-inference.json').read_text())
    if not (directory / 'qualification.sqlite').is_file():
        parser.error('Select an isolated qualification directory with its existing pilot database.')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(directory / 'qualification.sqlite'))
    import django
    django.setup()
    from django.conf import settings
    from django.test import override_settings
    from rest_framework.test import APIClient
    from modelanvil.identity.models import ApiKey, Role, generate_api_key
    from modelanvil.core.tenancy import set_active_project, set_active_tenant
    set_active_tenant(report['tenant_id']); set_active_project(report['project_id'])
    secret, hashed = generate_api_key()
    key = ApiKey.objects.create(tenant_id=report['tenant_id'], project_id=report['project_id'],
        name='Temporary isolated candidate chat qualification', role=Role.ENGINEER, secret_hash=hashed)
    client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
    outputs = {}
    try:
        with override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': str(directory / 'artifacts')}):
            listed = client.get('/api/v1/inference/models/')
            assert listed.status_code == 200, listed.content
            assert report['candidate'] in {model['id'] for model in listed.data['data']}
            for device in (('mlx:0',) if report['pins']['recipe'] == 'qlora_adapter' else ('cpu', report['pins']['accelerator']['device']['id'])):
                response = client.post('/api/v1/inference/chat/completions', {'model': report['candidate'],
                    'messages': [{'role': 'user', 'content': expected['prompt']}],
                    'max_tokens': len(expected['generated_token_ids']), 'temperature': 0, 'device': device}, format='json')
                assert response.status_code == 200, response.content
                assert response.data['choices'][0]['message']['content'] == expected['completion']
                outputs[device] = response.data
            rejected = client.patch(f"/api/v1/model-versions/{report['candidate']}/", {'metadata': {}}, format='json')
            assert rejected.status_code == 400, rejected.content
        result = {'candidate_id': report['candidate'], 'recipe': report['pins']['recipe'],
            'outputs': outputs, 'matches_independent_consumer': True, 'candidate_mutation_rejected': True,
            'scope': 'Actual completed isolated-pilot candidate through local CPU and named GPU chat API. No broader quality or production claim.'}
        with (directory / 'candidate-api-verification.json').open('x') as target:
            json.dump(result, target, indent=2); target.write('\n')
        print(json.dumps({'recipe': result['recipe'], 'devices': list(outputs), 'matches_independent_consumer': True}))
    finally:
        key.delete()


if __name__ == '__main__':
    main()
