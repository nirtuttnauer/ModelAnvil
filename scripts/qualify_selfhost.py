#!/usr/bin/env python3
"""Exercise a provisioned self-host release in fresh private instances; no public deployment."""
import argparse
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


def port():
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));return listener.getsockname()[1]


class Client:
    def __init__(self,root,credentials):
        self.root=root;self.state=json.loads((root/'instance.json').read_text());self.origin=self.state['origin'];self.cookies=http.cookiejar.CookieJar()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(root/'ca.crt'))),urllib.request.HTTPCookieProcessor(self.cookies))
        self.request('/api/v1/accounts/status/');self.request('/api/v1/accounts/signin/',{k:credentials[k] for k in ('email','password')})

    def request(self,path,value=None,expected=200,headers=None):
        fields={'X-Project-ID':self.state['project']};raw=None
        if value is not None:
            raw=json.dumps(value).encode();fields.update({'Content-Type':'application/json','Origin':self.origin,'Referer':self.origin+'/',
                'X-CSRFToken':next(c.value for c in self.cookies if c.name=='csrftoken')})
        fields.update(headers or {})
        try:response=self.opener.open(urllib.request.Request(self.origin+path,data=raw,headers=fields),timeout=30)
        except urllib.error.HTTPError as exc:response=exc
        with response:
            data=response.read();assert response.status==expected,'Unexpected HTTP status at '+path
            return json.loads(data) if response.headers.get_content_type()=='application/json' else data

    def snapshot(self):
        def rows(path):
            result=[]
            while path:
                page=self.request(path);result+=page['results'];path=page.get('next')
                if path:
                    assert path.startswith(self.origin+'/api/v1/');path=path[len(self.origin):]
            return result
        models=rows('/api/v1/model-versions/');runs=rows('/api/v1/training-runs/');budgets=rows('/api/v1/budget-reservations/');artifacts=rows('/api/v1/artifacts/')
        verified=[]
        for item in artifacts:
            if item['state']!='committed':continue
            request=urllib.request.Request(self.origin+'/api/v1/artifacts/'+item['artifact_id']+'/download/',headers={'X-Project-ID':self.state['project']})
            with self.opener.open(request,timeout=30) as response:raw=response.read(2*1024**2+1)
            assert len(raw)==item['byte_size'] and hashlib.sha256(raw).hexdigest()==item['sha256'];verified.append((item['artifact_id'],item['sha256']))
        return {'models':sorted((m['model_version_id'],m['artifact_manifest_id'],m['state']) for m in models),
            'runs':sorted((r['run_id'],r['status'],r['current_step'],r['output_model_version_uuid']) for r in runs),
            'budgets':sorted((b['job_id'],b['state'],b['settled_amount']) for b in budgets),'artifacts':sorted(verified)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',type=Path,required=True);parser.add_argument('--upgrade-release',type=Path)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--retain',action='store_true',help='Retain this qualification’s private synthetic instances for inspection.')
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,mode=0o700,exist_ok=False);output.chmod(0o700)
    release=args.release.resolve();controller=release/'modelanvil.py';primary=output/'instance';restored=output/'restored';backup=output/'backup'
    credentials={'email':'qualification@example.test','name':'Explicit selfhost qualification','password':secrets.token_urlsafe(32)}
    private=output/'credentials-private.json';private.write_text(json.dumps(credentials));private.chmod(0o600)
    roots=[primary,restored];started=time.monotonic();proof={'schema_version':'modelanvil.selfhost-qualification.v1','production_qualified':False}
    def cli(label,*arguments,data=None):
        with (output/(label+'.json')).open('wb') as result,(output/(label+'-private.log')).open('wb') as errors:
            code=subprocess.run([sys.executable,str(controller),*arguments],input=data,stdout=result,stderr=errors,timeout=360).returncode
        assert code==0,'Controller operation failed: '+label+'; inspect its private log.'
        return json.loads((output/(label+'.json')).read_text())
    def ports():
        first,second=port(),port()
        while first==second:second=port()
        return ['--http-port',str(first),'--https-port',str(second)]
    try:
        cli('install','install','--directory',str(primary),'--release',str(release),'--credentials-stdin',*ports(),data=json.dumps(credentials).encode())
        client=Client(primary,credentials);assert client.request('/api/v1/privacy/')['offline'] is True
        imported=cli('explicit-import','example','--directory',str(primary),'--name','qualified-offline-example')
        body={'model':imported['model'],'messages':[{'role':'user','content':'a tiny'}],'max_tokens':4,'temperature':0,'seed':42,'device':'cpu','prompt_format':'plain'}
        initial=client.request('/api/v1/inference/chat/completions',body);assert initial['usage']['completion_tokens']>0
        preview=client.request('/api/v1/training-runs/preflight/',imported['launch']);assert preview['status']=='approved'
        run=client.request('/api/v1/training-runs/',{**imported['launch'],'preflight_token':preview['preflight_token']},expected=201,headers={'Idempotency-Key':str(uuid.uuid4())})
        deadline=time.monotonic()+120
        while run['status'] not in ('completed','failed','cancelled'):
            assert time.monotonic()<deadline,'CPU reference recipe exceeded its qualification bound.'
            time.sleep(.2);run=client.request('/api/v1/training-runs/'+run['run_id']+'/')
        assert run['status']=='completed' and run['current_step']==4 and len(run['checkpoints'])==4
        exported=client.request('/api/v1/training-runs/'+run['run_id']+'/export/',{})['bundle'];source=json.loads((release/'reference.json').read_text())
        weights=base64.b64decode(exported['model.safetensors.b64'],validate=True);output_sha=hashlib.sha256(weights).hexdigest()
        assert output_sha==exported['weights_manifest.json']['weights_sha256'] and output_sha!=source['weights_manifest.json']['weights_sha256']
        blocked=client.request('/api/v1/model-imports/inspect/',{'repo_id':'HuggingFaceTB/SmolLM2-135M','revision':'a'*40},expected=400);assert 'offline' in json.dumps(blocked).lower()
        before=client.snapshot();cli('backup','backup','--directory',str(primary),'--output',str(backup))
        cli('restore','restore','--directory',str(restored),'--backup',str(backup),'--release',str(release),*ports())
        clone=Client(restored,credentials);assert clone.snapshot()==before and clone.state['compose_project']!=client.state['compose_project']
        proof.update(fresh_install=True,verified_tls=True,owner_authentication=True,explicit_local_model_import=True,offline=True,external_acquisition_refused=True,
            actual_optimizer_steps=4,checkpoint_count=4,base_weights_sha256=source['weights_manifest.json']['weights_sha256'],trained_weights_sha256=output_sha,
            isolated_restore_checked_state_and_all_artifact_hashes_equal=True)
        if args.upgrade_release:
            controller=args.upgrade_release.resolve()/'modelanvil.py'
            cli('upgrade','upgrade','--directory',str(primary),'--release',str(args.upgrade_release.resolve()),'--backup',str(output/'upgrade-backup'))
            upgraded=Client(primary,credentials);assert upgraded.snapshot()==before
            assert upgraded.state['version']!=client.state['version'];client=upgraded;proof['upgrade_preserved_checked_state_and_all_artifact_hashes']=True
        else:proof['upgrade']='not_run; supply a distinct verified --upgrade-release'
        project=client.state['compose_project'];volumes=lambda:sorted(subprocess.check_output(['docker','volume','ls','--filter','label=com.docker.compose.project='+project,'--format','{{.Name}}'],text=True,env={'PATH':os.environ.get('PATH',''),'HOME':str(Path.home())}).splitlines())
        prior=volumes();assert len(prior)==4
        cli('uninstall','uninstall','--directory',str(primary));assert volumes()==prior
        cli('retained-restart','start','--directory',str(primary));assert Client(primary,credentials).snapshot()==before
        proof.update(uninstall_retained_four_data_volumes=True,retained_installation_restarted=True,artifact_count=len(before['artifacts']),source_release=json.loads((release/'release.json').read_text())['version'],
            qualification_scope='Small numerical CPU reference pipeline and local-CA Docker package; no pretrained/task quality, public DNS/ACME, physical second host or native signing qualification.')
    finally:
        if not args.retain:
            for root in roots:
                # Only private synthetic projects created by this fresh-output qualification may be removed.
                assert root.parent==output and root.name in ('instance','restored')
                if not (root/'instance.json').is_file():continue
                state=json.loads((root/'instance.json').read_text());assert state['compose_project'].startswith('modelanvil-local-')
                subprocess.run(['docker','compose','--env-file',str(root/'.env'),'-p',state['compose_project'],'-f',str(root/'release/compose.yaml'),
                    'down','--volumes','--remove-orphans','--timeout','10'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,env={'PATH':os.environ.get('PATH',''),'HOME':str(Path.home())})
            proof['owned_synthetic_projects_removed']=True
    proof['wall_seconds']=time.monotonic()-started
    encoded=json.dumps(proof,indent=2);assert credentials['password'] not in encoded
    (output/'qualification.json').write_text(encoded);print(encoded)


if __name__=='__main__':main()
