"""Fixed bounded MCP broker; source/permissions are admitted by the project-scoped parent."""
import base64
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit,quote
import urllib.request

PROTOCOL='2025-11-25'
MAX_BYTES=256*1024
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bounded_function_schema',ROOT/'modelanvil/runners/tool_schema.py')
function_schema=importlib.util.module_from_spec(spec);spec.loader.exec_module(function_schema)


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def redact(value,secret):
    if not secret:return value
    variants=(secret,quote(secret,safe=''),base64.b64encode(secret.encode()).decode())
    if isinstance(value,str):
        for text in variants:value=value.replace(text,'[redacted credential]')
        return value
    if isinstance(value,list):return [redact(v,secret) for v in value]
    if isinstance(value,dict):return {redact(k,secret):redact(v,secret) for k,v in value.items()}
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Session:
    def __init__(self,server):
        self.server=server;self.identifier=0;self.session=None;self.proc=None;self.temporary=None
        if server['kind']=='builtin_math':
            self.temporary=tempfile.TemporaryDirectory(prefix='modelanvil-mcp-server-')
            self.proc=subprocess.Popen([sys.executable,'-I',str(ROOT/'scripts/bounded_math_mcp.py')],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                env={'PATH':os.environ.get('PATH',''),'HOME':self.temporary.name})
        elif server['kind']=='http':
            endpoint=urlsplit(server['endpoint'])
            if (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or not endpoint.hostname
                    or endpoint.scheme!='https' and not (server.get('allow_http_loopback') is True and endpoint.scheme=='http' and endpoint.hostname in ('127.0.0.1','::1'))):
                raise ValueError('Unsupported MCP endpoint.')
            secret=server.get('credential','')
            if not isinstance(secret,str) or len(secret)>2048 or '\r' in secret or '\n' in secret:raise ValueError('Invalid MCP credential.')
            self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        else:raise ValueError('Unsupported installed MCP transport.')

    def close(self):
        if self.proc is not None:
            self.proc.stdin.close()
            if self.proc.poll() is None:self.proc.terminate()
            try:self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
            self.proc.stdout.close()
        if self.temporary is not None:self.temporary.cleanup()

    def send(self,method,params,*,notification=False):
        self.identifier+=1;identifier=self.identifier
        request={'jsonrpc':'2.0','method':method,'params':params}
        if not notification:request['id']=identifier
        raw=json.dumps(request,allow_nan=False).encode()
        if len(raw)>65536:raise ValueError('MCP request exceeds its bound.')
        if self.proc is not None:
            self.proc.stdin.write(raw+b'\n');self.proc.stdin.flush()
            if notification:return None
            deadline=time.monotonic()+8
            with selectors.DefaultSelector() as selector:
                selector.register(self.proc.stdout,selectors.EVENT_READ)
                for _ in range(8):
                    remaining=deadline-time.monotonic()
                    if remaining<=0 or not selector.select(remaining):raise ValueError('MCP response timed out.')
                    line=self.proc.stdout.readline(MAX_BYTES+1)
                    if not line or len(line)>MAX_BYTES:raise ValueError('MCP response exceeds its bound.')
                    value=function_schema.loads(line)
                    if 'method' in value:raise ValueError('Server-initiated MCP requests are not enabled.')
                    if value.get('id')==identifier:return self.result(value,identifier)
                raise ValueError('MCP response did not match its request.')
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream',
            'MCP-Protocol-Version':PROTOCOL,'Mcp-Method':method}
        if method=='tools/call':headers['Mcp-Name']=params['name']
        if self.session:headers['Mcp-Session-Id']=self.session
        if self.server.get('credential'):headers['Authorization']='Bearer '+self.server['credential']
        req=urllib.request.Request(self.server['endpoint'],data=raw,headers=headers,method='POST')
        with self.opener.open(req,timeout=1) as response:
            if notification:
                if response.status not in (200,202,204):raise ValueError('MCP notification was not accepted.')
                return None
            session=response.headers.get('Mcp-Session-Id')
            if session:
                if not re.fullmatch(r'[\x21-\x7e]{1,128}',session):raise ValueError('MCP session ID exceeds its bound.')
                self.session=session
            media=response.headers.get_content_type();payload=bytearray();started=time.monotonic()
            if media not in ('application/json','text/event-stream'):raise ValueError('MCP requires JSON or bounded SSE.')
            while True:
                if time.monotonic()-started>8:raise ValueError('MCP response timed out.')
                block=response.read1(4096)
                if not block:break
                payload.extend(block)
                if len(payload)>MAX_BYTES:raise ValueError('MCP response exceeds its bound.')
                if media=='text/event-stream':
                    frames=bytes(payload).replace(b'\r\n',b'\n').split(b'\n\n')
                    for frame in frames[:-1]:
                        data=b'\n'.join(line[5:].lstrip(b' ') for line in frame.split(b'\n') if line.startswith(b'data:'))
                        if not data:continue
                        value=function_schema.loads(data)
                        if 'method' in value:raise ValueError('Server-initiated MCP requests are not enabled.')
                        if value.get('id')==identifier:return self.result(value,identifier)
            if media=='text/event-stream':raise ValueError('MCP SSE has no complete result.')
            return self.result(function_schema.loads(bytes(payload)),identifier)

    def result(self,value,identifier):
        if not isinstance(value,dict) or value.get('jsonrpc')!='2.0' or type(value.get('id')) is not int or value['id']!=identifier or 'method' in value:
            raise ValueError('MCP response identity differs.')
        if 'error' in value:raise ValueError('The MCP server returned a request error.')
        if not isinstance(value.get('result'),dict):raise ValueError('MCP result must be an object.')
        return redact(value['result'],self.server.get('credential',''))

    def initialize(self):
        result=self.send('initialize',{'protocolVersion':PROTOCOL,'capabilities':{},'clientInfo':{'name':'ModelAnvil bounded tools','version':'1'}})
        if result.get('protocolVersion')!=PROTOCOL or not isinstance(result.get('capabilities',{}).get('tools'),dict):
            raise ValueError('The MCP server does not support the qualified tools/protocol profile.')
        self.send('notifications/initialized',{},notification=True)
        return {'protocol_version':PROTOCOL,'server_info':result.get('serverInfo',{})}

    def catalog(self,allowed):
        found={};cursor=None
        for _ in range(4):
            result=self.send('tools/list',{'cursor':cursor} if cursor else {})
            values=result.get('tools')
            if not isinstance(values,list) or len(values)>128:raise ValueError('MCP tool catalog exceeds its bound.')
            for value in values:
                if not isinstance(value,dict) or not isinstance(value.get('name'),str):raise ValueError('MCP tool descriptor is malformed.')
                if value['name'] not in allowed:continue
                if value['name'] in found:raise ValueError('MCP tools contain duplicate names.')
                found[value['name']]={k:value[k] for k in ('name','description','inputSchema') if k in value}
            cursor=result.get('nextCursor')
            if not cursor or set(found)==set(allowed):break
            if not isinstance(cursor,str) or len(cursor)>256:raise ValueError('MCP pagination cursor exceeds its bound.')
        if set(found)!=set(allowed):raise ValueError('An installed allowed MCP tool is unavailable.')
        for tool in found.values():function_schema.schema(tool['inputSchema'])
        return found


