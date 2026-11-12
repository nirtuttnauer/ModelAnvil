#!/usr/bin/env python3
"""Rehearse backup, upgrade and rollback of an installed self-host instance with the release controllers.

`run` calls only existing controller subcommands, in this order, on new directories the operator passes:

1. `backup` of the installed directory into a new backup directory, with the installed release's controller.
2. `upgrade` to a second verified release, with that release's controller and a second new backup directory.
   `upgrade` takes that backup itself before it swaps the release.
3. Rollback: `restore` of the backup passed to `upgrade`, with the previous release's controller and that release,
   into a new directory. There is no in-place rollback. The upgraded directory and its database are left as they are.

Before the first step the drill records the instance with `snapshot`: the row count of every database table, the
sha256 of every committed artifact checked against its stored bytes, the sha256 of every file in the artifact volume,
the greedy-decoding token ids of every CPU reference model for one prompt, the PostgreSQL and pgvector versions, and
the health and readiness endpoints checked with the instance's own CA. After each step it records the affected instance
again and stops unless the state is unchanged and the instance is healthy.

`snapshot` records one running instance. With --expect it compares the instance against a recorded snapshot, so a
restore on another host can be checked against its source. The drill reads no instance secret, builds nothing, pulls
nothing and deletes nothing. It runs on Python 3.9 with the standard library only.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

SCHEMA='modelanvil.selfhost-drill.v1'
SNAPSHOT_SCHEMA='modelanvil.selfhost-drill-snapshot.v1'
PROMPT='a tiny'
MAX_TOKENS=8
CONTROLLER_TIMEOUT=3600
PROBE_MARK='MODELANVIL-DRILL-PROBE '

# Runs inside the instance's api container (`python -c PROBE <prompt> <max tokens>`). It only reads: table row counts,
# committed artifacts re-hashed from storage, every artifact file, and greedy decoding through the runtime the
# inference API uses for CPU reference models.
PROBE='''import hashlib,json,os,sys
import django
django.setup()
from django.conf import settings
from django.db import connection
from modelanvil.artifacts.models import Artifact
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.runners.local_execution import load_reference_bundle
from modelanvil.runners.models import ModelVersion
from modelanvil.runners.training import general_runtime,registry,runtime
prompt,limit=sys.argv[1],int(sys.argv[2])
def digest(stream):
    value,size=hashlib.sha256(),0
    while True:
        block=stream.read(1048576)
        if not block:break
        value.update(block);size+=len(block)
    return value.hexdigest(),size
with connection.cursor() as cursor:
    tables=sorted(connection.introspection.table_names(cursor))
    rows={}
    for table in tables:
        cursor.execute('SELECT COUNT(*) FROM '+connection.ops.quote_name(table));rows[table]=cursor.fetchone()[0]
    server=vector=None
    if connection.vendor=='postgresql':
        cursor.execute('SHOW server_version');server=cursor.fetchone()[0]
        cursor.execute("SELECT extversion FROM pg_extension WHERE extname='vector'");found=cursor.fetchone();vector=found[0] if found else None
backend=artifact_storage_backend();artifacts=[]
for item in Artifact.all_objects.filter(state='committed').order_by('pk'):
    with backend.open(item.tenant_id,item.object_key) as stream:stored,size=digest(stream)
    artifacts.append({'artifact_id':str(item.artifact_id),'sha256':item.sha256,'byte_size':item.byte_size,'stored_sha256':stored,'stored_bytes':size})
root=str(settings.MODELANVIL['artifact_root']);files=[]
for base,directories,names in os.walk(root):
    directories.sort()
    for name in sorted(names):
        path=os.path.join(base,name);relative=os.path.relpath(path,root)
        if os.path.islink(path) or not os.path.isfile(path):files.append({'path':relative,'regular_file':False});continue
        with open(path,'rb') as stream:value,size=digest(stream)
        files.append({'path':relative,'bytes':size,'sha256':value})
models=[]
for version in ModelVersion.all_objects.filter(architecture_ref__in=[runtime.RUNTIME_ID,general_runtime.RUNTIME_ID]).order_by('pk'):
    entry={'model_version_id':str(version.model_version_id),'artifact_manifest_id':version.artifact_manifest_id,'state':version.state}
    try:
        bundle,_,_=load_reference_bundle(version,tenant=version.tenant_id,project=version.project_id)
        output=registry.generate_completion(bundle,prompt,max_new_tokens=limit)
        entry.update(generated_token_ids=output['generated_token_ids'],completion=output['completion'])
    except (ValueError,KeyError,TypeError) as exc:entry['error']=type(exc).__name__+': '+str(exc)[:200]
    models.append(entry)
print(%r+json.dumps({'database_vendor':connection.vendor,'server_version':server,'pgvector':vector,'rows':rows,
    'artifacts':artifacts,'artifact_files':files,'models':models}))
'''%PROBE_MARK


class DrillError(ValueError):pass


FAILURES=(OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError)


def reason(exc):
    return str(exc) if isinstance(exc,DrillError) else type(exc).__name__+': '+str(exc)[:300]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def stamp(seconds):
    return datetime.datetime.fromtimestamp(seconds,datetime.timezone.utc).isoformat(timespec='seconds')


def clean_env():
    return {'PATH':os.environ.get('PATH',''),'HOME':os.environ.get('HOME',str(Path.home()))}


def instance_state(directory):
    path=directory/'instance.json'
    if not path.is_file():raise DrillError('Not an installed self-host directory (needs instance.json): '+str(directory))
    state=json.loads(path.read_text())
    if not isinstance(state,dict) or not str(state.get('compose_project','')).startswith('modelanvil-local-') or not state.get('version'):
        raise DrillError('The instance record is incomplete: '+str(path))
    return state


def release_manifest(directory):
    if not (directory/'modelanvil.py').is_file() or not (directory/'release.json').is_file():
        raise DrillError('Not a built release (needs modelanvil.py and release.json): '+str(directory))
    manifest=json.loads((directory/'release.json').read_text())
    if not isinstance(manifest,dict) or not manifest.get('version') or not isinstance(manifest.get('images'),dict):
        raise DrillError('The release manifest is incomplete: '+str(directory))
    return manifest


def compose(directory,state,*args,timeout=900):
    """One docker compose call on the instance's own project; Docker diagnostics go to a private log in the instance."""
    command=['docker','compose','--env-file',str(directory/'.env'),'-p',state['compose_project'],'-f',str(directory/'release/compose.yaml'),*args]
    try:result=subprocess.run(command,capture_output=True,env=clean_env(),timeout=timeout)
    except subprocess.TimeoutExpired:raise DrillError('docker compose '+args[0]+' exceeded its time limit for '+str(directory)) from None
    if result.returncode:
        with open(directory/'drill-private.log','ab',opener=lambda p,flags:os.open(p,flags,0o600)) as stream:
            stream.write(('Operation: compose '+args[0]+'\n').encode()+result.stderr[-65536:]+b'\n')
        raise DrillError('docker compose '+args[0]+' failed for '+str(directory)+'; inspect drill-private.log there.')
    return result.stdout.decode(errors='replace')


