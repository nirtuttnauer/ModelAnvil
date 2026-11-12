"""The self-host drill runs only backup, upgrade and restore, in that order, and stops when any checked state changes.

The controller process and Docker are mocked; the in-container probe also runs for real against the test database.
"""
import base64
import copy
import io
import json
import secrets
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from scripts import drill_selfhost as drill

OLD_IMAGES={'api':'sha256:'+'a'*64,'web':'sha256:'+'b'*64,'db':'sha256:'+'c'*64}
NEW_IMAGES={'api':'sha256:'+'d'*64,'web':'sha256:'+'e'*64,'db':'sha256:'+'c'*64}
HEALTHY={'health':{'status':200,'body':{'status':'ok'}},'ready':{'status':200,'body':{'status':'ready'}}}


def release(directory,version,images):
    directory.mkdir(parents=True)
    (directory/'modelanvil.py').write_text('# controller fixture; the drill never imports it\n')
    (directory/'release.json').write_text(json.dumps({'schema_version':'modelanvil.selfhost-release.v1','version':version,'images':images,'source_revision':'f'*40}))
    return directory


def installed(directory,secret,version='0.1.0',images=OLD_IMAGES,project='modelanvil-local-0123456789ab',port=18443):
    directory.mkdir(parents=True)
    release(directory/'release',version,images)
    (directory/'instance.json').write_text(json.dumps({'schema_version':'modelanvil.selfhost-instance.v1','compose_project':project,
        'version':version,'origin':'https://localhost:%d'%port,'project':'workspace-uuid','worker_id':1}))
    (directory/'.env').write_text('DJANGO_SECRET_KEY='+secret+'\nPOSTGRES_PASSWORD='+secret[::-1]+'\n')
    return directory


def recorded_state(version='0.1.0'):
    return {'schema_version':drill.SNAPSHOT_SCHEMA,'taken_at':'2026-11-12T00:00:00+00:00','version':version,'prompt':'a tiny','max_tokens':8,
        'database_vendor':'postgresql','server_version':'17.6','pgvector':'0.8.1','health':copy.deepcopy(HEALTHY),
        'rows':{'artifacts_artifact':7,'runners_modelversion':2,'django_migrations':240,'jobs_job':1,'rag_chunk':0},
        'artifacts':[{'artifact_id':'artifact-%d'%n,'sha256':str(n)*64,'byte_size':10+n,'stored_sha256':str(n)*64,'stored_bytes':10+n} for n in range(1,4)],
        'artifact_files':[{'path':'tenant/artifact-%d'%n,'bytes':10+n,'sha256':str(n)*64} for n in range(1,4)],
        'models':[{'model_version_id':'base','generated_token_ids':[104,105,2]},{'model_version_id':'trained','generated_token_ids':[33,33,33,33]}]}


