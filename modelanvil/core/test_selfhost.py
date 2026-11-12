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


import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from modelanvil.core.checks import INSECURE_DEFAULT_SECRET_KEY
from scripts import build_selfhost_release as builder
from scripts import install_selfhost

REPOSITORY=Path(__file__).resolve().parents[2]
INSTALL_SCRIPT=REPOSITORY/'scripts/install_selfhost.py'


def repository_default_values():
    """Every default or example value in the repository's Compose files, .env examples and CI service definitions."""
    sources=[*REPOSITORY.glob('compose*.y*ml'),*REPOSITORY.glob('deploy/*/compose*.y*ml'),*REPOSITORY.glob('deploy/*/docker-compose*.y*ml'),
        *REPOSITORY.glob('deploy/*/.env.example'),*REPOSITORY.glob('.github/workflows/*.y*ml')]
    values={INSECURE_DEFAULT_SECRET_KEY}
    for path in sources:
        text=path.read_text()
        values.update(re.findall(r'\$\{[A-Za-z0-9_]+:-([^}]*)\}',text))
        values.update(match[1].strip('\'"') for match in re.finditer(r'^\s*[A-Za-z0-9_]*(?:SECRET|PASSWORD|KEY)[A-Za-z0-9_]*\s*[:=][ \t]*(.*?)\s*$',text,re.MULTILINE))
    return sources,values


def release_fixture(directory,version='test1'):
    """A release whose controller is the real deploy/selfhost/modelanvil.py; the other payloads are fixture bytes."""
    directory.mkdir()
    for name in installer.FILES:(directory/name).write_bytes(b'qualified-fixture-bytes')
    shutil.copy2(REPOSITORY/'deploy/selfhost/modelanvil.py',directory/'modelanvil.py')
    installer.write_json(directory/'release.json',{'schema_version':'modelanvil.selfhost-release.v1','version':version,'architecture':'arm64','os':'linux',
        'images':{name:'sha256:'+digit*64 for name,digit in (('api','a'),('web','b'),('db','c'))},
        'files':{name:{'bytes':(directory/name).stat().st_size,'sha256':installer.sha(directory/name)} for name in installer.FILES}})
    return directory


# Answers only the controller's engine probes, refuses every other Docker operation and logs each call.
FAKE_DOCKER='''import json,sys
from pathlib import Path
config=json.loads(Path(__file__).with_name('fake-docker.json').read_text())
args=sys.argv[1:]
with open(config['log'],'a') as stream:stream.write(json.dumps(args)+'\\n')
if args[:2]==['--host','unix://'+config['socket']]:args=args[2:]
if args[:2]==['context','inspect']:print(json.dumps('unix://'+config['socket']))
elif args==['info','--format','{{json .ClientInfo.Plugins}}']:print(json.dumps([{'Name':'compose','Path':config['compose']}]))
elif args==['compose','version','--short']:print('2.40.0')
elif args==['info','--format','{{json .}}']:print(json.dumps({'OSType':'linux','MemTotal':8*1024**3,'Architecture':'aarch64'}))
else:sys.exit(1)
'''
ENGINE_PROBES=[['context','inspect','--format','{{json .Endpoints.docker.Host}}'],['info','--format','{{json .ClientInfo.Plugins}}'],
    ['compose','version','--short'],['info','--format','{{json .}}']]