def health(directory,state):
    """GET health and readiness over HTTPS, trusting only the instance's own local CA."""
    try:context=ssl.create_default_context(cafile=str(directory/'ca.crt'))
    except (OSError,ssl.SSLError):return {name:{'status':None,'error':'instance CA unavailable'} for name in ('health','ready')}
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
    result={}
    for name in ('health','ready'):
        try:
            with opener.open(state['origin']+'/api/v1/'+name+'/',timeout=15) as response:
                result[name]={'status':response.status,'body':json.loads(response.read(65536) or b'null')}
        except urllib.error.HTTPError as exc:result[name]={'status':exc.code}
        except (OSError,ValueError) as exc:result[name]={'status':None,'error':type(exc).__name__}
    return result


def healthy(snapshot):
    checks=snapshot.get('health',{})
    return checks.get('health',{}).get('status')==200 and checks['health'].get('body')=={'status':'ok'} and checks.get('ready',{}).get('status')==200


def snapshot(directory,prompt=PROMPT,max_tokens=MAX_TOKENS):
    directory=directory.resolve();state=instance_state(directory);taken=now()
    raw=compose(directory,state,'exec','-T','api','python','-c',PROBE,prompt,str(max_tokens))
    line=next((item for item in reversed(raw.splitlines()) if item.startswith(PROBE_MARK)),None)
    if line is None:raise DrillError('The instance probe returned no result for '+str(directory))
    probe=json.loads(line[len(PROBE_MARK):])
    manifest=json.loads((directory/'release/release.json').read_text())
    return {'schema_version':SNAPSHOT_SCHEMA,'taken_at':taken,'directory':str(directory),'compose_project':state['compose_project'],
        'origin':state.get('origin'),'version':state['version'],'release':{'version':manifest.get('version'),'source_revision':manifest.get('source_revision'),'images':manifest.get('images')},
        'health':health(directory,state),'prompt':prompt,'max_tokens':max_tokens,**probe}