class DrillCommandTests(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        # Generated at runtime so no fixture secret is stored; the drill must never copy it into its record.
        self.secret=secrets.token_urlsafe(32)
        self.instance=installed(self.root/'instance',self.secret)
        self.previous=release(self.root/'releases/0.1.0',version='0.1.0',images=OLD_IMAGES)
        self.new=release(self.root/'releases/0.1.1',version='0.1.1',images=NEW_IMAGES)
        self.commands=[];self.snapshots=[];self.codes={};self.changes={}

    def controller(self,command,**kwargs):
        """Stands in for the release controllers: creates what each subcommand would and prints its JSON result."""
        self.commands.append(command);action=command[2];value=lambda flag:Path(command[command.index(flag)+1])
        if self.codes.get(action):
            return SimpleNamespace(returncode=self.codes[action],stdout=b'',stderr=b'ModelAnvil: Release checksum failed: images.tar\n')
        if action=='backup':
            value('--output').mkdir(parents=True);(value('--output')/'backup.json').write_text(json.dumps({'release':'0.1.0'}))
            result={'backup':str(value('--output')),'verified_checksums':4,'contains_private_identity_and_credentials':True}
        elif action=='upgrade':
            value('--backup').mkdir(parents=True);(value('--backup')/'backup.json').write_text(json.dumps({'release':'0.1.0'}))
            state=json.loads((value('--directory')/'instance.json').read_text());state['version']='0.1.1'
            (value('--directory')/'instance.json').write_text(json.dumps(state))
            result={'origin':'https://localhost:18443','ready':True,'version':'0.1.1','production_qualified':False,'backup':str(value('--backup'))}
        elif action=='restore':
            installed(value('--directory'),self.secret,project='modelanvil-local-ba9876543210',port=28443)
            result={'origin':'https://localhost:28443','ready':True,'version':'0.1.0','production_qualified':False}
        else:raise AssertionError('unexpected controller subcommand '+action)
        return SimpleNamespace(returncode=0,stdout=json.dumps(result).encode(),stderr=b'')

    def snapshot(self,directory,prompt,max_tokens):
        stage=('baseline','after_backup','after_upgrade','after_rollback')[len(self.snapshots)]
        self.snapshots.append((Path(directory),prompt,max_tokens))
        value=recorded_state(json.loads((Path(directory)/'instance.json').read_text())['version'])
        self.changes.get(stage,lambda state:None)(value)
        return value

    def arguments(self,**overrides):
        values={'directory':self.instance,'previous_release':self.previous,'release':self.new,'backup':self.root/'backups/drill',
            'upgrade_backup':self.root/'backups/upgrade','rollback_directory':self.root/'rollback','record':self.root/'record'}
        values.update(overrides);arguments=['run']
        for name,path in values.items():arguments+=['--'+name.replace('_','-'),str(path)]
        return arguments+['--rollback-http-port','28080','--rollback-https-port','28443']

    def drill(self,arguments):
        with patch.object(drill.subprocess,'run',side_effect=self.controller),patch.object(drill,'snapshot',side_effect=self.snapshot), \
                patch('sys.stdout',new_callable=io.StringIO) as out,patch('sys.stderr',new_callable=io.StringIO) as errors:
            code=drill.main(arguments)
        return code,out.getvalue(),errors.getvalue()

    def report(self):
        return json.loads((self.root/'record/report.json').read_text())

    def test_drill_backs_up_upgrades_then_restores_the_upgrade_backup_with_the_previous_release(self):
        code,out,errors=self.drill(self.arguments())
        self.assertEqual(code,0,errors)
        python=sys.executable;instance=str(self.instance);upgrade_backup=str(self.root/'backups/upgrade')
        self.assertEqual(self.commands,[
            [python,str(self.instance/'release/modelanvil.py'),'backup','--directory',instance,'--output',str(self.root/'backups/drill')],
            [python,str(self.new/'modelanvil.py'),'upgrade','--directory',instance,'--release',str(self.new),'--backup',upgrade_backup],
            [python,str(self.previous/'modelanvil.py'),'restore','--directory',str(self.root/'rollback'),'--backup',upgrade_backup,
                '--release',str(self.previous),'--http-port','28080','--https-port','28443']])
        # Rollback is a restore into a new directory, never a write into the upgraded instance or a new subcommand.
        self.assertNotIn(instance,self.commands[2]);self.assertEqual([c[2] for c in self.commands],['backup','upgrade','restore'])
        self.assertEqual([s[0] for s in self.snapshots],[self.instance,self.instance,self.instance,self.root/'rollback'])
        self.assertEqual({(s[1],s[2]) for s in self.snapshots},{('a tiny',8)})
        report=self.report()
        self.assertTrue(report['passed']);self.assertIs(report['production_qualified'],False)
        self.assertEqual([(s['step'],s['exit_code']) for s in report['steps']],[('backup',0),('upgrade',0),('rollback',0)])
        self.assertEqual([s['command'][0] for s in report['steps']],['python3']*3)
        self.assertEqual(set(report['checks']),{'after_backup','after_upgrade','after_rollback'})
        self.assertTrue(all(check['equal'] for check in report['checks'].values()))
        rollback=report['rollback'];self.assertEqual(rollback['backup'],upgrade_backup);self.assertEqual(rollback['backup_release'],'0.1.0')
        self.assertGreaterEqual(rollback['backup_age_seconds'],0);self.assertGreaterEqual(rollback['restore_seconds'],0)
        self.assertEqual(sorted(p.name for p in (self.root/'record').iterdir()),
            ['after-backup.json','after-rollback.json','after-upgrade.json','baseline.json','report.json'])
        recorded=out+errors+''.join(p.read_text() for p in (self.root/'record').iterdir())
        self.assertNotIn(self.secret,recorded);self.assertNotIn(self.secret[::-1],recorded)

    def test_refusals_run_before_any_controller_call_or_snapshot(self):
        bare=self.root/'bare';bare.mkdir()
        other=release(self.root/'releases/other',version='0.0.9',images=OLD_IMAGES)
        rebuilt=release(self.root/'releases/rebuilt',version='0.1.0',images=NEW_IMAGES)
        same=release(self.root/'releases/same',version='0.1.0',images=OLD_IMAGES)
        incomplete=self.root/'releases/incomplete';incomplete.mkdir();(incomplete/'modelanvil.py').write_text('')
        existing=self.root/'existing';existing.mkdir()
        cases=(({'directory':bare},'needs instance.json'),({'previous_release':other},'--previous-release must be the release this directory runs'),
            ({'previous_release':rebuilt},'--previous-release must be the release this directory runs'),({'release':same},'already installed'),
            ({'release':incomplete},'Not a built release'),({'backup':existing},'new directory for --backup'),({'record':existing},'new directory for --record'),
            ({'upgrade_backup':self.root/'backups/drill'},'must differ'),({'rollback_directory':self.instance/'rollback'},'outside the installed directory'))
        for overrides,message in cases:
            with self.subTest(overrides=overrides):
                code,_,errors=self.drill(self.arguments(**overrides))
                self.assertEqual(code,2);self.assertIn(message,errors)
                self.assertEqual((self.commands,self.snapshots),([],[]));self.assertFalse((self.root/'record').exists())
        self.assertFalse((self.root/'backups').exists());self.assertFalse((self.root/'rollback').exists())

    def test_an_instance_without_a_model_is_refused_before_the_backup(self):
        self.changes['baseline']=lambda state:state.update(models=[])
        code,_,errors=self.drill(self.arguments())
        self.assertEqual(code,2);self.assertIn('no CPU reference model',errors);self.assertEqual(self.commands,[])
        self.assertFalse(self.report()['passed']);self.assertEqual(self.report()['steps'],[])

    def test_failed_upgrade_stops_the_drill_before_any_restore(self):
        self.codes['upgrade']=1
        code,_,errors=self.drill(self.arguments())
        self.assertEqual(code,1);self.assertEqual([c[2] for c in self.commands],['backup','upgrade'])
        self.assertIn('upgrade failed with exit code 1: ModelAnvil: Release checksum failed: images.tar',errors)
        report=self.report();self.assertFalse(report['passed']);self.assertEqual(report['steps'][-1]['exit_code'],1)
        self.assertNotIn('rollback',report);self.assertFalse((self.root/'rollback').exists())

    def test_state_changed_by_the_upgrade_stops_the_drill_and_names_the_table(self):
        self.changes['after_upgrade']=lambda state:state['rows'].update(runners_modelversion=1)
        code,_,errors=self.drill(self.arguments())
        self.assertEqual(code,1);self.assertIn('row counts differ in runners_modelversion',errors)
        self.assertEqual([c[2] for c in self.commands],['backup','upgrade'])
        self.assertEqual(self.report()['checks']['after_upgrade']['differing_tables'],{'runners_modelversion':[2,1]})

    def test_rollback_that_comes_back_on_another_version_fails(self):
        original=self.controller
        def restore_newer(command,**kwargs):
            result=original(command,**kwargs)
            if command[2]=='restore':
                target=Path(command[command.index('--directory')+1]);state=json.loads((target/'instance.json').read_text());state['version']='0.1.1'
                (target/'instance.json').write_text(json.dumps(state))
            return result
        with patch.object(self,'controller',side_effect=restore_newer):code,_,errors=self.drill(self.arguments())
        self.assertEqual(code,1);self.assertIn('instance version is 0.1.1, expected 0.1.0',errors)


class DrillComparisonTests(SimpleTestCase):
    def test_comparison_names_every_difference(self):
        reference=recorded_state();self.assertEqual(drill.compare(reference,recorded_state())['problems'],[])
        self.assertEqual(drill.usable(reference),[])
        def changed(change):
            value=recorded_state();change(value);return value
        cases=((lambda s:s['rows'].update(jobs_job=2),'row counts differ in jobs_job'),
            (lambda s:s['rows'].pop('rag_chunk'),'row counts differ in rag_chunk'),
            (lambda s:s['artifacts'][0].update(sha256='9'*64,stored_sha256='9'*64),'committed artifact ids, sha256 or sizes differ'),
            (lambda s:s['artifacts'].pop(),'committed artifact ids, sha256 or sizes differ'),
            (lambda s:s['artifacts'][1].update(stored_sha256='0'*64),'stored bytes differ from the recorded sha256 for artifact-2'),
            (lambda s:s['artifact_files'][2].update(sha256='0'*64),'artifact volume files or their sha256 differ'),
            (lambda s:s['models'][1].update(generated_token_ids=[33,33,33,34]),'greedy-decoding tokens differ'),
            (lambda s:s['models'][0].update(generated_token_ids=None) or s['models'][0].pop('generated_token_ids'),'a model failed to generate'),
            (lambda s:s.update(prompt='other'),'the snapshots used different prompts'),
            (lambda s:s.update(pgvector='0.7.0'),'pgvector differs'),(lambda s:s.update(server_version='16.4'),'server_version differs'),
            (lambda s:s['health']['health'].update(status=503),'the health check failed'),
            (lambda s:s['health']['ready'].update(status=None),'the health check failed'))
        for change,message in cases:
            with self.subTest(message=message):
                result=drill.compare(reference,changed(change))
                self.assertFalse(result['equal']);self.assertIn(message,result['problems'])
        result=drill.compare(reference,changed(cases[0][0]))
        self.assertEqual(result['differing_tables'],{'jobs_job':[1,2]});self.assertEqual(result['tables'],5);self.assertEqual(result['tables_with_rows'],4)
        empty=changed(lambda s:s.update(artifacts=[],models=[]))
        self.assertEqual(drill.usable(empty),['there is no committed artifact','there is no CPU reference model; import the example and train it first'])


class FakeResponse:
    def __init__(self,body):self.status=200;self.body=json.dumps(body).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,limit):return self.body[:limit]