class InstallScriptTests(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()

    def fake_engine(self):
        # Unix socket paths are limited to about 100 bytes, so the socket lives in a short directory.
        sockets=Path(tempfile.mkdtemp(prefix='ma-',dir='/tmp' if Path('/tmp').is_dir() else None));self.addCleanup(shutil.rmtree,sockets,True)
        listener=socket.socket(socket.AF_UNIX);self.addCleanup(listener.close);listener.bind(str(sockets/'engine.sock'))
        tools=self.root/'bin';tools.mkdir();docker=tools/'docker';program=tools/'fake_docker.py';program.write_text(FAKE_DOCKER)
        docker.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' -I '+shlex.quote(str(program))+' "$@"\n');docker.chmod(0o700)
        self.calls=self.root/'docker-calls.jsonl'
        (tools/'fake-docker.json').write_text(json.dumps({'log':str(self.calls),'socket':str(sockets/'engine.sock'),'compose':str(docker)}))
        self.engine_socket='unix://'+str(sockets/'engine.sock')
        return {**os.environ,'PATH':str(tools)+os.pathsep+os.environ.get('PATH','')}

    def docker_calls(self):
        calls=[json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return [call[2:] if call[:2]==['--host',self.engine_socket] else call for call in calls]

    def install(self,release,directory,env):
        return subprocess.run([sys.executable,str(INSTALL_SCRIPT),'--directory',str(directory),'--release',str(release),
            '--http-port','18080','--https-port','18443','--credentials-stdin'],input='{}',capture_output=True,text=True,env=env,timeout=120)

    def test_missing_release_directory_is_refused_before_any_controller_runs(self):
        empty=self.root/'not-a-release';empty.mkdir()
        for release,message in ((self.root/'missing','Release directory not found'),(empty,'Not a built release')):
            with patch.object(install_selfhost.subprocess,'run') as execute,patch('sys.stderr',new_callable=io.StringIO) as errors:
                code=install_selfhost.main(['--directory',str(self.root/'instance'),'--release',str(release)])
            self.assertEqual(code,2);self.assertIn(message,errors.getvalue());execute.assert_not_called()
        self.assertFalse((self.root/'instance').exists())

    def test_release_controller_receives_exactly_the_install_flags(self):
        release=release_fixture(self.root/'release');target=self.root/'instance';controller=str(release/'modelanvil.py')
        with patch.object(install_selfhost.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as execute:
            code=install_selfhost.main(['--directory',str(target),'--release',str(release),'--host','anvil.local','--bind','192.168.1.20',
                '--http-port','18080','--https-port','18443','--credentials-stdin'])
        self.assertEqual(code,0)
        execute.assert_called_once_with([sys.executable,controller,'install','--directory',str(target),'--release',str(release),
            '--host','anvil.local','--bind','192.168.1.20','--http-port','18080','--https-port','18443','--credentials-stdin'])
        # Omitted flags are left to the release controller's own defaults, and its exit status is the script's.
        with patch.object(install_selfhost.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as execute:
            code=install_selfhost.main(['--directory',str(target),'--release',str(release)])
        self.assertEqual(code,1)
        execute.assert_called_once_with([sys.executable,controller,'install','--directory',str(target),'--release',str(release)])

    def test_tampered_release_file_fails_the_install_through_the_controller_checksum(self):
        release=release_fixture(self.root/'release');env=self.fake_engine()
        # Control: the intact release passes every checksum and reaches its own image archive, which the fake engine refuses to load.
        intact=self.install(release,self.root/'intact',env)
        self.assertEqual(intact.returncode,1,intact.stderr);self.assertIn('Docker operation failed: load',intact.stderr)
        before=self.docker_calls()
        self.assertEqual(before[:4],ENGINE_PROBES);self.assertIn(['load','--input',str(self.root/'intact/release/images.tar')],before)
        self.assertFalse([call for call in before if call[0] in ('pull','build','buildx','login')])
        tampered=self.root/'tampered';shutil.copytree(release,tampered)
        raw=(tampered/'images.tar').read_bytes();(tampered/'images.tar').write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        self.assertEqual((tampered/'images.tar').stat().st_size,len(raw))
        refused=self.install(tampered,self.root/'refused',env)
        self.assertEqual(refused.returncode,1);self.assertIn('Release checksum failed: images.tar',refused.stderr)
        self.assertFalse((self.root/'refused').exists())
        # After the engine probes nothing was inspected, loaded, pulled or built.
        self.assertEqual(self.docker_calls()[len(before):],ENGINE_PROBES)

    def test_two_installs_generate_different_secrets_that_match_no_repository_default(self):
        release=release_fixture(self.root/'release');options=SimpleNamespace(host='localhost',bind='127.0.0.1',http_port=18080,https_port=18443)
        created={'tenant':'tenant-uuid','project':'project-uuid','worker_id':7,'pool':'pool-uuid','runner_manifest':'manifest-uuid'}
        docker=lambda args,**kwargs:json.dumps(created).encode() if 'initialize_selfhost' in args else b''
        generated=[]
        for name in ('first','second'):
            instance=installer.Instance.__new__(installer.Instance);instance.root=self.root/name;instance.state=None
            with patch.object(instance,'call',side_effect=docker),patch.object(instance,'load_images') as load,patch.object(instance,'start',return_value={'ready':True}):
                self.assertEqual(instance.install(release,{},options),{'ready':True})
            load.assert_called_once();generated.append(instance.private_secrets(instance.root/'.env'))
        sources,defaults=repository_default_values()
        self.assertIn(REPOSITORY/'compose.yaml',sources);self.assertIn(REPOSITORY/'deploy/compose/.env.example',sources)
        self.assertTrue({'local-dev-only','local-only-change-before-deploy','modelanvil_secret','change-me-in-production-secure-random-token','modelanvil'}<=defaults)
        first,second=generated
        for key in ('DJANGO_SECRET_KEY','POSTGRES_PASSWORD'):
            self.assertNotEqual(first[key],second[key])
            for value in (first[key],second[key]):self.assertNotIn(value,defaults)
        self.assertNotEqual(first['DJANGO_SECRET_KEY'],first['POSTGRES_PASSWORD'])


class ReleaseVersionTests(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()

    def build(self,*arguments,architecture='aarch64',porcelain=''):
        """Run the builder with git and the engine stubbed; an existing image tag stops it before any image build."""
        engines=[]
        class Engine:
            def __init__(self,root):engines.append(root);self.docker=['docker','--host','unix:///fixture.sock'];self.env={}
            def call(self,args,**kwargs):return json.dumps({'OSType':'linux','Architecture':architecture}).encode()
        git=lambda args,**kwargs:porcelain if args[:2]==['git','status'] else 'f'*40+'\n'
        with patch.object(builder,'Instance',Engine),patch.object(builder.subprocess,'check_output',side_effect=git), \
                patch.object(builder.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as execute:
            with self.assertRaises(ValueError) as refused:builder.main(list(arguments))
        return str(refused.exception),[call.args[0] for call in execute.call_args_list],engines

    def test_version_file_is_one_line_the_builder_and_controller_accept(self):
        text=builder.VERSION_FILE.read_text();version=text.rstrip('\n')
        self.assertEqual(text,version+'\n');self.assertNotIn('\n',version)
        self.assertEqual(builder.release_version(None),version)
        self.assertEqual(installer.release(release_fixture(self.root/'release',version=version))['version'],version)

    def test_builder_names_the_release_from_the_version_file_unless_version_is_passed(self):
        version=builder.VERSION_FILE.read_text().strip()
        for arguments,expected in (((),version),(('--version','explicit-2'),'explicit-2')):
            output=self.root/('release-'+expected)
            error,commands,_=self.build('--output',str(output),*arguments)
            self.assertIn('already uses this immutable release version',error)
            self.assertEqual(commands,[['docker','--host','unix:///fixture.sock','image','inspect','modelanvil-selfhost-api:'+expected]])

    def test_builder_refusals_still_stop_before_any_image_build(self):
        existing=self.root/'existing';existing.mkdir()
        error,commands,engines=self.build('--output',str(existing))
        self.assertIn('new output directory',error);self.assertEqual((commands,engines),([],[]))
        error,commands,engines=self.build('--output',str(self.root/'dirty'),porcelain=' M deploy/selfhost/VERSION\n')
        self.assertIn('Commit the release sources',error);self.assertEqual((commands,engines),([],[]));self.assertFalse((self.root/'dirty').exists())
        error,commands,engines=self.build('--output',str(self.root/'amd64'),architecture='x86_64')
        self.assertIn('Linux arm64 only',error);self.assertEqual(commands,[]);self.assertEqual(len(engines),1);self.assertFalse((self.root/'amd64').exists())
        error,commands,engines=self.build('--output',str(self.root/'upper'),'--version','Release-1')
        self.assertIn('lowercase release version',error);self.assertEqual((commands,engines),([],[]))
        for content,message in (('Not A Version\n','lowercase release version'),('0.1.0\n0.2.0\n','exactly one line'),('','exactly one line')):
            file=self.root/'VERSION';file.write_text(content)
            with patch.object(builder,'VERSION_FILE',file):error,commands,engines=self.build('--output',str(self.root/'bad-file'))
            self.assertIn(message,error);self.assertEqual((commands,engines),([],[]))
