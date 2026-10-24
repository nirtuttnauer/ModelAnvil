"""Installed, explicitly permitted read-only MCP targets; credentials remain on the host."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid
from django.conf import settings
from modelanvil.runners import tool_schema

NAMESPACE=uuid.UUID('6b194297-419e-45c4-92a8-fd765df8030e')
BROKER=Path(__file__).resolve().parents[2]/'scripts/mcp_tool_client.py'
PROTOCOL='2025-11-25'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _identifier(tenant,project,key):return str(uuid.uuid5(NAMESPACE,f'{tenant}:{project}:{key}'))


def _signature(value):
    return hmac.new(settings.SECRET_KEY.encode(),json.dumps(value,sort_keys=True,allow_nan=False).encode(),hashlib.sha256).hexdigest()


def configured(tenant,project):
    scope=f'{tenant}:{project}'
    local={'id':_identifier(tenant,project,'builtin_math'),'name':'Local arithmetic MCP','kind':'builtin_math',
        'allowed_tools':['add','multiply'],'credential':'','read_only':True,'available':True}
    local['signature']=_signature(local);result={local['id']:local}
    installed=getattr(settings,'MODELANVIL_MCP_SERVERS',{}).get(scope,{})
    keys=getattr(settings,'MODELANVIL_MCP_SERVER_KEYS',{}).get(scope,{})
    if not isinstance(installed,dict) or len(installed)>16 or not isinstance(keys,dict):
        identifier=_identifier(tenant,project,'invalid-installed-configuration')
        result[identifier]={'id':identifier,'name':'Unavailable installed MCP configuration','kind':'http','available':False,
            'read_only':True,'allowed_tools':[],'reason':'Review this project’s installed MCP configuration. Local arithmetic remains available.'}
        return result
    for key,value in installed.items():
        if not isinstance(key,str) or not 1<=len(key)<=80:continue
        identifier=_identifier(tenant,project,key)
        try:
            if (not isinstance(value,dict) or set(value)!={'name','endpoint','allowed_tools','credential_id','read_only'}
                    or not isinstance(value['name'],str) or not 1<=len(value['name'])<=80 or value['read_only'] is not True
                    or not isinstance(value['endpoint'],str) or not 1<=len(value['endpoint'])<=2048
                    or not isinstance(value['credential_id'],str) or len(value['credential_id'])>80):raise ValueError()
            allowed=value['allowed_tools']
            if (not isinstance(allowed,list) or not 1<=len(allowed)<=8 or any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',n) for n in allowed)
                    or len(set(allowed))!=len(allowed)):raise ValueError()
            endpoint=urlsplit(value['endpoint'])
            if (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or not endpoint.hostname or not endpoint.path
                    or endpoint.scheme!='https' and not (settings.DEBUG and endpoint.scheme=='http' and endpoint.hostname in ('127.0.0.1','::1'))):raise ValueError()
            credential=keys.get(value['credential_id']) if value['credential_id'] else ''
            if not isinstance(credential,str) or value['credential_id'] and not credential or len(credential)>2048 or '\r' in credential or '\n' in credential:
                raise ValueError()
            if credential and (credential in value['endpoint'] or credential in value['name']):raise ValueError()
            item={'id':identifier,'name':value['name'],'kind':'http','endpoint':value['endpoint'],
                'allowed_tools':sorted(allowed),'credential':credential,'read_only':True,'available':True,
                'allow_http_loopback':bool(settings.DEBUG and endpoint.scheme=='http')}
            item['signature']=_signature(item);result[identifier]=item
        except (ValueError,TypeError):
            # One unavailable customer target must not hide the local implementation or other targets.
            result[identifier]={'id':identifier,'name':'Unavailable installed MCP target','kind':'http','available':False,
                'read_only':True,'allowed_tools':[],'reason':'Review the installed endpoint, read-only tool allowlist and scoped host credential.'}
    return result


def public_target(value):
    return {k:v for k,v in value.items() if k not in ('credential','signature','allow_http_loopback')}


def installed_targets(tenant,project):return [public_target(v) for v in configured(tenant,project).values()]


def resolve(identifier,tenant,project):
    from modelanvil.core.privacy import project_policy
    value=configured(tenant,project).get(str(identifier));policy=project_policy(tenant,project)
    if value is None or not value['available'] or str(identifier) not in policy.get('mcp_targets',[]):
        raise ValueError('Select an installed read-only MCP target explicitly enabled in project Privacy settings.')
    if value['kind']=='http' and policy['offline']:raise ValueError('Remote MCP is disabled while the installation or project is offline.')
    return value


def _broker(value,operation,*,cancelled=lambda:False,lease_descriptor=None,**payload):
    if value.get('available') is not True or value.get('read_only') is not True:raise ValueError('This MCP target is unavailable or consequential.')
    server={k:value[k] for k in ('kind','allowed_tools')}
    if value['kind']=='http':server.update({k:value[k] for k in ('endpoint','credential','allow_http_loopback')})
    raw=json.dumps({'server':server,'operation':operation,**payload},allow_nan=False).encode()
    if len(raw)>65536:raise ValueError('MCP request exceeds64KiB.')
    with tempfile.TemporaryDirectory(prefix='modelanvil-mcp-') as temp:
        env={'PATH':os.environ.get('PATH',''),'HOME':temp,'PYTHONDONTWRITEBYTECODE':'1'}
        child=None;started=time.monotonic()
        try:
            if cancelled():raise ValueError('MCP request cancelled before dispatch.')
            child=subprocess.Popen([sys.executable,'-I',str(BROKER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                env=env,pass_fds=() if lease_descriptor is None else (lease_descriptor,))
            pending=raw
            while True:
                if cancelled():raise ValueError('MCP request cancelled or lost its authorization.')
                if time.monotonic()-started>22:raise ValueError('MCP request exceeded its wall limit.')
                try:
                    output,_=child.communicate(input=pending,timeout=.1);break
                except subprocess.TimeoutExpired:pending=None
            if child.returncode or not 0<len(output)<=256*1024:raise ValueError('MCP discovery or execution did not complete.')
            report=tool_schema.loads(output)
            if (report.get('schema_version')!='modelanvil.mcp-tool-client.v1' or report.get('status')!='completed'
                    or report.get('protocol',{}).get('protocol_version')!=PROTOCOL or not isinstance(report.get('result'),dict)
                    or type(report.get('wall_seconds')) not in (int,float) or not math.isfinite(report['wall_seconds'])
                    or not 0<=report['wall_seconds']<=21):raise ValueError('MCP broker returned incomplete protocol evidence.')
            # The broker never prints credentials; check the host secret again before any model or artifact egress.
            credential=value.get('credential','')
            if credential and credential in json.dumps(report,ensure_ascii=False):raise ValueError('MCP output contains a protected credential.')
            return {**report,'server':public_target(value),'configuration_signature':value['signature']}
        finally:
            if child is not None:
                if child.poll() is None:child.kill()
                child.wait()
                for stream in (child.stdin,child.stdout):
                    if stream is not None and not stream.closed:stream.close()


def discover(identifier,tenant,project,**kwargs):
    value=resolve(identifier,tenant,project);report=_broker(value,'list',**kwargs);result=report['result']
    if not isinstance(result.get('tools'),dict) or set(result['tools'])!=set(value['allowed_tools']) or result.get('catalog_digest')!=digest(result['tools']):
        raise ValueError('MCP discovery differs from its explicit installed allowlist.')
    return report


def call(identifier,tenant,project,*,name,arguments,catalog_digest,configuration_signature,**kwargs):
    value=resolve(identifier,tenant,project)
    if value['signature']!=configuration_signature or name not in value['allowed_tools']:
        raise ValueError('MCP target permissions or scoped credential changed since admission.')
    return _broker(value,'call',name=name,arguments=arguments,catalog_digest=catalog_digest,**kwargs)
