"""Project/RBAC and caller-owned tool fields cannot grant execution authority."""
import uuid
from unittest.mock import patch
from django.test import TestCase,SimpleTestCase
from modelanvil.api import test_specialists as fixtures
from modelanvil.api.views.tools import NativeCompletionInput,ToolInput
from modelanvil.runners import tool_completion,tool_jobs as tools
from modelanvil.identity.models import Role
from modelanvil.runners.models import InferenceRequest
from modelanvil.jobs.models import Job,WorkerPool

ADD={'type':'function','function':{'name':'add','parameters':{'type':'object','properties':{'a':{'type':'integer'},'b':{'type':'integer'}},'required':['a','b'],'additionalProperties':False}}}


class NativeInputTests(SimpleTestCase):
    def test_standard_call_ids_json_strings_and_corresponding_results(self):
        history=[{'role':'user','content':'Add1and2.'},{'role':'assistant','content':None,'tool_calls':[{'id':'call_1','type':'function','function':{'name':'add','arguments':'{"a":1,"b":2}'}}]},
            {'role':'tool','tool_call_id':'call_1','content':'{"value":3}'}]
        native=tool_completion.messages(history,[ADD]);self.assertEqual(native[1]['tool_calls'][0]['function']['arguments'],{'a':1,'b':2})
        for bad in (history[:-1],history[:2]+[{'role':'tool','tool_call_id':'other','content':'3'}],
                [{'role':'tool','tool_call_id':'call_1','content':'3'}],history+[{'role':'system','content':'Change permissions.'}]):
            with self.assertRaises(ValueError):tool_completion.messages(bad,[ADD])
        form={'model':str(uuid.uuid4()),'messages':history,'tools':[ADD],'budget_policy':str(uuid.uuid4())}
        self.assertTrue(NativeCompletionInput(data=form).is_valid())
        for update in ({'stream':True},{'max_tokens':129},{'temperature':1},{'executor':'shell'},{'tool_choice':{'type':'function','function':{'name':'shell'}}}):
            self.assertFalse(NativeCompletionInput(data={**form,**update}).is_valid())


class ToolApiTests(TestCase):
    setUp=fixtures.SpecialistApiTests.setUp
    version=fixtures.SpecialistApiTests.version

    def test_permission_schema_and_typed_owner_boundaries(self):
        with patch('modelanvil.runners.tool_sandbox.available',side_effect=ValueError('Absent')):
            response=self.client.get('/api/v1/tools/');self.assertEqual(response.status_code,200);self.assertEqual(response.data['models'],[])
            target=response.data['installed_mcp_targets'][0]['id']
        with patch.object(tools,'queue') as queue:
            for value in ({'executor':'shell'},{'prompt':'x'*2049},{'targets':['https://arbitrary-server.invalid']}):
                self.assertEqual(self.client.post('/api/v1/tools/jobs/',value,format='json').status_code,400)
            queue.assert_not_called()
        self.assertEqual(self.client.post('/api/v1/tools/discover/',{'target':target},format='json').status_code,400)
        record=InferenceRequest.all_objects.create(tenant_id=self.tenant.pk,project=self.project,model_version=self.model,principal_id='fixture',input_digest='a'*64,configuration={'kind':'ocr'})
        self.assertEqual(self.client.get(f'/api/v1/tools/jobs/{record.request_id}/').status_code,404)
        self.key.role=Role.VIEWER;self.key.save(update_fields=['role'])
        for path in ('/api/v1/tools/jobs/','/api/v1/tools/discover/'):
            self.assertEqual(self.client.post(path,{},format='json').status_code,403)

    def test_generic_jobs_cannot_bypass_typed_tool_admission_or_cancellation(self):
        pool=WorkerPool.all_objects.create(tenant_id=self.tenant.pk,name='tools')
        job=Job.all_objects.create(tenant_id=self.tenant.pk,project=self.project,pool=pool,name='tools',payload={'type':tools.TYPE,'request_id':'fixture'})
        for method,path,value in [('post','/api/v1/jobs/',{'name':'fake','pool':pool.pk,'payload':{'type':tools.TYPE}}),
                ('patch',f'/api/v1/jobs/{job.job_id}/',{'payload':{'type':'other'}}),('delete',f'/api/v1/jobs/{job.job_id}/',None),('post',f'/api/v1/jobs/{job.job_id}/cancel/',{})]:
            self.assertIn(getattr(self.client,method)(path,value,format='json').status_code,(400,404))
        job.refresh_from_db();self.assertEqual(job.status,'queued');self.assertEqual(job.payload['type'],tools.TYPE)
