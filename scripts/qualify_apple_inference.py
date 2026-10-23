#!/usr/bin/env python3
"""Offline, isolated SmolLM2 CPU/MPS/MLX/GGUF inference mechanics qualification."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--gguf', type=Path, required=True, help='Operator converted pinned SmolLM2 F16 GGUF')
    parser.add_argument('--output', type=Path, required=True, help='New private directory; never an existing DB')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.update(DJANGO_SETTINGS_MODULE='modelanvil.settings', DATABASE_NAME=str(args.output / 'qualification.sqlite'),
                      MODELANVIL_ARTIFACT_ROOT=str(args.output / 'artifacts'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import django
    django.setup()
    import mlx.core as mx
    import torch
    from django.core.management import call_command
    from rest_framework.test import APIClient
    from modelanvil.core.tenancy import set_active_tenant, set_active_project
    from modelanvil.device_admission import device_lease, device_available
    from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
    from modelanvil.runners.inference import local_session, generate, runtime_observation
    from modelanvil.runners.model_catalog import _store
    from modelanvil.runners.models import InferenceRequest, ModelVersion
    from modelanvil.runners.training.hf_runtime import SOURCE, FILE_HASHES, mps_memory
    assert torch.backends.mps.is_available() and mx.metal.is_available(), 'Actual MPS and Metal access required'
    assert os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK') != '1', 'CPU fallback must be disabled'
    pins = {n: hashlib.sha256((args.snapshot / n).read_bytes()).hexdigest() for n in FILE_HASHES}
    assert pins == FILE_HASHES, 'Snapshot differs from the exact public base revision'
    gguf_sha = hashlib.sha256(args.gguf.read_bytes()).hexdigest()
    assert gguf_sha == '9b041a726f64659de76d5f1b3efa1909477b00094b16845a6288c9cd4e2fefc1', 'Unqualified GGUF input'
    call_command('migrate', verbosity=0)
    tenant = Tenant.objects.create(slug='apple-inference', name='Bounded Apple inference qualification')
    set_active_tenant(tenant.pk)
    team = Team.objects.create(tenant_id=tenant.pk, slug='team', name='Team')
    project = Project.objects.create(tenant_id=tenant.pk, team=team, slug='inference', name='Inference qualification')
    other = Project.objects.create(tenant_id=tenant.pk, team=team, slug='isolation', name='Isolation check')
    set_active_project(project.pk)
    keys = []
    def authenticated(project):
        secret, hashed = generate_api_key()
        keys.append(ApiKey.objects.create(tenant=tenant, project=project, name='Temporary qualification', role=Role.ENGINEER, secret_hash=hashed))
        client = APIClient(); client.credentials(HTTP_AUTHORIZATION='Bearer ' + secret)
        return client
    client, outsider = authenticated(project), authenticated(other)
    report = {'source': SOURCE, 'files': pins, 'gguf_sha256': gguf_sha, 'outputs': {}, 'checks': {},
              'scope': 'Bounded offline operation mechanics on this Mac. No domain quality, global free memory, other GPU vendors or production qualification.'}
    def checked(response, status=200):
        assert response.status_code == status, (response.status_code, response.content[:2000])
        return response.data
    def catalog():
        return {row['id']: row for row in checked(client.get('/api/v1/inference/models/'))['data']}
    def measured_memory():
        gc.collect(); torch.mps.synchronize(); torch.mps.empty_cache(); mx.synchronize(); mx.clear_cache()
        return {'mps': mps_memory(), 'mps_current_allocated_bytes': torch.mps.current_allocated_memory(),
                'mlx_active_bytes': mx.get_active_memory(), 'mlx_peak_bytes': mx.get_peak_memory()}
    path = '/api/v1/inference/chat/completions'
    try:
        refs = {}
        for name in FILE_HASHES:
            with (args.snapshot / name).open('rb') as source:
                refs[name] = _store(source, tenant=tenant.pk, project=project.pk, name=name)
        with args.gguf.open('rb') as source:
            gguf = _store(source, tenant=tenant.pk, project=project.pk, name=args.gguf.name)
        models = {}
        for format in ('safetensors', 'mlx', 'gguf'):
            item = checked(client.post('/api/v1/model-imports/', {'name': 'Qualified ' + format, 'format': format,
                'files': {args.gguf.name: gguf} if format == 'gguf' else refs, 'accepted_license': 'apache-2.0',
                'idempotency_key': format}, format='json'), 201)
            models[format] = item['candidate_id']
        report['catalog_before'] = catalog()
        assert all(not row['load_tested'] for row in report['catalog_before'].values())
        # MLX retains its eight-byte process RNG state independently of loaded models.
        mx.random.seed(42); mx.eval(mx.random.state)
        report['memory_before'] = measured_memory()
        for format, device in [('safetensors', 'cpu'), ('safetensors', 'mps:0'), ('mlx', 'mlx:0'), ('gguf', 'cpu')]:
            label = format + ':' + device
            body = {'model': models[format], 'messages': [{'role': 'user', 'content': 'Once upon a time'}],
                    'max_tokens': 8, 'temperature': 0, 'seed': 42, 'prompt_format': 'plain', 'device': device}
            complete = checked(client.post(path, body, format='json', HTTP_IDEMPOTENCY_KEY=label))
            assert complete['usage']['completion_tokens'] > 0 and complete['choices'][0]['message']['content']
            replay = client.post(path, body, format='json', HTTP_IDEMPOTENCY_KEY=label)
            assert checked(replay) == complete and replay['Idempotency-Replayed'] == 'true'
            stream = client.post(path, {**body, 'stream': True, 'stream_options': {'include_usage': True}}, format='json')
            assert stream.status_code == 200
            wire = b''.join(stream.streaming_content); stream.close()
            assert b'[DONE]' in wire and b'inference_error' not in wire
            events = [json.loads(line[6:]) for line in wire.splitlines() if line.startswith(b'data: ') and line != b'data: [DONE]']
            text = ''.join(choice['delta'].get('content', '') for event in events for choice in event.get('choices', []))
            assert text == complete['choices'][0]['message']['content']
            assert events[-1]['usage'] == complete['usage']
            stream = client.post(path, {**body, 'stream': True, 'max_tokens': 32}, format='json')
            assert stream.status_code == 200
            stream.close()
            cancelled = InferenceRequest.all_objects.latest('created_at')
            assert cancelled.status == 'cancelled' and 0 < cancelled.usage['completion_tokens'] <= 32
            assert device_available(device), 'Closing must release device admission'
            too_long = client.post(path, {**body, 'messages': [{'role': 'user', 'content': 'the ' * 3000}]}, format='json')
            assert too_long.status_code == 400
            rejected = outsider.post(path, body, format='json')
            assert rejected.status_code in (400, 404)
            assert models[format] not in {r['id'] for r in checked(outsider.get('/api/v1/inference/models/'))['data']}
            # Restore request context after testing the other project.
            current = catalog()[models[format]]
            assert device in current['load_tested_devices']
            if label == 'safetensors:cpu':
                assert current['load_tested_devices'] == ['cpu'], 'CPU proof must not qualify MPS'
            report['outputs'][label] = {'completion': complete, 'stream': events,
                'cancelled_usage': cancelled.usage, 'context_rejection': too_long.status_code,
                'project_rejection': rejected.status_code, 'memory_after_unload': measured_memory()}
            print('Passed ' + label, flush=True)
        # Count actual MLX forwards at early close: the usage counter cannot hide library lookahead.
        version = ModelVersion.all_objects.get(model_version_id=models['mlx'])
        class CountingModel:
            def __init__(self, model): self.model, self.calls = model, 0
            def __getattr__(self, key): return getattr(self.model, key)
            def __call__(self, *args, **kwargs):
                self.calls += 1
                return self.model(*args, **kwargs)
        with local_session(version, tenant=tenant.pk, project=project.pk, device='mlx:0') as session:
            counter = CountingModel(session['model']); session['model'] = counter
            parts = generate(session, [{'role': 'user', 'content': 'Once upon a time'}], max_tokens=32, prompt_format='plain')
            first = next(parts); parts.close()
            assert first.get('text') and counter.calls == session['measurement']['usage']['completion_tokens']
            report['checks']['mlx_early_close'] = {'actual_forward_calls': counter.calls, 'usage': session['measurement']['usage']}
            # A real computed token with a controlled stop set exercises EOS handling without a fake model.
            tokenizer = session['tokenizer']; eos = tokenizer.eos_token_ids
            prompt = tokenizer.encode('Once upon a time', add_special_tokens=True)
            token = mx.argmax(counter(mx.array([prompt]))[0, -1]).item()
            tokenizer.eos_token_ids = {token}
            stopped = list(generate(session, [{'role': 'user', 'content': 'Once upon a time'}], max_tokens=8, prompt_format='plain'))[-1]
            tokenizer.eos_token_ids = eos
            assert stopped['finish_reason'] == 'stop' and stopped['usage']['completion_tokens'] == 1
            report['checks']['controlled_mlx_eos'] = {**stopped, 'controlled_eos_token': token}
            report['checks']['mlx_loaded'] = runtime_observation(session)
            del counter
        report['memory_final'] = measured_memory()
        assert report['memory_final']['mlx_active_bytes'] == report['memory_before']['mlx_active_bytes'], 'MLX model allocations remained after unload'
        report['catalog_after'] = catalog()
        assert report['catalog_after'][models['gguf']]['devices'] == ['cpu']
        report['checks']['cpu_mps_greedy_equal'] = report['outputs']['safetensors:cpu']['completion']['choices'] == report['outputs']['safetensors:mps:0']['completion']['choices']
        report['checks']['safetensors_mlx_greedy_equal'] = report['outputs']['safetensors:cpu']['completion']['choices'] == report['outputs']['mlx:mlx:0']['completion']['choices']
        with device_lease('mlx:0'):
            report['mlx_device'] = mx.device_info()
        mx.set_default_device(mx.cpu)
        try:
            with local_session(version, tenant=tenant.pk, project=project.pk, device='mlx:0'):
                raise AssertionError('MLX CPU fallback was accepted')
        except ValueError as error:
            assert 'CPU fallback is disabled' in str(error)
            report['checks']['mlx_cpu_fallback_rejected'] = str(error)
        finally:
            mx.set_default_device(mx.gpu)
        body = {'model': models['mlx'], 'messages': [{'role': 'user', 'content': 'Once upon a time'}],
                'max_tokens': 32, 'device': 'mlx:0', 'stream': True}
        stream = client.post(path, body, format='json'); assert stream.status_code == 200
        iterator = iter(stream.streaming_content); next(iterator)
        keys[0].role = Role.VIEWER; keys[0].save(update_fields=['role'])
        withheld = b''.join(iterator); stream.close()
        assert b'inference_error' in withheld and b'"content":' not in withheld
        keys[0].role = Role.ENGINEER; keys[0].save(update_fields=['role'])
        report['checks']['live_mlx_authority_revocation'] = {'text_withheld': True,
            'status': InferenceRequest.all_objects.latest('created_at').status}
        report['passed'] = True
    finally:
        for key in keys:
            key.is_active = False; key.save(update_fields=['is_active'])
        Tenant.objects.filter(pk=tenant.pk).update(status='suspended')
        report['temporary_keys_revoked'] = True
        (args.output / 'report.json').write_text(json.dumps(report, indent=2, default=str) + '\n')


if __name__ == '__main__':
    main()
