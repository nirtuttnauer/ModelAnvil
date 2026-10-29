"""Fresh initialization and bounded local import never replace existing identity or execute model code."""
import base64
import io
import json
import secrets
from types import SimpleNamespace
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase,override_settings
from django.conf import settings
import tempfile
from modelanvil.identity.models import Tenant,User,ApiKey,Membership
from modelanvil.core.models import ProjectPrivacyPolicy
from modelanvil.runners.models import ModelVersion
from modelanvil.runners.training import general_runtime as runtime
from modelanvil.runners.training.general_transformer import GeneralTransformer
from modelanvil.runners.training.engine import pack_safetensors


class SelfhostBoundaryTests(TestCase):
    def command(self,command_name,value,**kwargs):
        out=io.StringIO();raw=value if isinstance(value,bytes) else json.dumps(value).encode()
        with patch('sys.stdin',SimpleNamespace(buffer=io.BytesIO(raw))):call_command(command_name,stdout=out,**kwargs)
        return json.loads(out.getvalue())

    def initialize(self):
        # Generated at runtime so the suite does not store a fixture password.
        self.fixture_password=secrets.token_urlsafe(24)
        return self.command('initialize_selfhost',{'email':'owner@example.test','password':self.fixture_password,'name':'Private workspace'})

    def test_initialization_is_empty_private_offline_and_cannot_reset_existing_accounts(self):
        created=self.initialize();self.assertEqual(created['models_created'],0);self.assertEqual(created['api_keys_created'],0)
        self.assertFalse(ModelVersion.all_objects.exists());self.assertFalse(ApiKey.objects.exists())
        self.assertEqual(Membership.objects.get().role,'owner');self.assertTrue(ProjectPrivacyPolicy.all_objects.get().offline)
        self.assertNotIn(self.fixture_password,json.dumps(created))
        self.assertTrue(User.objects.get().check_password(self.fixture_password))
        with self.assertRaisesRegex(CommandError,'fresh database'):self.initialize()
        self.assertEqual(Tenant.objects.count(),1)

    def test_invalid_initialization_never_creates_partial_identity(self):
        for value in (b'x'*8193,{'email':'invalid','password':'short','name':'A'}, {'email':'a@example.test','password':'123456789012','name':'A'}):
            with self.assertRaises(CommandError):self.command('initialize_selfhost',value)
            self.assertFalse(Tenant.objects.exists());self.assertFalse(User.objects.exists())

    def test_reference_import_verifies_tensors_tokenizer_and_dimensions_before_registration(self):
        created=self.initialize();tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with override_settings(MODELANVIL={**settings.MODELANVIL,'artifact_root':tmp.name,'artifact_backend':'filesystem'}):
            model=GeneralTransformer(vocab_size=260,n_layer=1,n_head=1,n_embd=4,context_window=32,seed=123)
            raw,manifest=pack_safetensors(model.export_tensors())
            bundle={'config.json':{'runtime':runtime.RUNTIME_ID,'vocab_size':260,'n_layer':1,'n_head':1,'n_embd':4,'context_window':32},
                'tokenizer_config.json':{'kind':'byte-v1','vocab_size':260,'pad_id':0,'bos_id':1,'eos_id':2,'unk_id':3},
                'model.safetensors.b64':base64.b64encode(raw).decode(),'weights_manifest.json':manifest}
            args={'tenant_id':created['tenant'],'project_id':created['project'],'name':'Imported reference','license':'MIT'}
            for bad in ({**bundle,'weights_manifest.json':{'weights_sha256':'f'*64}}, {**bundle,'tokenizer_config.json':{'kind':'untrusted'}},
                    {**bundle,'config.json':{**bundle['config.json'],'n_layer':10**9}}, {**bundle,'executor':'shell'}):
                with self.assertRaises(CommandError):self.command('import_cpu_reference',bad,**args)
                self.assertFalse(ModelVersion.all_objects.exists())
            result=self.command('import_cpu_reference',bundle,example_worker_id=created['worker_id'],**args)
            self.assertIn('launch',result);self.assertEqual(ModelVersion.all_objects.count(),1)
            self.assertFalse(ModelVersion.all_objects.get().source_training_run.exists())
            with self.assertRaises(CommandError):self.command('import_cpu_reference',bundle,**args)


from pathlib import Path
from django.test import SimpleTestCase
from deploy.selfhost import modelanvil as installer


