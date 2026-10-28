"""Offline execution, scoped policy, safe diagnostics and egress revocation."""
import io
import json
import logging
import socket
import sys
import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.request import Request

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from modelanvil.core.logging import JsonFormatter
from modelanvil.core.models import ActivationEvent, ProjectPrivacyPolicy
from modelanvil.core.privacy import PrivacyRefused, _Redirects, acquisition_scope, guarded_session, open_acquisition, require_destination
from modelanvil.core.tenancy import reset_context, set_active_project, set_active_tenant
from modelanvil.identity.models import ApiKey, Project, ProjectGrant, Role, Team, Tenant, generate_api_key


class PrivacyTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Private', slug='private')
        team = Team.all_objects.create(tenant_id=self.tenant.pk, name='Team', slug='team')
        self.project = Project.all_objects.create(tenant_id=self.tenant.pk, team=team, name='One', slug='one')
        self.other = Project.all_objects.create(tenant_id=self.tenant.pk, team=team, name='Two', slug='two')
        secret, hashed = generate_api_key()
        self.key = ApiKey.objects.create(tenant=self.tenant, project=self.project, name='admin', role=Role.ADMIN, secret_hash=hashed)
        self.client = APIClient(); self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {secret}')
        self.addCleanup(reset_context)

    def test_policy_requires_administrator_and_cannot_expand_installation_destinations(self):
        current = self.client.get('/api/v1/privacy/').json()
        data = {'offline':True, 'acquisition_origins':['https://huggingface.co'], 'measurement_retention_days':7}
        result = self.client.put('/api/v1/privacy/', data, format='json')
        self.assertEqual(result.status_code, 200, result.json())
        self.assertTrue(result.json()['offline'])
        self.assertEqual(self.client.put('/api/v1/privacy/', {**data,'acquisition_origins':['https://evil.invalid']}, format='json').status_code, 400)
        ApiKey.objects.filter(pk=self.key.pk).update(role=Role.ENGINEER)
        self.assertEqual(self.client.put('/api/v1/privacy/', data, format='json').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/privacy/', HTTP_X_PROJECT_ID=str(self.other.pk)).status_code, 401)
        self.assertFalse(current['external_judges']); self.assertFalse(current['diagnostic_content_collection'])

    def test_scope_revocation_and_offline_are_checked_before_a_connection(self):
        ProjectPrivacyPolicy.all_objects.create(tenant_id=self.tenant.pk, project=self.project,
            acquisition_origins=['https://huggingface.co'])
        with acquisition_scope(self.tenant.pk, self.project.pk):
            self.assertEqual(require_destination('https://huggingface.co/a'), 'https://huggingface.co')
            ProjectPrivacyPolicy.all_objects.filter(project=self.project).update(acquisition_origins=[])
            with self.assertRaises(PrivacyRefused): require_destination('https://huggingface.co/a')
        with override_settings(MODELANVIL_OFFLINE=True), patch('socket.socket.connect') as connect:
            with acquisition_scope(self.tenant.pk, self.project.pk), self.assertRaisesMessage(PrivacyRefused,'offline'):
                require_destination('https://huggingface.co/a')
            connect.assert_not_called()
        for purpose in ('judge','generation','analytics','support'):
            with self.assertRaises(PrivacyRefused): require_destination('https://huggingface.co',purpose=purpose)

    @override_settings(MODELANVIL_ACQUISITION_ORIGINS=['https://one.test','https://two.test'])
    def test_redirect_checks_and_cross_origin_credential_stripping(self):
        request = Request('https://one.test/file', headers={'Authorization':'SECRET','X-Api-Key':'SECRET','Cookie':'SECRET','Range':'bytes=4-'})
        redirected = _Redirects().redirect_request(request,None,302,'Found',{},'https://two.test/file')
        self.assertEqual(redirected.get_header('Range'),'bytes=4-')
        self.assertFalse(any('SECRET' in value for value in redirected.headers.values()))
        with self.assertRaises(PrivacyRefused):
            _Redirects().redirect_request(request,None,302,'Found',{},'https://other.test/steal')
        with self.assertRaises(PrivacyRefused):
            open_acquisition(Request('https://one.test/upload',data=b'PRIVATE'),timeout=1)
        with guarded_session() as session:
            import requests
            with self.assertRaises(PrivacyRefused):
                session.send(requests.Request('POST','https://one.test/upload',data='PRIVATE').prepare())

    def test_diagnostics_are_content_free_and_expired_measurement_deletion_is_scoped(self):
        from modelanvil.jobs.models import Job, WorkerPool
        pool = WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='PRIVATE_POOL')
        Job.all_objects.create(tenant_id=self.tenant.pk,project=self.project,pool=pool,name='PRIVATE',payload={'token':'SECRET','prompt':'PRIVATE'})
        bundle = self.client.get('/api/v1/privacy/diagnostics/')
        self.assertEqual(bundle.status_code,200,bundle.json())
        self.assertNotIn('PRIVATE',str(bundle.json())); self.assertNotIn('SECRET',str(bundle.json()))
        self.assertEqual(bundle['Cache-Control'],'no-store')
        self.assertEqual(self.client.get('/api/v1/privacy/diagnostics/?include_content=true').status_code,400)
        self.assertEqual(self.client.put('/api/v1/privacy/diagnostics/',{}).status_code,405)
        for project in (self.project,self.other):
            ActivationEvent.all_objects.create(tenant_id=self.tenant.pk,project=project,event_id=uuid.uuid4(),session_id=uuid.uuid4(),
                kind='activity',created_at=timezone.now()-timedelta(days=31))
        self.assertEqual(self.client.post('/api/v1/privacy/purge-measurements/',{},format='json').status_code,400)
        response = self.client.post('/api/v1/privacy/purge-measurements/',{'confirm':'delete_expired_measurements'},format='json')
        self.assertEqual(response.json()['deleted_measurements'],1)
        self.assertEqual(ActivationEvent.all_objects.get().project_id,self.other.pk)

    def test_shared_sdk_session_has_no_ambient_cookies_and_rejects_a_lost_scope(self):
        import requests
        request = requests.Request('GET','https://huggingface.co/model',headers={'Cookie':'SECRET'}).prepare()
        with guarded_session() as session:
            session.cookies.set('ambient','SECRET')
            with acquisition_scope(self.tenant.pk,self.project.pk), patch('requests.sessions.Session.send') as send:
                session.send(request)
                send.assert_called_once()
                self.assertNotIn('Cookie',request.headers)
                self.assertEqual(len(session.cookies),0)
            reset_context()
            with self.assertRaisesMessage(PrivacyRefused,'scope'):
                session.send(request)

    def test_raw_messages_tracebacks_and_untrusted_request_ids_do_not_enter_logs(self):
        try: raise ValueError('PRIVATE PROMPT with SECRET credential')
        except ValueError:
            record = logging.LogRecord('modelanvil.test',logging.ERROR,'private-path',1,'PRIVATE %s',('SECRET',),sys.exc_info())
        text = JsonFormatter().format(record)
        self.assertNotIn('PRIVATE',text); self.assertNotIn('SECRET',text)
        self.assertEqual(json.loads(text)['exception_type'],'ValueError')
        response = self.client.get('/api/v1/privacy/',HTTP_X_REQUEST_ID='SECRET-CREDENTIAL')
        self.assertNotEqual(response['X-Request-ID'],'SECRET-CREDENTIAL')
        uuid.UUID(response['X-Request-ID'])

    def test_rag_is_project_scoped_and_rechecks_revocation_for_an_existing_engine(self):
        from modelanvil.rag.models import KnowledgeBase
        from modelanvil.rag.ingestion import index_documents
        from modelanvil.rag.retrieval import RetrievalEngine
        base = KnowledgeBase.all_objects.create(tenant_id=self.tenant.pk,project=self.other,name='Private corpus')
        set_active_tenant(self.tenant.pk)
        index = index_documents(base,[{'title':'Private','content':'PRIVATE evidence'}],128,0)
        set_active_project(self.project.pk)
        engine = RetrievalEngine(index)
        self.assertEqual(engine.retrieve_lexical('PRIVATE'),[])
        grant = ProjectGrant.all_objects.create(tenant_id=self.tenant.pk,project=self.other,granted_to_project=self.project,
            resource_type='knowledgebase',resource_id=base.kb_id)
        self.assertEqual(len(engine.retrieve_lexical('PRIVATE')),1)
        grant.delete()
        self.assertEqual(engine.retrieve_lexical('PRIVATE'),[])
        self.assertEqual(self.client.post(f'/api/v1/index-versions/{index.index_id}/query/',{'query':'PRIVATE','mode':'lexical'},format='json').status_code,404)
        set_active_project(None)
        type(index).all_objects.filter(pk=index.pk).update(status='revoked')
        self.assertEqual(engine.retrieve_lexical('PRIVATE'),[])
