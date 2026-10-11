"""Specialist request bounds, project isolation and OCR publication lineage."""
import io
import json
import tempfile
import subprocess
import sys
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact, Dataset, LineageEdge
from modelanvil.core.tenancy import set_active_project, set_active_tenant
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.runners.model_catalog import _store, filename_allowed
from modelanvil.runners.models import InferenceRequest, Model, ModelVersion, TokenizerVersion
from modelanvil.runners.specialists import PINS, check_files
from scripts.specialist_runtime import validate_decision, validate_ocr


class SpecialistInputTests(SimpleTestCase):
    def test_typed_schema_bounds_and_unknown_options(self):
        good = {'state': 'Please refund the duplicate charge.', 'questions': {
            'route': {'type': 'choice', 'instructions': 'Who handles this?', 'criteria': {'billing': 'refunds', 'support': 'bugs'}},
            'urgency': {'type': 'score', 'instructions': 'How urgent?', 'criteria': ['low', 'high']},
            'refund': {'type': 'noul', 'instructions': 'Refund requested?'}}}
        validate_decision(good)
        for bad in ({**good, 'state': float('nan')}, {**good, 'state': {'x': float('nan')}}, {**good,'state':'  '},
                    {**good, 'state': 'x' * 32001}, {**good, 'temperature': 1},
                    {**good, 'questions': {'x': {'type': 'choice', 'instructions': 'a', 'criteria': ['a','b']}}},
                    {**good, 'questions': {'x': {'type': 'noul', 'instructions': 'a', 'tool': 'execute'}}}):
            with self.assertRaises(ValueError): validate_decision(bad)
        validate_ocr({'max_tokens': 512})
        for bad in ({'max_tokens': True}, {'max_tokens': 1025}, {'max_tokens': 512, 'prompt': 'other'}):
            with self.assertRaises(ValueError): validate_ocr(bad)

    def test_only_exact_auxiliary_subpaths_allowed(self):
        self.assertTrue(filename_allowed('encoder/config.json'))
        self.assertTrue(filename_allowed('processor_config.json'))
        for name in ('encoder/../config.json', '/tokenizer/tokenizer.json', 'model.py', 'encoder/model.safetensors'):
            self.assertFalse(filename_allowed(name))

    def test_snapshot_pin_set_and_every_hash_are_required(self):
        files = {n: {**pin, 'artifact_id': 'fixture'} for n, pin in PINS['laya']['files'].items()}
        check_files(files, 'laya')
        with self.assertRaises(ValueError): check_files({n: r for n, r in files.items() if n != 'encoder/config.json'}, 'laya')
        with self.assertRaises(ValueError): check_files({**files, 'model.safetensors': {**files['model.safetensors'], 'sha256':'f'*64}}, 'laya')


class SpecialistApiTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(); self.addCleanup(storage.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': storage.name})
        override.enable(); self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug='specialist', name='Specialist')
        set_active_tenant(self.tenant.pk); self.addCleanup(set_active_tenant, None)
        team = Team.objects.create(tenant_id=self.tenant.pk, name='team', slug='team')
        self.project = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='one', slug='one')
        self.other = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='two', slug='two')
        set_active_project(self.project.pk); self.addCleanup(set_active_project, None)
        secret, hashed = generate_api_key()
        self.key = ApiKey.objects.create(tenant=self.tenant, project=self.project, name='engineer', role=Role.ENGINEER, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.model = self.version('ocr', self.project)
        self.laya = self.version('laya', self.project)

    def version(self, kind, project):
        ref = _store(io.BytesIO(b'{}'), tenant=self.tenant.pk, project=project.pk, name='snapshot.json')
        tok = TokenizerVersion.all_objects.create(tenant_id=self.tenant.pk, project=project, name=f'tok-{kind}-{project.pk}')
        model = Model.all_objects.create(tenant_id=self.tenant.pk, project=project, name=f'model-{kind}-{project.pk}')
        return ModelVersion.all_objects.create(tenant_id=self.tenant.pk, project=project, model=model, tokenizer=tok,
            architecture_ref=f'modelanvil.{kind}.v1', artifact_manifest_id=ref['artifact_id'],
            metadata={'format': kind, 'source': {}, 'snapshot_manifest': ref, 'imported': True})

    def upload_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        file = SimpleUploadedFile('receipt.png', b'\x89PNG\r\n\x1a\nfixture')
        r = self.client.post('/api/v1/specialists/upload-image/', {'file': file}, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['artifact_id']

    @patch('modelanvil.runners.specialists.execute')
    def test_ocr_measured_record_and_source_model_publication_lineage(self, execute):
        image = self.upload_image()
        execute.return_value = {'text': 'Invoice 1042\nTotal: 38.50 USD', 'usage': {'input_tokens': 400, 'output_tokens': 20},
            'elapsed_seconds': 2.0, 'image_dimensions': [900, 350],
            'provenance': {'source': {'revision': 'a'*40}, 'snapshot_sha256': 'b'*64, 'files': {}}}
        result = self.client.post('/api/v1/specialists/ocr/', {'model': str(self.model.model_version_id), 'image_artifact': image}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        record = InferenceRequest.all_objects.get(request_id=result.data['request_id'])
        self.assertEqual(record.status, 'completed'); self.assertEqual(record.usage['input_tokens'], 400)
        output = Artifact.all_objects.get(artifact_id=result.data['output_artifact']['artifact_id'])
        self.assertEqual(output.metadata['kind'], 'ocr_dataset_input')
        self.assertEqual(set(LineageEdge.all_objects.filter(child_artifact=output).values_list('relation', flat=True)), {'ocr_text','ocr_model'})
        dataset = Dataset.all_objects.create(tenant_id=self.tenant.pk, project=self.project, name='OCR dataset')
        published = self.client.post(f'/api/v1/datasets/{dataset.dataset_id}/prepare/',
            {'input_artifact_id': str(output.artifact_id), 'chunk_characters': 32, 'detect': True, 'dedup': True}, format='json')
        self.assertEqual(published.status_code, 201, published.data)
        self.assertEqual(published.data['row_count'], 1)
        self.assertTrue(LineageEdge.all_objects.filter(parent_artifact=output, relation='derived_dataset').exists())

    @patch('modelanvil.runners.specialists.execute')
    def test_scope_role_kind_and_error_records(self, execute):
        image = self.upload_image()
        foreign = self.version('ocr', self.other)
        body = {'model': str(foreign.model_version_id), 'image_artifact': image}
        self.assertEqual(self.client.post('/api/v1/specialists/ocr/', body, format='json').status_code, 404)
        self.assertEqual(self.client.post('/api/v1/specialists/ocr/', {**body, 'model': str(self.laya.model_version_id)}, format='json').status_code, 404)
        bad = _store(io.BytesIO(b'image'), tenant=self.tenant.pk, project=self.other.pk, name='image', metadata={'kind':'ocr_image'})
        self.assertEqual(self.client.post('/api/v1/specialists/ocr/', {'model':str(self.model.model_version_id), 'image_artifact':bad['artifact_id']}, format='json').status_code, 404)
        execute.assert_not_called()
        execute.side_effect = ValueError('Token budget exceeded.')
        self.assertEqual(self.client.post('/api/v1/specialists/ocr/', {'model':str(self.model.model_version_id),'image_artifact':image}, format='json').status_code, 400)
        self.assertEqual(InferenceRequest.all_objects.get().status, 'failed')
        self.assertFalse(Artifact.all_objects.filter(metadata__kind='ocr_dataset_input').exists())
        self.key.role = Role.VIEWER; self.key.save(update_fields=['role'])
        self.assertEqual(self.client.post('/api/v1/specialists/decisions/', {'model':str(self.laya.model_version_id),'state':'a','questions':{}}, format='json').status_code, 403)

    def test_wrong_image_bytes_and_model_mutation_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.assertEqual(self.client.post('/api/v1/specialists/upload-image/', {'file': SimpleUploadedFile('x.png',b'plain text')}, format='multipart').status_code,400)
        from django.core.exceptions import ValidationError
        self.model.metadata = {'format': 'safetensors'}
        with self.assertRaises(ValidationError): self.model.save()

    def test_acquisition_uses_pinned_plan_and_exact_license_idempotency(self):
        from modelanvil.jobs.models import Worker, WorkerPool
        pool = WorkerPool.all_objects.create(tenant_id=self.tenant.pk, name='import')
        Worker.all_objects.create(tenant_id=self.tenant.pk, pool=pool, name='worker', capabilities={'model_import':True})
        body = {'kind':'laya','name':'Pinned Laya','pool':pool.pk,'accepted_license':'mit','idempotency_key':'one'}
        self.assertEqual(self.client.post('/api/v1/specialists/acquire/',body,format='json').status_code,400)
        body['accepted_license'] = 'apache-2.0'
        one = self.client.post('/api/v1/specialists/acquire/',body,format='json')
        two = self.client.post('/api/v1/specialists/acquire/',body,format='json')
        self.assertEqual(one.status_code,201,one.data);self.assertEqual(one.data,two.data)
        from modelanvil.runners.models import ModelImport
        item = ModelImport.all_objects.get(import_id=one.data['import_id'])
        self.assertEqual(item.files,PINS['laya']['files']);self.assertEqual(item.revision,PINS['laya']['revision'])
        self.assertEqual(self.client.post('/api/v1/specialists/acquire/',{**body,'revision':'f'*40},format='json').status_code,400)

    def test_nested_staging_verifies_bytes_and_removes_work_directory(self):
        from modelanvil.runners.inference import staged_snapshot
        ref = _store(io.BytesIO(b'{"a":1}'),tenant=self.tenant.pk,project=self.project.pk,name='encoder/config.json')
        with staged_snapshot({'encoder/config.json':ref},self.tenant.pk,self.project.pk) as directory:
            self.assertEqual((directory/'encoder/config.json').read_bytes(),b'{"a":1}')
        self.assertFalse(directory.exists())
        bad = {**ref,'sha256':'f'*64}
        with self.assertRaises(ValueError):
            with staged_snapshot({'encoder/config.json':bad},self.tenant.pk,self.project.pk): pass

    @patch('modelanvil.runners.specialists.execute')
    def test_pdf_pages_keep_locations_and_one_source_group_in_immutable_jsonl(self, execute):
        from django.core.files.uploadedfile import SimpleUploadedFile
        uploaded = self.client.post('/api/v1/specialists/upload-image/',{'file':SimpleUploadedFile('scan.pdf',b'%PDF-fixture')},format='multipart')
        self.assertEqual(uploaded.status_code,201,uploaded.data)
        execute.return_value = {'text':'First scanned page\n\nSecond scanned page', 'usage':{'input_tokens':800,'output_tokens':30},
            'elapsed_seconds':3,'image_dimensions':[400,200], 'rasterization':{'source_format':'pdf','renderer':'pypdfium2==5.14.0','page_count':2},
            'pages':[{'page':1,'text':'First scanned page','image_dimensions':[400,200],'raster_sha256':'1'*64},
                     {'page':2,'text':'Second scanned page','image_dimensions':[400,200],'raster_sha256':'2'*64}],
            'provenance':{'source':{},'snapshot_sha256':'b'*64,'files':{}}}
        result = self.client.post('/api/v1/specialists/ocr/',{'model':str(self.model.model_version_id),'image_artifact':uploaded.data['artifact_id']},format='json')
        self.assertEqual(result.status_code,200,result.data)
        rows = result.data['envelopes'];self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['source_group_id'],rows[1]['source_group_id']);self.assertNotEqual(rows[0]['sample_id'],rows[1]['sample_id'])
        self.assertEqual([r['blocks'][0]['location']['page'] for r in rows],[1,2])
        self.assertEqual(rows[1]['provenance']['source_record_key'],'page/2')
        dataset = Dataset.all_objects.create(tenant_id=self.tenant.pk,project=self.project,name='Scanned pages')
        publication = self.client.post(f'/api/v1/datasets/{dataset.dataset_id}/prepare/',{'input_artifact_id':result.data['output_artifact']['artifact_id']},format='json')
        self.assertEqual(publication.status_code,201,publication.data);self.assertEqual(publication.data['row_count'],2)

    def test_child_timeout_has_isolated_environment_exact_code_and_releases_staging(self):
        from pathlib import Path
        from modelanvil.runners.specialists import execute, RUNTIME
        from modelanvil.device_admission import device_lease
        ref=_store(io.BytesIO(b'{}'),tenant=self.tenant.pk,project=self.project.pk,name='config.json')
        inputs={'state':'Request','questions':{'question':{'type':'noul','instructions':'Refund requested?'}}}
        observed={}
        def timeout(command, **kwargs):
            observed['work']=Path(kwargs['cwd'])
            observed['model']=Path(json.loads(kwargs['input'])['directory'])
            self.assertEqual(command[1],'-I')
            self.assertEqual(Path(command[2]).read_bytes(),RUNTIME.read_bytes())
            self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'],'1')
            self.assertEqual(kwargs['env']['PYTORCH_ENABLE_MPS_FALLBACK'],'0')
            self.assertFalse({'HF_TOKEN','PYTHONPATH','AWS_SECRET_ACCESS_KEY'} & set(kwargs['env']))
            self.assertEqual(kwargs['timeout'],120)
            raise subprocess.TimeoutExpired(command,120)
        with override_settings(MODELANVIL_SPECIALIST_PYTHON=sys.executable), patch('modelanvil.runners.specialists.snapshot',return_value={'source':{},'files':{'config.json':ref}}), patch('modelanvil.runners.specialists.subprocess.run',side_effect=timeout):
            with self.assertRaisesRegex(ValueError,'runtime was terminated'):
                execute(self.laya,tenant=self.tenant.pk,project=self.project.pk,kind='laya',device='cpu',inputs=inputs)
        self.assertFalse(observed['work'].exists());self.assertFalse(observed['model'].exists())
        with device_lease('cpu'):pass