def usable(reference):
    """A snapshot that can show a restore: healthy, with artifacts whose stored bytes match and a model that generates."""
    problems=[]
    if not healthy(reference):problems.append('the instance is not healthy')
    if not reference['artifacts']:problems.append('there is no committed artifact')
    if not reference['models']:problems.append('there is no CPU reference model; import the example and train it first')
    problems+=['model '+m['model_version_id']+' did not generate: '+m['error'] for m in reference['models'] if 'generated_token_ids' not in m]
    problems+=['artifact '+a['artifact_id']+' does not match its stored bytes' for a in reference['artifacts'] if (a['stored_sha256'],a['stored_bytes'])!=(a['sha256'],a['byte_size'])]
    return problems


def compare(reference,candidate):
    """Every check a restore, upgrade or backup must leave unchanged, with each difference named."""
    problems=[]
    tables=sorted(set(reference['rows'])|set(candidate['rows']))
    differing={t:[reference['rows'].get(t),candidate['rows'].get(t)] for t in tables if reference['rows'].get(t)!=candidate['rows'].get(t)}
    if differing:problems.append('row counts differ in '+', '.join(sorted(differing)))
    pins=lambda value:sorted((a['artifact_id'],a['sha256'],a['byte_size']) for a in value['artifacts'])
    if pins(reference)!=pins(candidate):problems.append('committed artifact ids, sha256 or sizes differ')
    mismatched=[a['artifact_id'] for a in candidate['artifacts'] if (a['stored_sha256'],a['stored_bytes'])!=(a['sha256'],a['byte_size'])]
    if mismatched:problems.append('stored bytes differ from the recorded sha256 for '+', '.join(mismatched))
    if reference['artifact_files']!=candidate['artifact_files']:problems.append('artifact volume files or their sha256 differ')
    tokens=lambda value:{m['model_version_id']:m.get('generated_token_ids') for m in value['models']}
    if (reference['prompt'],reference['max_tokens'])!=(candidate['prompt'],candidate['max_tokens']):problems.append('the snapshots used different prompts')
    elif tokens(reference)!=tokens(candidate):problems.append('greedy-decoding tokens differ')
    if any('generated_token_ids' not in m for m in candidate['models']):problems.append('a model failed to generate')
    for field in ('database_vendor','server_version','pgvector'):
        if reference.get(field)!=candidate.get(field):problems.append(field+' differs')
    if not healthy(candidate):problems.append('the health check failed')
    return {'equal':not problems,'problems':problems,'tables':len(tables),'tables_with_rows':sum(1 for t in tables if candidate['rows'].get(t)),
        'rows_total':sum(candidate['rows'].values()),'differing_tables':differing,'committed_artifacts':len(candidate['artifacts']),
        'artifact_files':len(candidate['artifact_files']),'models':len(candidate['models']),'pgvector':[reference.get('pgvector'),candidate.get('pgvector')],
        'server_version':[reference.get('server_version'),candidate.get('server_version')],'health':candidate.get('health')}


def write_new(path,value):
    with open(path,'x') as stream:json.dump(value,stream,indent=2);stream.write('\n')


def inside(path,parent):
    return path==parent or parent in path.parents


def preflight(args):
    """Refusals that run before any controller call; nothing is created or changed."""
    paths={name:getattr(args,name).expanduser().resolve() for name in ('directory','previous_release','release','backup','upgrade_backup','rollback_directory','record')}
    state=instance_state(paths['directory'])
    installed=release_manifest(paths['directory']/'release');previous=release_manifest(paths['previous_release']);target=release_manifest(paths['release'])
    if previous['version']!=state['version'] or installed['version']!=state['version'] or previous['images']!=installed['images']:
        raise DrillError('--previous-release must be the release this directory runs ('+state['version']+'); rollback restores the upgrade backup with it.')
    if target['version']==state['version']:raise DrillError('--release must be a different verified release; '+state['version']+' is already installed.')
    created=('backup','upgrade_backup','rollback_directory','record')
    for name in created:
        if paths[name].exists():raise DrillError('Use a new directory for --'+name.replace('_','-')+'; existing recovery points and instances are never reused.')
        if inside(paths[name],paths['directory']):raise DrillError('Keep --'+name.replace('_','-')+' outside the installed directory.')
    if len({paths[name] for name in created})<len(created):raise DrillError('The backup, upgrade backup, rollback and record directories must differ.')
    return paths,state,previous,target


