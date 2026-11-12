#!/usr/bin/env python3
"""ANVIL-025 off-host restore: copy a backup into a new docker:dind engine that has never seen ModelAnvil, restore it there
with release 0.1.0, and compare it with the source snapshot. Host side; records exit codes and timings, never secrets.

usage: offhost_restore.py <worktree> <release-0.1.0> <backup-dir> <baseline.json> <credentials> <seed.json> <output-dir>
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

WT,REL,BACKUP,BASELINE,CREDS,SEED,OUT=[Path(a).resolve() for a in sys.argv[1:8]]
TOOLS=Path(__file__).resolve().parent
IMAGE='docker:dind@sha256:08a98015fce594af7c382883bea080ea206de74402a95da9dc52b6428c8cd121'
NAME='anvil025-offhost';VOLUME='anvil025-offhost-docker'
OUT.mkdir(parents=True,mode=0o700,exist_ok=False)
log=[];record={'image':IMAGE,'container':NAME,'volume':VOLUME,'steps':[]}
stamp=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat(timespec='seconds')


def say(text):
    line=stamp(time.time())+' '+text;print(line,flush=True);log.append(line)


def sh(label,command,check=True,timeout=1800,quiet=False,data=None):
    started=time.time();clock=time.monotonic()
    result=subprocess.run(command,capture_output=True,timeout=timeout,input=data)
    seconds=round(time.monotonic()-clock,1)
    record['steps'].append({'step':label,'exit_code':result.returncode,'seconds':seconds,'started_at':stamp(started)})
    say('%s exit %d seconds %.1f'%(label,result.returncode,seconds))
    if not quiet and result.stdout.strip():say(result.stdout.decode(errors='replace').strip()[-4000:])
    if result.returncode and result.stderr.strip():say('stderr: '+result.stderr.decode(errors='replace').strip()[-1500:])
    if check and result.returncode:raise SystemExit(label+' failed')
    return result


def inner(label,script,**kwargs):
    return sh(label,['docker','exec',NAME,'sh','-c',script],**kwargs)


def sha(path):
    value=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):value.update(block)
    return value.hexdigest()


try:
    sh('cleanup-before',['docker','rm','-f',NAME],check=False,quiet=True);sh('volume-cleanup-before',['docker','volume','rm',VOLUME],check=False,quiet=True)
    sh('dind-start',['docker','run','-d','--privileged','--name',NAME,'--platform','linux/arm64','-v',VOLUME+':/var/lib/docker',
        '-v',str(REL)+':/release:ro','-v',str(WT/'scripts')+':/scripts:ro',IMAGE],quiet=True)
    for attempt in range(90):
        if subprocess.run(['docker','exec',NAME,'docker','info'],capture_output=True).returncode==0:break
        time.sleep(1)
    else:raise SystemExit('inner engine did not start')
    record['inner_engine']=json.loads(inner('inner-info',"docker info --format '{{json .}}'",quiet=True).stdout)
    record['inner_engine']={k:record['inner_engine'].get(k) for k in ('ServerVersion','OSType','Architecture','MemTotal','NCPU','Driver','ID','Name')}
    say('inner engine '+json.dumps(record['inner_engine']))
    record['inner_images_before']=int(inner('inner-images-before','docker images -aq | wc -l').stdout.decode().strip())
    record['inner_volumes_before']=int(inner('inner-volumes-before','docker volume ls -q | wc -l').stdout.decode().strip())
    record['inner_containers_before']=int(inner('inner-containers-before','docker ps -aq | wc -l').stdout.decode().strip())
    inner('apk-add','apk add -q --no-progress python3 curl',quiet=True)
    record['inner_python']=inner('inner-python','python3 --version').stdout.decode().strip()
    inner('offhost-dir','mkdir -m 700 /offhost')
    sh('copy-backup',['docker','cp',str(BACKUP),NAME+':/offhost/backup'])
    sh('copy-baseline',['docker','cp',str(BASELINE),NAME+':/offhost/baseline.json'])
    sh('copy-credentials',['docker','cp',str(CREDS),NAME+':/offhost/owner-private.json'],quiet=True)
    sh('copy-helper',['docker','cp',str(TOOLS/'seed.py'),NAME+':/offhost/seed.py'],quiet=True)
    names=['database.dump','artifacts.tar','.env','instance.json','backup.json']
    source={n:sha(BACKUP/n) for n in names}
    copied=dict(reversed(line.split('  /offhost/backup/')) for line in inner('copy-sha256','cd / && sha256sum '+' '.join('/offhost/backup/'+n for n in names),quiet=True).stdout.decode().splitlines())
    record['copy_sha256_equal']={n:copied.get(n)==source[n] for n in names}
    record['copy_bytes']={n:(BACKUP/n).stat().st_size for n in names if n not in ('.env',)}
    record['copy_modes']=inner('copy-modes',"stat -c '%a %n' /offhost/backup/*  /offhost/backup/.env",quiet=True).stdout.decode().split()
    say('copy sha256 equal '+json.dumps(record['copy_sha256_equal'])+' modes '+' '.join(record['copy_modes']))
    completed=(BACKUP/'backup.json').stat().st_mtime
    started=time.time()
    restored=inner('restore','python3 /release/modelanvil.py restore --directory /offhost/restored --backup /offhost/backup --release /release --http-port 43080 --https-port 43443')
    finished=time.time()
    record['restore']={'backup_completed_at':stamp(completed),'restore_started_at':stamp(started),'restore_finished_at':stamp(finished),
        'backup_age_seconds':round(started-completed,1),'restore_seconds':round(finished-started,1),'result':json.loads(restored.stdout)}
    record['inner_images_after']=sorted(inner('inner-images-after','docker images -q --no-trunc | sort -u',quiet=True).stdout.decode().split())
    record['release_images']=json.loads((REL/'release.json').read_text())['images']
    say('inner images after restore '+' '.join(record['inner_images_after']))
    for name in ('health','ready'):
        result=inner('curl-'+name,'curl --fail --silent --show-error --cacert /offhost/restored/ca.crt https://localhost:43443/api/v1/'+name+'/',check=False)
        record['curl_'+name]={'exit_code':result.returncode,'body':result.stdout.decode().strip()}
    compared=inner('drill-snapshot-expect','python3 /scripts/drill_selfhost.py snapshot --directory /offhost/restored --expect /offhost/baseline.json --output /offhost/snapshot.json',check=False,quiet=True)
    record['snapshot_expect']={'exit_code':compared.returncode,**json.loads(compared.stdout)}
    say('snapshot --expect exit %d equal %s problems %s'%(compared.returncode,record['snapshot_expect']['comparison']['equal'],record['snapshot_expect']['comparison']['problems']))
    sh('copy-snapshot-out',['docker','cp',NAME+':/offhost/snapshot.json',str(OUT/'offhost-snapshot.json')])
    seed=json.loads(SEED.read_text())
    chat=inner('api-chat','python3 /offhost/seed.py chat /scripts /offhost/restored /offhost/owner-private.json '+seed['imported_model']+' '+seed['trained_model'],check=False)
    record['api_chat']={'exit_code':chat.returncode,**(json.loads(chat.stdout) if chat.returncode==0 else {})}
    inner('stop','python3 /offhost/restored/release/modelanvil.py stop --directory /offhost/restored',quiet=True)
    inner('uninstall','python3 /offhost/restored/release/modelanvil.py uninstall --directory /offhost/restored',quiet=True)
    project=json.loads(inner('project','cat /offhost/restored/instance.json',quiet=True).stdout)['compose_project'];record['inner_project']=project
    inner('inner-volume-rm','docker volume rm $(docker volume ls -q --filter label=com.docker.compose.project='+project+')')
    record['inner_left']=inner('inner-left','echo containers $(docker ps -aq | wc -l) volumes $(docker volume ls -q | wc -l) networks $(docker network ls -q --filter label=com.docker.compose.project='+project+' | wc -l)').stdout.decode().strip()
    inner('remove-private','rm -rf /offhost/owner-private.json /offhost/backup /offhost/restored')
finally:
    sh('dind-remove',['docker','rm','-f',NAME],check=False,quiet=True);sh('dind-volume-remove',['docker','volume','rm',VOLUME],check=False,quiet=True)
    left=subprocess.run(['sh','-c','echo container $(docker ps -aq -f name=^'+NAME+'$ | wc -l) volume $(docker volume ls -q -f name=^'+VOLUME+'$ | wc -l)'],capture_output=True).stdout.decode().strip()
    record['outer_left']=left;say('outer cleanup: '+left)
    (OUT/'offhost.json').write_text(json.dumps(record,indent=2));(OUT/'offhost.txt').write_text('\n'.join(log)+'\n')
