"""Fixed local Docker boundary; model/user data can supply Python source, never a command."""
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from urllib.parse import urlsplit

IMAGE='python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704'
LIMITS={'source_bytes':8192,'stdout_bytes':16384,'stderr_bytes':16384,'execution_seconds':5,
    'container_memory_bytes':128*1024**2,'cpu_cores':1,'pids':32,'writable_tmpfs_bytes':32*1024**2,
    'network':'none','filesystem':'read-only image plus private /work and /tmp tmpfs; no host mounts',
    'execution_uid':65534,'persistent_files':False}
TMPFS={'/work':'rw,nosuid,nodev,noexec,size=16m,uid=65534,gid=65534,mode=755',
    '/tmp':'rw,nosuid,nodev,noexec,size=16m,uid=65534,gid=65534,mode=700'}
GUARD=Path(__file__).resolve().parents[2]/'scripts/tool_sandbox_guard.py'


def validate(code,seconds):
    if not isinstance(code,str) or not 0<len(code.encode())<=8192 or type(seconds) is not int or not 1<=seconds<=5:
        raise ValueError('Use1–8192 UTF-8 bytes of Python source and1–5 seconds.')


def _endpoint(binary):
    env={'PATH':os.environ.get('PATH',''),'HOME':str(Path.home())}
    try:
        result=subprocess.run([binary,'context','inspect','--format','{{json .Endpoints.docker.Host}}'],
            env=env,capture_output=True,text=True,timeout=3,check=True)
        value=json.loads(result.stdout);parsed=urlsplit(value)
        if (not isinstance(value,str) or len(value)>512 or parsed.scheme!='unix' or parsed.netloc or parsed.query or parsed.fragment
                or not Path(parsed.path).is_absolute() or not stat.S_ISSOCK(os.stat(parsed.path).st_mode)):
            raise ValueError()
    except (OSError,ValueError,subprocess.SubprocessError):
        raise ValueError('Code execution requires the operator’s local Unix-socket Docker daemon; remote engines are disabled.') from None
    return value


def _command():
    binary=shutil.which('docker')
    if not binary:raise ValueError('Install the local Docker runtime before code execution.')
    return [binary,'--host',_endpoint(binary)]


def _json(command,env):
    try:
        result=subprocess.run(command,env=env,capture_output=True,timeout=3,check=True)
        if len(result.stdout)>1024**2:raise ValueError()
        return json.loads(result.stdout)
    except (OSError,ValueError,subprocess.SubprocessError):raise ValueError('The local sandbox runtime could not be verified.') from None


def _daemon(command,env):
    value=_json([*command,'info','--format','{{json .}}'],env)
    if value.get('OSType')!='linux' or 'name=seccomp,profile=builtin' not in value.get('SecurityOptions',[]):
        raise ValueError('The sandbox requires a local Linux Docker engine with its built-in seccomp profile enabled.')
    return value


def available():
    command=_command()
    with tempfile.TemporaryDirectory(prefix='modelanvil-sandbox-probe-') as temp:
        env={'PATH':os.environ.get('PATH',''),'HOME':temp,'DOCKER_CONFIG':temp}
        image=_json([*command,'image','inspect',IMAGE],env)[0]
        daemon=_daemon(command,env)
        if daemon.get('OSType')!='linux' or IMAGE not in image.get('RepoDigests',[]):
            raise ValueError('Provision the exact pinned Python image on the local Linux Docker engine; jobs never pull images.')
        return {'image':IMAGE,'image_id':image['Id'],'os':image['Os'],'architecture':image['Architecture'],
            'engine_version':daemon['ServerVersion'],'security':daemon['SecurityOptions'],'limits':LIMITS,'production_qualified':False}


def _check_container(value):
    host,config=value['HostConfig'],value['Config']
    normalize=lambda values:{v.removeprefix('CAP_').upper() for v in values or []}
    if (config['Image']!=IMAGE or config['User']!='0:0' or host['NetworkMode']!='none' or not host['ReadonlyRootfs']
            or host['Privileged'] or host.get('Binds') or value.get('Mounts') or host.get('Devices') or host.get('DeviceRequests')
            or host.get('PidMode','')!='' or host.get('IpcMode','private')!='private'
            or host['Memory']!=128*1024**2 or host['MemorySwap']!=128*1024**2 or host['NanoCpus']!=10**9 or host['PidsLimit']!=32
            or normalize(host['CapDrop'])!={'ALL'} or normalize(host['CapAdd'])!={'SETUID','SETGID','KILL'}
            or len(host.get('SecurityOpt',[]))!=1 or host['SecurityOpt'][0] not in ('no-new-privileges','no-new-privileges:true')
            or host['Tmpfs']!=TMPFS or host['LogConfig']['Type']!='none'):
        raise ValueError('The actual container does not match the declared sandbox isolation.')
    return {'image':config['Image'],'read_only_root':True,'network':'none','host_mounts':False,
        'memory_bytes':host['Memory'],'cpu_cores':host['NanoCpus']/10**9,'pids':host['PidsLimit'],
        'trusted_watchdog_uid':0,'execution_uid':65534,'watchdog_capabilities':['SETUID','SETGID','KILL'],
        'untrusted_child_capabilities':[],'no_new_privileges':True,'logging':'none'}