def controller(report,name,command):
    """Run one controller subcommand and record its exit code, duration and JSON result; stop the drill if it fails."""
    started=time.time();clock=time.monotonic()
    try:result=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,timeout=CONTROLLER_TIMEOUT)
    except subprocess.TimeoutExpired:result=None
    entry={'step':name,'command':['python3',*command[1:]],'started_at':stamp(started),'seconds':round(time.monotonic()-clock,1),
        'exit_code':None if result is None else result.returncode}
    report['steps'].append(entry)
    if result is None:raise DrillError(name+' exceeded '+str(CONTROLLER_TIMEOUT)+' seconds.')
    if result.returncode:
        # The controller prints one 'ModelAnvil: ...' line; Docker detail stays in its private log.
        entry['error']=(result.stderr.decode(errors='replace').strip().splitlines() or [''])[-1]
        raise DrillError(name+' failed with exit code '+str(result.returncode)+': '+entry['error'])
    try:entry['result']=json.loads(result.stdout)
    except ValueError:raise DrillError(name+' did not return its JSON result.') from None
    return entry


def backup_completed(path):
    """The controller writes backup.json last, after hashing the paired dump and archive."""
    marker=path/'backup.json'
    if not marker.is_file():raise DrillError('The backup has no backup.json: '+str(path))
    saved=json.loads(marker.read_text());return marker.stat().st_mtime,saved.get('release')


def run(args):
    try:paths,state,previous,target=preflight(args)
    except FAILURES as exc:
        print('ModelAnvil drill: '+reason(exc),file=sys.stderr);return 2
    directory=paths['directory'];record=paths['record']
    report={'schema_version':SCHEMA,'started_at':now(),'directory':str(directory),'compose_project':state['compose_project'],
        'previous_release':{'path':str(paths['previous_release']),'version':previous['version'],'source_revision':previous.get('source_revision')},
        'release':{'path':str(paths['release']),'version':target['version'],'source_revision':target.get('source_revision')},
        'prompt':args.prompt,'max_tokens':args.max_tokens,'steps':[],'checks':{},'passed':False,'production_qualified':False}
    record.mkdir(parents=True,mode=0o700)
    def finish(code,error=None):
        if error:report['error']=error
        report['finished_at']=now();write_new(record/'report.json',report);print(json.dumps(report,indent=2))
        if error:print('ModelAnvil drill: '+error,file=sys.stderr)
        return code
    def check(name,where,version):
        current=snapshot(where,args.prompt,args.max_tokens);write_new(record/(name.replace('_','-')+'.json'),current)
        result=compare(baseline,current)
        if current['version']!=version:result['problems'].append('instance version is '+current['version']+', expected '+version);result['equal']=False
        report['checks'][name]=result
        if not result['equal']:raise DrillError(name+': '+'; '.join(result['problems']))
    try:
        baseline=snapshot(directory,args.prompt,args.max_tokens);write_new(record/'baseline.json',baseline)
        problems=usable(baseline)
        if problems:raise DrillError('The installed instance cannot show a restore: '+'; '.join(problems))
        report['baseline']={'taken_at':baseline['taken_at'],'tables':len(baseline['rows']),'rows_total':sum(baseline['rows'].values()),
            'committed_artifacts':len(baseline['artifacts']),'artifact_files':len(baseline['artifact_files']),'models':len(baseline['models']),
            'server_version':baseline['server_version'],'pgvector':baseline['pgvector'],'health':baseline['health']}
    except FAILURES as exc:return finish(2,reason(exc))
    python=sys.executable;forwarded=[]
    for flag,value in (('--host',args.rollback_host),('--bind',args.rollback_bind),('--http-port',args.rollback_http_port),('--https-port',args.rollback_https_port)):
        if value is not None:forwarded+=[flag,str(value)]
    try:
        controller(report,'backup',[python,str(directory/'release/modelanvil.py'),'backup','--directory',str(directory),'--output',str(paths['backup'])])
        completed,_=backup_completed(paths['backup']);report['backup']={'path':str(paths['backup']),'completed_at':stamp(completed)}
        check('after_backup',directory,state['version'])
        controller(report,'upgrade',[python,str(paths['release']/'modelanvil.py'),'upgrade','--directory',str(directory),'--release',str(paths['release']),'--backup',str(paths['upgrade_backup'])])
        check('after_upgrade',directory,target['version'])
        completed,saved=backup_completed(paths['upgrade_backup'])
        if saved!=previous['version']:raise DrillError('The upgrade backup records release '+str(saved)+', not '+previous['version']+'.')
        started=time.time()
        report['rollback']={'directory':str(paths['rollback_directory']),'backup':str(paths['upgrade_backup']),'backup_release':saved,
            'backup_completed_at':stamp(completed),'restore_started_at':stamp(started),'backup_age_seconds':round(started-completed,1)}
        entry=controller(report,'rollback',[python,str(paths['previous_release']/'modelanvil.py'),'restore','--directory',str(paths['rollback_directory']),
            '--backup',str(paths['upgrade_backup']),'--release',str(paths['previous_release']),*forwarded])
        report['rollback']['restore_seconds']=entry['seconds']
        check('after_rollback',paths['rollback_directory'],previous['version'])
    except FAILURES as exc:return finish(1,reason(exc))
    report['passed']=True
    return finish(0)


