"""Operation-selection fixtures are not hardware/model qualification."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase,TestCase,override_settings
from rest_framework.test import APIClient
from modelanvil.runners import accelerator_support as support
from modelanvil.runners.training import hf_runtime,cpu_hf_runtime
from modelanvil.identity.models import Tenant,ApiKey,Role,generate_api_key

class OperationCompatibilityTests(SimpleTestCase):
    def test_invalid_device_precision_quantization_and_offload_refuse_before_probe(self):
        choices=[('full_sft','auto',{}),('full_sft','mps:0',{'precision':'fp16'}),
            ('full_sft','cpu',{'offload':True}),('full_sft','cpu',{'quantization':'int4'}),
            ('qlora_adapter','cuda:0',{'quantization':'int4'}),('text_inference','xpu:0',{}),('unknown','cpu',{})]
        with patch.object(support,'inventory',side_effect=AssertionError('Unexpected backend probe')):
            for operation,device,options in choices:
                row=support.inspect(operation,device,**options)
                self.assertFalse(row['installed_compatible']);self.assertFalse(row['model_loaded']);self.assertFalse(row['tensors_created'])

    def test_missing_exact_dependency_pin_refuses_before_device_probe(self):
        with patch.object(hf_runtime,'require_packages',side_effect=ValueError('Install exact pinned runtime.')),patch.object(hf_runtime,'observed_device') as observed:
            row=support.inspect('full_sft','mps:0')
        self.assertFalse(row['installed_compatible']);self.assertIn('pinned',row['reason']);observed.assert_not_called()

    def test_mps_fallback_is_not_reported_as_gpu_compatibility(self):
        with patch.dict('os.environ',{'PYTORCH_ENABLE_MPS_FALLBACK':'1'}),patch.object(hf_runtime,'require_packages'),patch.object(hf_runtime,'observed_device') as observed:
            row=support.inspect('full_sft','mps:0')
        self.assertFalse(row['installed_compatible']);self.assertIn('CPU kernel fallback',row['reason']);observed.assert_not_called()

    def test_runtime_contract_and_capacity_are_checked_without_recipe_substitution(self):
        with patch.object(cpu_hf_runtime,'CONTRACT',{'recipes':['full_sft']}):
            row=support.inspect('lora_adapter','cpu')
        self.assertFalse(row['installed_compatible']);self.assertIn('absent',row['reason'])
        with patch.object(cpu_hf_runtime,'require_packages'),patch('modelanvil.runners.training.hardware.total_memory_bytes',return_value=1024):
            row=support.inspect('full_sft','cpu')
        self.assertFalse(row['installed_compatible']);self.assertIn('memory',row['reason'])

    def test_metadata_installation_does_not_hide_a_broken_cpu_framework_import(self):
        with patch.object(cpu_hf_runtime,'require_packages'),patch('modelanvil.runners.training.hardware.total_memory_bytes',return_value=32*1024**3):
            row=support.inspect('full_sft','cpu',observed={'framework':{'version':None}})
        self.assertFalse(row['installed_compatible']);self.assertIn('imported CPU tensor framework',row['reason'])

    def test_compatible_backend_fixture_does_not_become_model_qualification(self):
        device={'device':{'id':'rocm:0','backend':'rocm','torch_device':'cuda:0','vendor':'AMD'}}
        with patch.object(hf_runtime,'require_packages'),patch.object(hf_runtime,'observed_device',return_value=device),patch('modelanvil.runners.training.hardware.total_memory_bytes',return_value=32*1024**3):
            row=support.inspect('full_sft','rocm:0')
        self.assertTrue(row['installed_compatible']);self.assertEqual(row['observed_device']['device']['vendor'],'AMD')
        self.assertFalse(row['recipe_changed']);self.assertFalse(row['cpu_fallback']);self.assertFalse(row['model_qualified']);self.assertFalse(row['production_qualified'])

@override_settings(ALLOWED_HOSTS=['testserver'])
class OperationSupportHTTPTests(TestCase):
    def test_authenticated_read_only_explicit_selection_and_duplicate_parameter_refusal(self):
        client=APIClient();self.assertEqual(client.get('/api/v1/compute-support/').status_code,401)
        tenant=Tenant.objects.create(slug='support-test',name='Support test');secret,hashed=generate_api_key()
        ApiKey.objects.create(tenant=tenant,name='Support viewer',role=Role.VIEWER,secret_hash=hashed)
        client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        response=client.get('/api/v1/compute-support/?operation=full_sft&device=auto')
        self.assertEqual(response.status_code,200);self.assertFalse(response.json()['installed_compatible']);self.assertEqual(response['Cache-Control'],'no-store')
        for query in ['operation=full_sft&device=cpu&device=mps:0','operation=full_sft','operation=full_sft&device=cpu&launch=true']:
            self.assertEqual(client.get('/api/v1/compute-support/?'+query).status_code,400)
        from modelanvil.jobs.models import Job
        from modelanvil.budgets.models import BudgetReservation
        self.assertEqual(Job.all_objects.count(),0);self.assertEqual(BudgetReservation.all_objects.count(),0)
