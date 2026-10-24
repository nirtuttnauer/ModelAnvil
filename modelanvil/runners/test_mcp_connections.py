"""Project grants, current credentials and offline gates precede MCP dispatch."""
import json
from unittest.mock import patch
from django.test import TestCase,override_settings
from modelanvil.runners import mcp_connections as mcp
from modelanvil.identity.models import Tenant, Team, Project
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.core.models import ProjectPrivacyPolicy


class InstalledConnectionTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(slug='mcp-guards',name='MCP guards')
        set_active_tenant(self.tenant.pk);self.addCleanup(set_active_tenant,None)
        team=Team.objects.create(tenant_id=self.tenant.pk,name='Team',slug='mcp')
        self.project=Project.objects.create(tenant_id=self.tenant.pk,team=team,name='A',slug='a')
        self.other=Project.objects.create(tenant_id=self.tenant.pk,team=team,name='B',slug='b')

    def test_local_mcp_requires_explicit_project_grant_and_can_operate_offline(self):
        target=mcp.installed_targets(self.tenant.pk,self.project.pk)[0]
        with self.assertRaisesRegex(ValueError,'explicitly enabled'):mcp.discover(target['id'],self.tenant.pk,self.project.pk)
        policy=ProjectPrivacyPolicy.all_objects.create(tenant_id=self.tenant.pk,project=self.project,offline=True,mcp_targets=[target['id']])
        listing=mcp.discover(target['id'],self.tenant.pk,self.project.pk)
        result=mcp.call(target['id'],self.tenant.pk,self.project.pk,name='add',arguments={'a':17,'b':25},
            catalog_digest=listing['result']['catalog_digest'],configuration_signature=listing['configuration_signature'])
        self.assertEqual(result['result']['structured_content'],{'value':42})
        with self.assertRaises(ValueError):mcp.resolve(target['id'],self.tenant.pk,self.other.pk)
        policy.mcp_targets=[];policy.save(update_fields=['mcp_targets'])
        with self.assertRaises(ValueError):mcp.call(target['id'],self.tenant.pk,self.project.pk,name='add',arguments={'a':17,'b':25},
            catalog_digest=listing['result']['catalog_digest'],configuration_signature=listing['configuration_signature'])

    def test_host_credentials_never_enter_public_targets_and_rotation_refuses_dispatch(self):
        scope=f'{self.tenant.pk}:{self.project.pk}'
        server={'name':'Installed fixture','endpoint':'https://example.invalid/mcp','allowed_tools':['add'],'credential_id':'read-only','read_only':True}
        with override_settings(MODELANVIL_MCP_SERVERS={scope:{'fixture':server}},MODELANVIL_MCP_SERVER_KEYS={scope:{'read-only':'private-fixture-value'}}):
            values=mcp.configured(self.tenant.pk,self.project.pk);remote=next(v for v in values.values() if v['kind']=='http')
            self.assertNotIn('private-fixture-value',json.dumps(mcp.installed_targets(self.tenant.pk,self.project.pk)))
            policy=ProjectPrivacyPolicy.all_objects.create(tenant_id=self.tenant.pk,project=self.project,mcp_targets=[remote['id']])
            signature=remote['signature']
            with override_settings(MODELANVIL_MCP_SERVER_KEYS={scope:{'read-only':'rotated-fixture-value'}}),patch.object(mcp,'_broker') as broker:
                with self.assertRaisesRegex(ValueError,'credential changed'):mcp.call(remote['id'],self.tenant.pk,self.project.pk,name='add',arguments={'a':1,'b':2},catalog_digest='f'*64,configuration_signature=signature)
                broker.assert_not_called()
            policy.offline=True;policy.save(update_fields=['offline'])
            with self.assertRaisesRegex(ValueError,'offline'):mcp.resolve(remote['id'],self.tenant.pk,self.project.pk)
            with override_settings(MODELANVIL_MCP_SERVERS={scope:{'fixture':{**server,'read_only':False}}}):
                self.assertFalse(next(v for v in mcp.installed_targets(self.tenant.pk,self.project.pk) if v['kind']=='http')['available'])
                with self.assertRaises(ValueError):mcp.resolve(remote['id'],self.tenant.pk,self.project.pk)

    def test_one_missing_customer_credential_does_not_hide_the_local_tool_profile(self):
        scope=f'{self.tenant.pk}:{self.project.pk}'
        with override_settings(MODELANVIL_MCP_SERVERS={scope:{'fixture':{'name':'Customer target','endpoint':'https://example.invalid/mcp',
                'allowed_tools':['add'],'credential_id':'missing','read_only':True}}},MODELANVIL_MCP_SERVER_KEYS={}):
            values=mcp.installed_targets(self.tenant.pk,self.project.pk)
            self.assertTrue(next(v for v in values if v['kind']=='builtin_math')['available'])
            self.assertFalse(next(v for v in values if v['kind']=='http')['available'])

    def test_invalid_remote_configuration_does_not_disable_local_tools_or_privacy(self):
        from modelanvil.core.privacy import project_policy
        scope=f'{self.tenant.pk}:{self.project.pk}'
        with override_settings(MODELANVIL_MCP_SERVERS={scope:['invalid']}):
            policy=project_policy(self.tenant.pk,self.project.pk)
            self.assertTrue(next(v for v in policy['installed_mcp_targets'] if v['kind']=='builtin_math')['available'])
            self.assertFalse(next(v for v in policy['installed_mcp_targets'] if v['kind']=='http')['available'])