class SnapshotCommandTests(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.secret=secrets.token_urlsafe(32);self.instance=installed(self.root/'instance',self.secret);(self.instance/'ca.crt').write_text('fixture CA\n')

    def test_snapshot_probes_through_the_instance_compose_project_and_trusts_only_its_ca(self):
        probe={k:v for k,v in recorded_state().items() if k in ('database_vendor','server_version','pgvector','rows','artifacts','artifact_files','models')}
        stdout=('{"event": "django log line"}\n'+drill.PROBE_MARK+json.dumps(probe)+'\n').encode()
        opened=[];contexts=[]
        opener=SimpleNamespace(open=lambda url,timeout:opened.append(url) or FakeResponse({'status':'ok'} if url.endswith('/health/') else {'status':'ready'}))
        with patch.object(drill.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=stdout,stderr=b'')) as execute, \
                patch.object(drill.ssl,'create_default_context',side_effect=lambda cafile:contexts.append(cafile) or object()), \
                patch.object(drill.urllib.request,'build_opener',return_value=opener):
            value=drill.snapshot(self.instance,'a tiny',8)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0],['docker','compose','--env-file',str(self.instance/'.env'),'-p','modelanvil-local-0123456789ab',
            '-f',str(self.instance/'release/compose.yaml'),'exec','-T','api','python','-c',drill.PROBE,'a tiny','8'])
        self.assertEqual(set(execute.call_args.kwargs['env']),{'PATH','HOME'})
        self.assertEqual(contexts,[str(self.instance/'ca.crt')])
        self.assertEqual(opened,['https://localhost:18443/api/v1/health/','https://localhost:18443/api/v1/ready/'])
        self.assertEqual(value['health'],HEALTHY);self.assertEqual(value['rows'],probe['rows']);self.assertEqual(value['models'],probe['models'])
        self.assertEqual((value['version'],value['compose_project'],value['release']['images']),('0.1.0','modelanvil-local-0123456789ab',OLD_IMAGES))
        self.assertNotIn(self.secret,json.dumps(value))

    def test_failed_probe_keeps_docker_detail_in_a_private_log(self):
        with patch.object(drill.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=b'',stderr=b'container api is not running')):
            with self.assertRaisesRegex(drill.DrillError,'inspect drill-private.log'):drill.snapshot(self.instance,'a tiny',8)
        log=self.instance/'drill-private.log'
        self.assertEqual(log.stat().st_mode&0o777,0o600);self.assertIn('container api is not running',log.read_text())

    def test_expect_reuses_the_recorded_prompt_and_exits_one_on_a_mismatch(self):
        expected=recorded_state();expected.update(prompt='another prompt',max_tokens=4);(self.root/'expected.json').write_text(json.dumps(expected))
        calls=[]
        def taken(result):
            def snapshot(directory,prompt,limit):calls.append((prompt,limit));return result
            return snapshot
        arguments=['snapshot','--directory',str(self.instance),'--expect',str(self.root/'expected.json')]
        for result,code in ((copy.deepcopy(expected),0),({**copy.deepcopy(expected),'pgvector':'0.7.0'},1)):
            with patch.object(drill,'snapshot',side_effect=taken(result)),patch('sys.stdout',new_callable=io.StringIO) as out:
                self.assertEqual(drill.main(arguments),code)
            self.assertEqual(json.loads(out.getvalue())['comparison']['equal'],code==0)
        self.assertEqual(calls,[('another prompt',4)]*2)
        (self.root/'taken.json').write_text('{}')
        with patch.object(drill,'snapshot') as snapshot,patch('sys.stderr',new_callable=io.StringIO) as errors:
            self.assertEqual(drill.main([*arguments,'--output',str(self.root/'taken.json')]),2)
        snapshot.assert_not_called();self.assertIn('new --output file',errors.getvalue())


