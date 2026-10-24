"""Code execution trust boundaries; actual Docker qualification is recorded separately."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from modelanvil.runners import tool_sandbox as sandbox


class SandboxBoundaryTests(SimpleTestCase):
    def test_invalid_source_and_limits_refused_before_contacting_docker(self):
        with patch.object(sandbox,'_command') as command:
            for code,seconds in [('',1),('x'*8193,1),('x',0),('x',6),('x',True),(None,1)]:
                with self.subTest(seconds=seconds),self.assertRaises(ValueError):sandbox.run(code,seconds=seconds)
            command.assert_not_called()

    def test_remote_engine_and_environment_credentials_are_not_forwarded(self):
        for endpoint in ('tcp://remote.example:2375','ssh://operator@remote','https://remote.example/docker'):
            with patch.dict('os.environ',{'DOCKER_HOST':'tcp://remote.example:2375','DOCKER_CUSTOM_HEADERS':'Authorization=private-fixture-value'}), \
                    patch.object(sandbox.subprocess,'run',return_value=SimpleNamespace(stdout=__import__('json').dumps(endpoint))) as execute:
                with self.assertRaisesRegex(ValueError,'local Unix-socket'):sandbox._endpoint('/installed/docker')
                self.assertNotIn('DOCKER_HOST',execute.call_args.kwargs['env'])
                self.assertNotIn('DOCKER_CUSTOM_HEADERS',execute.call_args.kwargs['env'])

    def test_actual_container_configuration_cannot_relax_network_mounts_or_privileges(self):
        value={'Config':{'Image':sandbox.IMAGE,'User':'0:0'},'Mounts':[],
            'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'Privileged':False,'Binds':None,'Devices':[],
                'Memory':128*1024**2,'MemorySwap':128*1024**2,'NanoCpus':10**9,'PidsLimit':32,
                'CapDrop':['ALL'],'CapAdd':['SETUID','SETGID','KILL'],'SecurityOpt':['no-new-privileges'],
                'Tmpfs':sandbox.TMPFS,'LogConfig':{'Type':'none'}}}
        self.assertEqual(sandbox._check_container(value)['execution_uid'],65534)
        for change in ({'NetworkMode':'bridge'},{'ReadonlyRootfs':False},{'Privileged':True},
                {'Binds':['/private:/work']},{'CapAdd':['SYS_ADMIN']},{'Memory':0},{'PidsLimit':0},
                {'SecurityOpt':[]},{'SecurityOpt':['no-new-privileges:false']},{'SecurityOpt':['no-new-privileges','seccomp=unconfined']},
                {'PidMode':'host'},{'DeviceRequests':[{'Count':-1}]},{'Tmpfs':{'/work':'rw,exec'}},{'LogConfig':{'Type':'json-file'}}):
            bad=deepcopy(value);bad['HostConfig'].update(change)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'declared sandbox isolation'):sandbox._check_container(bad)
