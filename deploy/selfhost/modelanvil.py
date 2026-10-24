#!/usr/bin/env python3
"""Standard-library installer/controller for a verified, provisioned local Docker release."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import webbrowser

FILES={'modelanvil.py','compose.yaml','reference.json','README.md','LICENSE','requirements.selfhost.lock.txt','images.tar'}


class InstallError(ValueError):pass


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while True:
            block=stream.read(4*1024**2)
            if not block:break
            value.update(block)
    return value.hexdigest()


def read_json(path,maximum=65536):
    with path.open('rb') as stream:raw=stream.read(maximum+1)
    if len(raw)>maximum:raise InstallError('Configuration exceeds its supported size.')
    value=json.loads(raw)
    if not isinstance(value,dict):raise InstallError('Configuration requires a JSON object.')
    return value


def write_json(path,value):
    temporary=path.with_name(path.name+'.tmp')
    with open(temporary,'w',opener=lambda p,flags:os.open(p,flags,0o600)) as stream:json.dump(value,stream,indent=2)
    os.replace(temporary,path)


def release(directory):
    if any(p.name not in FILES|{'release.json','.DS_Store'} for p in directory.iterdir()):raise InstallError('Release contains unlisted files or directories.')
    value=read_json(directory/'release.json')
    if (value.get('schema_version')!='modelanvil.selfhost-release.v1' or not isinstance(value.get('files'),dict)
            or set(value['files'])!=FILES or set(value.get('images',{}))!={'api','web','db'}
            or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,79}',value.get('version',''))
            or any(not re.fullmatch(r'sha256:[a-f0-9]{64}',v) for v in value['images'].values())):
        raise InstallError('This directory is not a complete self-host release.')
    for name,pin in value['files'].items():
        if not isinstance(pin,dict) or type(pin.get('bytes')) is not int or not 0<pin['bytes']<=4*1024**3 or not re.fullmatch(r'[a-f0-9]{64}',pin.get('sha256','')):raise InstallError('Release file manifest is invalid.')
        path=directory/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=pin['bytes'] or sha(path)!=pin['sha256']:
            raise InstallError('Release checksum failed: '+name)
    return value


class Instance:
    def __init__(self,root):
        self.root=root.resolve();self.temporary=tempfile.TemporaryDirectory(prefix='modelanvil-controller-')
        clean={'PATH':os.environ.get('PATH',''),'HOME':str(Path.home())}
        try:
            result=subprocess.run(['docker','context','inspect','--format','{{json .Endpoints.docker.Host}}'],env=clean,capture_output=True,timeout=5,check=True)
            endpoint=json.loads(result.stdout)
            if not isinstance(endpoint,str) or not endpoint.startswith('unix:///') or not stat.S_ISSOCK(os.stat(endpoint[7:]).st_mode):raise ValueError()
        except (OSError,ValueError,subprocess.SubprocessError):raise InstallError('Start the local Unix-socket Docker engine with Compose v2, then retry.') from None
        self.docker=['docker','--host',endpoint];self.env={**clean,'DOCKER_CONFIG':self.temporary.name}
        # Compose can be installed under the user's Docker config. Expose only that installed binary, never registry credentials.
        plugins=subprocess.run([*self.docker,'info','--format','{{json .ClientInfo.Plugins}}'],env=clean,capture_output=True,timeout=5,check=True)
        compose=next((Path(v['Path']).resolve() for v in json.loads(plugins.stdout) if v.get('Name')=='compose'),None)
        if compose is None or not compose.is_absolute() or not compose.is_file() or not os.access(compose,os.X_OK):raise InstallError('Install Docker Compose v2 or later, then retry.')
        directory=Path(self.temporary.name)/'cli-plugins';directory.mkdir(mode=0o700);(directory/'docker-compose').symlink_to(compose)
        version=self.call(['compose','version','--short'],timeout=5).decode().strip()
        match=re.match(r'^v?(\d+)\.',version)
        if not match or int(match[1])<2:raise InstallError('Docker Compose v2 or later is required.')
        info=json.loads(self.call(['info','--format','{{json .}}']))
        if info.get('OSType')!='linux' or type(info.get('MemTotal')) is not int or info['MemTotal']<4*1024**3:raise InstallError('The CPU self-host package requires a local Linux Docker engine with at least4GiB assigned memory.')
        self.architecture={'aarch64':'arm64','x86_64':'amd64'}.get(info.get('Architecture'),info.get('Architecture'))
        if self.architecture!='arm64':raise InstallError('This package requires a native Linux arm64 Docker engine; emulation and other architectures need separate qualification.')
        self.state=read_json(self.root/'instance.json') if (self.root/'instance.json').exists() else None

    def call(self,args,*,data=None,input_file=None,output=None,timeout=240):
        with tempfile.TemporaryFile() as diagnostic:
            try:
                result=subprocess.run([*self.docker,*args],input=data,stdin=input_file,stdout=output or subprocess.PIPE,stderr=diagnostic,env=self.env,timeout=timeout)
                if result.returncode:
                    if self.root.is_dir():
                        diagnostic.seek(0);raw=diagnostic.read(1024*1024)
                        with open(self.root/'controller-private.log','ab',opener=lambda p,flags:os.open(p,flags,0o600)) as stream:
                            stream.write(('Operation: '+args[0]+'\n').encode()+raw+b'\n')
                    raise InstallError('Docker operation failed: '+args[0]+'. Inspect status and the private controller log.')
                return result.stdout
            except subprocess.TimeoutExpired:raise InstallError('Docker operation exceeded its time limit. Inspect status before retrying.') from None

    def compose(self,*args,**kwargs):
        if self.state is None:raise InstallError('Initialize an installation directory first.')
        return self.call(['compose','--env-file',str(self.root/'.env'),'-p',self.state['compose_project'],'-f',str(self.root/'release/compose.yaml'),*args],**kwargs)

    def environment(self,manifest,*,host,bind,http_port,https_port,secrets_from=None):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',host) or '..' in host:raise InstallError('Use an explicit local/LAN hostname without paths or credentials.')
        try:socket.inet_aton(bind)
        except OSError:raise InstallError('Use an explicit IPv4 bind address.') from None
        if any(type(p) is not int or not 1024<=p<=65535 for p in (http_port,https_port)) or http_port==https_port:
            raise InstallError('Select different HTTP/HTTPS ports from1024–65535.')
        values=secrets_from or {'DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'POSTGRES_PASSWORD':secrets.token_urlsafe(32)}
        entries={**values,'MODELANVIL_DOMAIN':host,'MODELANVIL_BIND_ADDRESS':bind,'MODELANVIL_HTTP_PORT':str(http_port),'MODELANVIL_HTTPS_PORT':str(https_port),
            'MODELANVIL_PUBLIC_ORIGIN':f'https://{host}:{https_port}','MODELANVIL_SELFHOST_WORKER_ID':str(self.state.get('worker_id',0)),
            **{'MODELANVIL_'+key.upper()+'_IMAGE':value for key,value in manifest['images'].items()}}
        with open(self.root/'.env','w',opener=lambda p,flags:os.open(p,flags,0o600)) as stream:
            stream.write(''.join(k+'='+v+'\n' for k,v in entries.items()))
        (self.root/'.env').chmod(0o600)
        self.state.update(origin=entries['MODELANVIL_PUBLIC_ORIGIN'],host=host,bind=bind,http_port=http_port,https_port=https_port,version=manifest['version'])
        write_json(self.root/'instance.json',self.state)

    def load_images(self,manifest,directory=None):
        if manifest.get('architecture')!=self.architecture:raise InstallError('Release and native engine architectures differ; emulation is not qualified.')
        for identifier in manifest['images'].values():
            try:self.call(['image','inspect',identifier],timeout=5)
            except InstallError:
                self.call(['load','--input',str((directory or self.root/'release')/'images.tar')],timeout=600);break
        for identifier in manifest['images'].values():
            info=json.loads(self.call(['image','inspect',identifier],timeout=5))[0]
            if info['Id']!=identifier or info['Architecture']!=manifest['architecture'] or info['Os']!='linux':raise InstallError('Release image identity/platform differs from its manifest.')

    def start(self):
        self.compose('up','-d','--wait','--wait-timeout','120','db','api','worker','reconciler','web')
        ca=self.root/'ca.crt'
        for attempt in range(30):
            try:self.compose('cp','web:/data/caddy/pki/authorities/local/root.crt',str(ca),timeout=5);break
            except InstallError:time.sleep(.5)
        else:raise InstallError('The local TLS authority was not available; inspect deployment readiness.')
        ca.chmod(0o644)
        context=ssl.create_default_context(cafile=str(ca))
        with urllib.request.urlopen(self.state['origin']+'/api/v1/ready/',context=context,timeout=10) as response:
            if response.status!=200:raise InstallError('The installation is not ready.')
        return {'origin':self.state['origin'],'ready':True,'ca':str(ca),'version':self.state['version'],'production_qualified':False}

    def bootstrap(self,credentials):
        self.compose('up','-d','--wait','--wait-timeout','60','db')
        self.compose('run','--rm','-T','migrate')
        raw=self.compose('run','--rm','-T','--no-deps','migrate','python','manage.py','initialize_selfhost',data=json.dumps(credentials).encode())
        result=json.loads(raw);self.state.update({k:result[k] for k in ('tenant','project','worker_id','pool','runner_manifest')})
        return result

    def launchers(self):
        command='exec python3 '+shlex.quote(str(self.root/'release/modelanvil.py'))+' start --directory '+shlex.quote(str(self.root))+' --open\n'
        app=self.root/'ModelAnvil.app/Contents';(app/'MacOS').mkdir(parents=True,exist_ok=True)
        (app/'MacOS/launch').write_text('#!/bin/sh\n'+command);(app/'MacOS/launch').chmod(0o700)
        import plistlib
        with (app/'Info.plist').open('wb') as stream:plistlib.dump({'CFBundleIdentifier':'local.modelanvil.launcher','CFBundleName':'ModelAnvil','CFBundleExecutable':'launch','CFBundlePackageType':'APPL','CFBundleVersion':'1'},stream)
        # The desktop-file format uses quoted arguments, not shell expansion.
        quote=lambda text:'"'+str(text).replace('%','%%').replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')+'"'
        (self.root/'ModelAnvil.desktop').write_text('[Desktop Entry]\nType=Application\nName=ModelAnvil\nTerminal=false\nExec=python3 '+quote(self.root/'release/modelanvil.py')+' start --directory '+quote(self.root)+' --open\n')
        (self.root/'ModelAnvil.desktop').chmod(0o700)

    def install(self,source,credentials,options):
        if self.root.exists():raise InstallError('Install into a new directory. Existing instances and user data are never overwritten.')
        manifest=release(source)
        self.root.mkdir(parents=True,mode=0o700);self.root.chmod(0o700);shutil.copytree(source,self.root/'release',ignore=shutil.ignore_patterns('.DS_Store'))
        self.state={'schema_version':'modelanvil.selfhost-instance.v1','compose_project':'modelanvil-local-'+uuid.uuid4().hex[:12]}
        self.environment(manifest,host=options.host,bind=options.bind,http_port=options.http_port,https_port=options.https_port)
        self.load_images(manifest);return self.initialize(credentials)

    def initialize(self,credentials):
        self.bootstrap(credentials);manifest=read_json(self.root/'release/release.json')
        options={k:self.state[k] for k in ('host','bind','http_port','https_port')}
        self.environment(manifest,**options,secrets_from=self.private_secrets(self.root/'.env'))
        self.launchers();return self.start()

    def backup(self,destination,*,restart=True):
        if destination.exists():raise InstallError('Use a new backup directory so previous recovery points survive.')
        destination.mkdir(parents=True,mode=0o700)
        self.compose('stop','web','api','worker','reconciler')
        completed=False
        try:
            self.compose('run','--rm','-T','--no-deps','migrate','python','-c',
                "import django;django.setup();from modelanvil.jobs.models import Job;assert not Job.all_objects.filter(status__in=['queued','running','interrupted']).exists(),'Wait for or cancel active jobs before backing up.'")
            with open(destination/'database.dump','wb',opener=lambda p,flags:os.open(p,flags,0o600)) as stream:
                self.compose('exec','-T','db','pg_dump','-U','modelanvil','-d','modelanvil','-Fc',output=stream)
            with open(destination/'artifacts.tar','wb',opener=lambda p,flags:os.open(p,flags,0o600)) as stream:
                self.compose('run','--rm','-T','--no-deps','migrate','tar','-C','/app/storage/artifacts','-cf','-','.',output=stream)
            shutil.copy2(self.root/'.env',destination/'.env');shutil.copy2(self.root/'instance.json',destination/'instance.json')
            write_json(destination/'backup.json',{'schema_version':'modelanvil.selfhost-backup.v1','release':self.state['version'],
                'files':{n:sha(destination/n) for n in ('database.dump','artifacts.tar','.env','instance.json')}})
            completed=True
        finally:
            if restart or not completed:self.start()
        return {'backup':str(destination),'verified_checksums':4,'contains_private_identity_and_credentials':True}

    def container_status(self):
        raw=self.compose('ps','--format','json').decode().strip()
        if not raw:return []
        return json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines()]

    def private_secrets(self,path):
        values=dict(line.split('=',1) for line in path.read_text().splitlines() if '=' in line)
        result={k:values.get(k,'') for k in ('DJANGO_SECRET_KEY','POSTGRES_PASSWORD')}
        if any(not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',v) for v in result.values()):raise InstallError('The private instance secrets are invalid.')
        return result

    def upgrade(self,source,backup):
        manifest=release(source);self.load_images(manifest,directory=source)
        if manifest['version']==self.state['version']:raise InstallError('This release is already installed.')
        staged=self.root/('.release-staging-'+uuid.uuid4().hex[:8]);shutil.copytree(source,staged);release(staged)
        self.backup(backup,restart=False)
        previous=self.root/'release-history'/(self.state['version']+'-'+uuid.uuid4().hex[:8]);previous.parent.mkdir(exist_ok=True)
        private=self.private_secrets(self.root/'.env');options={k:self.state[k] for k in ('host','bind','http_port','https_port')}
        shutil.move(str(self.root/'release'),str(previous));shutil.move(str(staged),str(self.root/'release'))
        self.environment(manifest,**options,secrets_from=private)
        self.compose('run','--rm','-T','migrate');result=self.start();result['previous_release_retained']=str(previous);result['backup']=str(backup)
        return result

    def restore(self,backup,source,options):
        if self.root.exists():raise InstallError('Restore requires a new directory and isolated Docker project; live data is never overwritten.')
        manifest=release(source);saved=read_json(backup/'backup.json')
        names={'database.dump','artifacts.tar','.env','instance.json'}
        if (saved.get('schema_version')!='modelanvil.selfhost-backup.v1' or saved.get('release')!=manifest['version'] or set(saved.get('files',{}))!=names):
            raise InstallError('Use the complete verified backup and its matching release.')
        for name in names:
            path=backup/name
            if path.is_symlink() or not path.is_file() or sha(path)!=saved['files'][name]:raise InstallError('Backup checksum failed: '+name)
        import tarfile
        from pathlib import PurePosixPath
        with tarfile.open(backup/'artifacts.tar','r:') as archive:
            for member in archive:
                path=PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):raise InstallError('Artifact backup contains an unsafe path or link.')
        private=self.private_secrets(backup/'.env')
        self.root.mkdir(parents=True,mode=0o700);self.root.chmod(0o700);shutil.copytree(source,self.root/'release')
        self.state=read_json(backup/'instance.json');self.state['compose_project']='modelanvil-local-'+uuid.uuid4().hex[:12]
        self.environment(manifest,host=options.host,bind=options.bind,http_port=options.http_port,https_port=options.https_port,secrets_from=private)
        self.load_images(manifest);self.compose('up','-d','--wait','--wait-timeout','60','db')
        with (backup/'database.dump').open('rb') as stream:self.compose('exec','-T','db','pg_restore','-U','modelanvil','-d','modelanvil','--exit-on-error','--no-owner',input_file=stream)
        with (backup/'artifacts.tar').open('rb') as stream:self.compose('run','--rm','-T','--no-deps','migrate','tar','-C','/app/storage/artifacts','-xf','-',input_file=stream)
        self.compose('run','--rm','-T','migrate');self.launchers();return self.start()

    def diagnostics(self):
        return {'instance':{k:self.state[k] for k in ('compose_project','project','version','origin')},'containers':self.container_status(),
            'release_images':read_json(self.root/'release/release.json')['images'],'offline':True,'production_qualified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    for name in ('install','initialize','start','stop','status','diagnostics','backup','uninstall','example','import-reference','upgrade','restore'):
        item=sub.add_parser(name);item.add_argument('--directory',type=Path,required=True)
        if name in ('install','restore'):
            item.add_argument('--release',type=Path,default=Path(__file__).resolve().parent);item.add_argument('--host',default='localhost');item.add_argument('--bind',default='127.0.0.1')
            item.add_argument('--http-port',type=int,default=8080);item.add_argument('--https-port',type=int,default=8443);item.add_argument('--credentials-stdin',action='store_true',help='Private JSON input; default uses interactive email/name/password prompts.')
        if name=='initialize':item.add_argument('--credentials-stdin',action='store_true')
        if name=='restore':item.add_argument('--backup',type=Path,required=True)
        if name=='upgrade':item.add_argument('--release',type=Path,required=True);item.add_argument('--backup',type=Path,required=True)
        if name=='start':item.add_argument('--open',action='store_true')
        if name=='backup':item.add_argument('--output',type=Path,required=True)
        if name in ('example','import-reference'):item.add_argument('--name',required=True)
        if name=='import-reference':item.add_argument('--file',type=Path,required=True);item.add_argument('--license',required=True)
    args=parser.parse_args();instance=Instance(args.directory)
    if args.action in ('install','initialize'):
        if args.credentials_stdin:credentials=json.loads(sys.stdin.buffer.read(8193))
        else:credentials={'email':input('Owner email: '),'name':input('Workspace name: '),'password':getpass.getpass('New owner password (12+ characters): ')}
        result=instance.install(args.release.resolve(),credentials,args) if args.action=='install' else instance.initialize(credentials)
    elif args.action=='restore':result=instance.restore(args.backup.resolve(),args.release.resolve(),args)
    elif args.action=='upgrade':result=instance.upgrade(args.release.resolve(),args.backup.resolve())
    elif args.action=='start':
        result=instance.start()
        if args.open:webbrowser.open(instance.state['origin'])
    elif args.action=='stop':instance.compose('stop');result={'stopped':True,'user_data_retained':True}
    elif args.action=='uninstall':instance.compose('down');result={'containers_removed':True,'user_data_and_volumes_retained':True,'directory':str(instance.root)}
    elif args.action=='backup':result=instance.backup(args.output.resolve())
    elif args.action in ('example','import-reference'):
        path=instance.root/'release/reference.json' if args.action=='example' else args.file.resolve()
        if args.action=='example':release(instance.root/'release')
        with path.open('rb') as stream:raw=stream.read(2*1024**2+1)
        if not 0<len(raw)<=2*1024**2:raise InstallError('Reference import exceeds2MiB.')
        command=['run','--rm','-T','--no-deps','migrate','python','manage.py','import_cpu_reference',
            '--tenant-id',instance.state['tenant'],'--project-id',instance.state['project'],'--name',args.name,'--license','MIT' if args.action=='example' else args.license]
        if args.action=='example':command+=['--example-worker-id',str(instance.state['worker_id'])]
        result=json.loads(instance.compose(*command,data=raw))
        write_json(instance.root/'last-import.json',result)
    else:result=instance.diagnostics()
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    try:main()
    except (InstallError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        print('ModelAnvil: '+str(exc) if isinstance(exc,InstallError) else 'ModelAnvil: installation operation failed. Check status, local Docker and the declared package limits.',file=sys.stderr);sys.exit(1)