def run(code,*,seconds=5,cancelled=lambda:False,lease_descriptor=None):
    validate(code,seconds);command=_command();identity='modelanvil-tool-'+str(uuid.uuid4());proc=None;cleaned=False
    with tempfile.TemporaryDirectory(prefix='modelanvil-code-') as temp:
        env={'PATH':os.environ.get('PATH',''),'HOME':temp,'DOCKER_CONFIG':temp}
        image=_json([*command,'image','inspect',IMAGE],env)[0];daemon=_daemon(command,env)
        if IMAGE not in image.get('RepoDigests',[]):raise ValueError('Provision the pinned sandbox image; network acquisition is disabled during jobs.')
        args=[*command,'run','-i','--name',identity,'--pull=never','--network=none','--read-only','--user=0:0',
            '--cpus=1','--memory=128m','--memory-swap=128m','--pids-limit=32','--cap-drop=ALL','--cap-add=SETUID','--cap-add=SETGID','--cap-add=KILL',
            '--security-opt=no-new-privileges','--workdir=/work',*[f'--tmpfs={path}:{options}' for path,options in TMPFS.items()],'--log-driver=none',
            IMAGE,'/usr/local/bin/python','-I','-S','-B','-c',GUARD.read_text()]
        raw=bytearray();errors=bytearray();started=time.monotonic();status=None;isolation=None;cancel_sent=False
        try:
            proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,
                pass_fds=() if lease_descriptor is None else (lease_descriptor,))
            deadline=time.monotonic()+5
            while isolation is None:
                if cancelled():status='cancelled';break
                result=subprocess.run([*command,'inspect',identity],env=env,capture_output=True,timeout=3)
                if result.returncode==0:
                    if len(result.stdout)>1024**2:raise ValueError('Sandbox inspection exceeds its bound.')
                    isolation=_check_container(json.loads(result.stdout)[0]);break
                if proc.poll() is not None or time.monotonic()>deadline:raise ValueError('Sandbox container failed to start within its bound.')
                time.sleep(.05)
            if status is None:
                proc.stdin.write(json.dumps({'code':code,'wall_seconds':seconds},ensure_ascii=False).encode());proc.stdin.close()
                with selectors.DefaultSelector() as selector:
                    for name,stream in (('stdout',proc.stdout),('stderr',proc.stderr)):
                        os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ,name)
                    while selector.get_map():
                        if cancelled() and not cancel_sent:
                            signal_result=subprocess.run([*command,'kill','--signal=TERM',identity],env=env,capture_output=True,timeout=3)
                            if signal_result.returncode and proc.poll() is None:raise ValueError('Sandbox cancellation could not be delivered.')
                            cancel_sent=True
                        if time.monotonic()-started>seconds+10:status='timeout';break
                        for key,_ in selector.select(.05):
                            block=os.read(key.fd,4096)
                            if not block:selector.unregister(key.fileobj);continue
                            target=raw if key.data=='stdout' else errors
                            if len(target)+len(block)>256*1024:raise ValueError('Sandbox controller output exceeds its bound.')
                            target.extend(block)
                if status is None:
                    proc.wait(timeout=2)
                    if proc.returncode:raise ValueError('Sandbox did not return a complete trusted result.')
                    report=json.loads(raw)
                    if (report.get('schema_version')!='modelanvil.python-sandbox.v1' or report.get('status') not in ('completed','code_error','timeout','output_limit','cancelled')
                            or report.get('execution_uid')!=65534 or report.get('network')!='none' or report.get('persistent_files') is not False
                            or type(report.get('exit_code')) is not int or not isinstance(report.get('stdout'),str) or not isinstance(report.get('stderr'),str)
                            or any(type(report.get(n)) is not int or not 0<=report[n]<=16384 for n in ('stdout_bytes','stderr_bytes'))
                            or type(report.get('wall_seconds')) not in (int,float) or not math.isfinite(report['wall_seconds'])
                            or not 0<=report['wall_seconds']<=seconds+2):raise ValueError('Sandbox result is missing required bounded execution evidence.')
            if status:report={'schema_version':'modelanvil.python-sandbox.v1','status':status,'stdout':'','stderr':'',
                'exit_code':None,'cpu_seconds':None,'execution_uid':65534,'network':'none','persistent_files':False}
        finally:
            # Wait for only this container's forced removal before releasing the caller's admission fence.
            result=subprocess.run([*command,'rm','--force',identity],env=env,capture_output=True,timeout=5)
            cleaned=result.returncode==0
            if proc is not None:
                if proc.poll() is None:proc.kill()
                proc.wait(timeout=3)
                for stream in (proc.stdin,proc.stdout,proc.stderr):
                    if stream is not None and not stream.closed:stream.close()
            if not cleaned:raise ValueError('Sandbox cleanup could not be verified; execution is unqualified.')
        return {**report,'isolation':isolation,'limits':LIMITS,'controller_wall_seconds':time.monotonic()-started,
            'container_removed':cleaned,'engine_version':daemon['ServerVersion'],'security':daemon['SecurityOptions'],'production_qualified':False}