def main():
    signal.alarm(20)
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(5,5))
    if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(512*1024**2,512*1024**2))
    raw=sys.stdin.buffer.read(65537)
    if not 0<len(raw)<=65536:raise ValueError('MCP broker input exceeds its bound.')
    request=function_schema.loads(raw);server=request['server'];allowed=server['allowed_tools']
    if (not isinstance(allowed,list) or not 1<=len(allowed)<=8 or len(set(allowed))!=len(allowed)
            or any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',n) for n in allowed)):
        raise ValueError('MCP broker needs an explicit bounded tool allowlist.')
    started=time.monotonic();session=Session(server)
    try:
        protocol=session.initialize();catalog=session.catalog(allowed)
        if request['operation']=='list':result={'tools':catalog,'catalog_digest':digest(catalog)}
        elif request['operation']=='call':
            name=request['name'];args=request['arguments']
            if name not in catalog or request['catalog_digest']!=digest(catalog):raise ValueError('MCP tool catalog or selection changed.')
            function_schema.bounded(args)
            from jsonschema import Draft202012Validator
            Draft202012Validator(catalog[name]['inputSchema']).validate(args)
            result=session.send('tools/call',{'name':name,'arguments':args})
            content=result.get('content',[])
            if (not isinstance(content,list) or len(content)>8 or type(result.get('isError',False)) is not bool
                    or any(not isinstance(c,dict) or c.get('type')!='text' or not isinstance(c.get('text'),str) or len(c['text'].encode())>16384 for c in content)):
                raise ValueError('Only bounded textual MCP tool results are supported.')
            function_schema.bounded(result.get('structuredContent'))
            result={'content':content,'structured_content':result.get('structuredContent'),'is_error':result.get('isError',False),
                'catalog_digest':digest(catalog),'tool_name':name}
        else:raise ValueError('Unsupported MCP broker operation.')
        output={'schema_version':'modelanvil.mcp-tool-client.v1','status':'completed','protocol':protocol,'result':result,
            'wall_seconds':time.monotonic()-started,'production_qualified':False}
        raw=json.dumps(output,allow_nan=False)
        if len(raw.encode())>MAX_BYTES:raise ValueError('MCP broker output exceeds its bound.')
        print(raw)
    finally:session.close()


if __name__=='__main__':
    try:main()
    except Exception:
        # Transport URLs, authentication headers, server errors and raw bodies may contain credentials.
        print(json.dumps({'schema_version':'modelanvil.mcp-tool-client.v1','status':'failed','error':'MCP discovery or execution did not complete under the installed allowlist and limits.'}))
        sys.exit(1)