class ProbeTests(TestCase):
    """Runs the exact probe source the drill sends to the api container, against the test database and artifact store."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        override=override_settings(MODELANVIL={**settings.MODELANVIL,'artifact_root':self.temp.name,'artifact_backend':'filesystem'})
        override.enable();self.addCleanup(override.disable)

    def command(self,command_name,value,**kwargs):
        out=io.StringIO()
        with patch('sys.stdin',SimpleNamespace(buffer=io.BytesIO(json.dumps(value).encode()))):call_command(command_name,stdout=out,**kwargs)
        return json.loads(out.getvalue())

    def probe(self):
        out=io.StringIO()
        with patch.object(sys,'argv',['probe','a tiny','8']),patch('sys.stdout',out):exec(compile(drill.PROBE,'drill-probe','exec'),{'__name__':'drill_probe'})
        line=[item for item in out.getvalue().splitlines() if item.startswith(drill.PROBE_MARK)]
        self.assertEqual(len(line),1)
        return {**json.loads(line[0][len(drill.PROBE_MARK):]),'health':copy.deepcopy(HEALTHY),'prompt':'a tiny','max_tokens':8}

    def test_probe_records_rows_artifact_hashes_and_greedy_tokens_and_detects_changed_bytes(self):
        from modelanvil.runners.training import general_runtime as runtime
        from modelanvil.runners.training.engine import pack_safetensors
        from modelanvil.runners.training.general_transformer import GeneralTransformer
        created=self.command('initialize_selfhost',{'email':'owner@example.test','password':secrets.token_urlsafe(24),'name':'Drill workspace'})
        model=GeneralTransformer(vocab_size=260,n_layer=1,n_head=1,n_embd=4,context_window=32,seed=123)
        raw,manifest=pack_safetensors(model.export_tensors())
        bundle={'config.json':{'runtime':runtime.RUNTIME_ID,'vocab_size':260,'n_layer':1,'n_head':1,'n_embd':4,'context_window':32},
            'tokenizer_config.json':{'kind':'byte-v1','vocab_size':260,'pad_id':0,'bos_id':1,'eos_id':2,'unk_id':3},
            'model.safetensors.b64':base64.b64encode(raw).decode(),'weights_manifest.json':manifest}
        self.command('import_cpu_reference',bundle,tenant_id=created['tenant'],project_id=created['project'],name='Drill reference',license='MIT',
            example_worker_id=created['worker_id'])
        first=self.probe()
        self.assertEqual(first['database_vendor'],'sqlite');self.assertIsNone(first['pgvector'])
        self.assertEqual(first['rows']['runners_modelversion'],1);self.assertGreaterEqual(first['rows']['artifacts_artifact'],1)
        self.assertEqual(first['rows']['identity_tenant'],1)
        self.assertTrue(first['artifacts'])
        for item in first['artifacts']:self.assertEqual((item['stored_sha256'],item['stored_bytes']),(item['sha256'],item['byte_size']))
        # The filesystem store keeps raw bytes, so every committed artifact is one of the hashed volume files.
        self.assertLessEqual({a['sha256'] for a in first['artifacts']},{f['sha256'] for f in first['artifact_files']})
        [generated]=first['models'];self.assertNotIn('error',generated)
        self.assertTrue(1<=len(generated['generated_token_ids'])<=8);self.assertIsInstance(generated['completion'],str)
        self.assertEqual(drill.usable(first),[])
        # Greedy decoding of the same stored weights is deterministic, so a second probe is identical.
        self.assertEqual(drill.compare(first,self.probe())['problems'],[])
        # One flipped byte in stored artifact bytes, same size, is reported by both hash checks.
        committed={a['sha256'] for a in first['artifacts']}
        stored=next(f for f in first['artifact_files'] if f['sha256'] in committed)
        path=Path(self.temp.name)/stored['path'];data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(bytes(data))
        changed=self.probe();problems=drill.compare(first,changed)['problems']
        self.assertIn('artifact volume files or their sha256 differ',problems)
        self.assertTrue(any(p.startswith('stored bytes differ from the recorded sha256') for p in problems),problems)