def snapshot_command(args):
    expected=None
    try:
        if args.expect:
            expected=json.loads(args.expect.read_text())
            if expected.get('schema_version')!=SNAPSHOT_SCHEMA:raise DrillError('--expect needs a snapshot written by this drill.')
        if args.output and args.output.exists():raise DrillError('Use a new --output file.')
        prompt,limit=(expected['prompt'],expected['max_tokens']) if expected else (args.prompt,args.max_tokens)
        current=snapshot(args.directory.expanduser(),prompt,limit)
    except DrillError as exc:
        print('ModelAnvil drill: '+str(exc),file=sys.stderr);return 2
    if args.output:write_new(args.output,current)
    if expected is None:
        problems=usable(current);print(json.dumps({'snapshot':current,'usable_for_a_restore_check':not problems,'problems':problems},indent=2));return 0
    result=compare(expected,current);print(json.dumps({'comparison':result,'expected_taken_at':expected['taken_at'],'snapshot_taken_at':current['taken_at']},indent=2))
    return 0 if result['equal'] else 1


def prompt(value):
    if not 0<len(value)<=64:raise argparse.ArgumentTypeError('use a prompt of 1-64 characters')
    return value


def tokens(value):
    number=int(value)
    if not 1<=number<=32:raise argparse.ArgumentTypeError('use 1-32 tokens')
    return number


def parse(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter);sub=parser.add_subparsers(dest='action',required=True)
    drill=sub.add_parser('run',help='backup, upgrade, then roll back by restoring the upgrade backup with the previous release')
    drill.add_argument('--directory',type=Path,required=True,help='Installed instance directory.')
    drill.add_argument('--previous-release',type=Path,required=True,help='The verified release this directory runs; used for the rollback restore.')
    drill.add_argument('--release',type=Path,required=True,help='The second verified release to upgrade to.')
    drill.add_argument('--backup',type=Path,required=True,help='New directory for the step-1 backup.')
    drill.add_argument('--upgrade-backup',type=Path,required=True,help='New directory for the backup that upgrade takes.')
    drill.add_argument('--rollback-directory',type=Path,required=True,help='New directory for the rollback restore.')
    drill.add_argument('--record',type=Path,required=True,help='New directory for report.json and the snapshots.')
    drill.add_argument('--rollback-host');drill.add_argument('--rollback-bind')
    drill.add_argument('--rollback-http-port',type=int);drill.add_argument('--rollback-https-port',type=int)
    drill.add_argument('--prompt',type=prompt,default=PROMPT);drill.add_argument('--max-tokens',type=tokens,default=MAX_TOKENS)
    shot=sub.add_parser('snapshot',help='record one running instance, or compare it with --expect')
    shot.add_argument('--directory',type=Path,required=True);shot.add_argument('--output',type=Path,help='New file for the snapshot JSON.')
    shot.add_argument('--expect',type=Path,help='A snapshot to compare with; its prompt and token limit are reused.')
    shot.add_argument('--prompt',type=prompt,default=PROMPT);shot.add_argument('--max-tokens',type=tokens,default=MAX_TOKENS)
    return parser.parse_args(argv)


def main(argv=None):
    args=parse(argv)
    try:return run(args) if args.action=='run' else snapshot_command(args)
    except FAILURES as exc:
        print('ModelAnvil drill: operation failed ('+type(exc).__name__+'). Inspect the record directory and the private logs.',file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