class InstallerBoundaryTests(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def package(self):
        directory=self.root/'release';directory.mkdir()
        for name in installer.FILES:(directory/name).write_bytes(b'qualified-fixture-bytes')
        manifest={'schema_version':'modelanvil.selfhost-release.v1','version':'test1','architecture':'arm64',
            'images':{k:'sha256:'+'a'*64 for k in ('api','web','db')},
            'files':{name:{'bytes':(directory/name).stat().st_size,'sha256':installer.sha(directory/name)} for name in installer.FILES}}
        installer.write_json(directory/'release.json',manifest);return directory,manifest

    def instance(self,path):
        instance=installer.Instance.__new__(installer.Instance);instance.root=path;instance.state={'compose_project':'owned-test-project','project':'workspace-uuid','worker_id':1}
        return instance

    def test_release_corruption_and_unexpected_files_cannot_enter_installation(self):
        directory,manifest=self.package();self.assertEqual(installer.release(directory)['version'],'test1')
        (directory/'reference.json').write_bytes(b'changed')
        with self.assertRaisesRegex(installer.InstallError,'checksum'):installer.release(directory)
        manifest['files']['../../outside']={'bytes':1,'sha256':'a'*64};installer.write_json(directory/'release.json',manifest)
        with self.assertRaises(installer.InstallError):installer.release(directory)
        live=self.root/'live';live.mkdir();(live/'user-data').write_text('retain')
        with self.assertRaisesRegex(installer.InstallError,'new directory'):self.instance(live).install(directory,{},None)
        self.assertEqual((live/'user-data').read_text(),'retain')

    def test_environment_cannot_inject_compose_values_or_confuse_workspace_and_docker_ids(self):
        root=self.root/'instance';root.mkdir();instance=self.instance(root)
        manifest={'version':'test1','images':{k:'sha256:'+'a'*64 for k in ('api','web','db')}}
        for host in ('localhost\nEVIL=1','https://name','name/secret','name:80'):
            with self.assertRaises(installer.InstallError):instance.environment(manifest,host=host,bind='127.0.0.1',http_port=18080,https_port=18443)
        instance.environment(manifest,host='localhost',bind='127.0.0.1',http_port=18080,https_port=18443)
        self.assertEqual(instance.state['project'],'workspace-uuid');self.assertEqual(instance.state['compose_project'],'owned-test-project')
        self.assertEqual((root/'.env').stat().st_mode&0o777,0o600)
        with patch.object(instance,'call',return_value=b'') as execute:
            instance.compose('ps');self.assertIn('owned-test-project',execute.call_args.args[0]);self.assertNotIn('workspace-uuid',execute.call_args.args[0])

    def test_unsafe_backup_archive_is_refused_before_creating_a_restore_target(self):
        import tarfile
        directory,manifest=self.package();backup=self.root/'backup';backup.mkdir()
        for name in ('database.dump','.env','instance.json'):(backup/name).write_bytes(b'private fixture')
        with tarfile.open(backup/'artifacts.tar','w') as archive:
            member=tarfile.TarInfo('../../outside');member.size=1;archive.addfile(member,io.BytesIO(b'x'))
        installer.write_json(backup/'backup.json',{'schema_version':'modelanvil.selfhost-backup.v1','release':'test1',
            'files':{name:installer.sha(backup/name) for name in ('database.dump','artifacts.tar','.env','instance.json')}})
        target=self.root/'restored';instance=self.instance(target)
        with self.assertRaisesRegex(installer.InstallError,'unsafe path'):instance.restore(backup,directory,None)
        self.assertFalse(target.exists())

    def test_failed_quiescence_check_restarts_the_original_installation(self):
        root=self.root/'instance';root.mkdir();instance=self.instance(root)
        with patch.object(instance,'compose',side_effect=[b'',installer.InstallError('active jobs')]),patch.object(instance,'start') as restart:
            with self.assertRaises(installer.InstallError):instance.backup(self.root/'backup',restart=False)
            restart.assert_called_once()

    def test_compose_plugin_is_exposed_without_forwarding_host_docker_credentials(self):
        import os
        import stat
        binary=self.root/'installed-docker-compose';binary.write_text('fixture');binary.chmod(0o700)
        replies=[SimpleNamespace(returncode=0,stdout=b'"unix:///installed/docker.sock"'),
            SimpleNamespace(returncode=0,stdout=json.dumps([{'Name':'compose','Path':str(binary)}]).encode()),
            SimpleNamespace(returncode=0,stdout=b'2.42.0'),SimpleNamespace(returncode=0,stdout=b'{"OSType":"linux","MemTotal":8589934592,"Architecture":"aarch64"}')]
        real_stat=os.stat
        def socket_stat(path,*args,**kwargs):
            if str(path)=='/installed/docker.sock':return SimpleNamespace(st_mode=stat.S_IFSOCK)
            return real_stat(path,*args,**kwargs)
        with patch.dict(os.environ,{'DOCKER_HOST':'tcp://unreviewed.example:2375','DOCKER_AUTH_CONFIG':'private-fixture'}), \
                patch.object(installer.subprocess,'run',side_effect=replies) as execute,patch.object(installer.os,'stat',side_effect=socket_stat):
            instance=installer.Instance(self.root/'new-instance')
            self.addCleanup(instance.temporary.cleanup)
            plugin=Path(instance.temporary.name)/'cli-plugins/docker-compose';self.assertEqual(plugin.resolve(),binary.resolve())
            for call in execute.call_args_list:
                self.assertNotIn('DOCKER_HOST',call.kwargs['env']);self.assertNotIn('DOCKER_AUTH_CONFIG',call.kwargs['env'])
            self.assertEqual(instance.env['DOCKER_CONFIG'],instance.temporary.name)

    def test_installation_does_not_silently_emulate_a_different_cpu_architecture(self):
        instance=self.instance(self.root/'instance');instance.architecture='amd64'
        with patch.object(instance,'call') as command:
            with self.assertRaisesRegex(installer.InstallError,'emulation'):instance.load_images({'architecture':'arm64','images':{}})
            command.assert_not_called()
