"""Actual bounded stdio/loopback MCP exchange and credential redaction."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from django.test import SimpleTestCase

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/mcp_tool_client.py'
PARAMETERS={'type':'object','properties':{n:{'type':'integer','minimum':-1000000,'maximum':1000000} for n in ('a','b')},
    'required':['a','b'],'additionalProperties':False}


class MCPTransportTests(SimpleTestCase):
    def invoke(self,value,success=True):
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([sys.executable,'-I',str(SCRIPT)],input=json.dumps(value),text=True,capture_output=True,
                timeout=23,env={'PATH':os.environ.get('PATH',''),'HOME':temp})
        self.assertEqual(result.returncode,0 if success else 1,result.stdout)
        return json.loads(result.stdout)

    def test_actual_stdio_discovery_call_and_permission_or_schema_changes(self):
        server={'kind':'builtin_math','allowed_tools':['add','multiply']}
        listing=self.invoke({'server':server,'operation':'list'})
        self.assertEqual(set(listing['result']['tools']),{'add','multiply'})
        self.assertEqual(listing['protocol']['protocol_version'],'2025-11-25')
        request={'server':server,'operation':'call','name':'add','arguments':{'a':17,'b':25},'catalog_digest':listing['result']['catalog_digest']}
        result=self.invoke(request);self.assertEqual(result['result']['structured_content'],{'value':42});self.assertFalse(result['result']['is_error'])
        for update in ({'name':'shell'},{'catalog_digest':'f'*64},{'arguments':{'a':True,'b':25}},
                       {'arguments':{'a':17,'b':25,'command':'arbitrary'}}):
            self.assertEqual(self.invoke({**request,**update},success=False)['status'],'failed')

    def test_actual_loopback_http_handshake_bearer_and_session_do_not_leak_credentials(self):
        credential='fixture-token-never-a-user-key';events=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                if self.headers.get('Authorization')!='Bearer '+credential:self.send_error(401);return
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];events.append(method)
                if self.headers.get('Mcp-Method')!=method:self.send_error(400);return
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method!='initialize' and self.headers.get('Mcp-Session-Id')!='scoped-fixture-session':self.send_error(400);return
                if method=='initialize':result={'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'Fixture '+credential}}
                elif method=='tools/list':result={'tools':[{'name':'add','description':'Add two integers.','inputSchema':PARAMETERS}]}
                elif method=='tools/call':
                    a=request['params']['arguments'];result={'content':[{'type':'text','text':f"{a['a']+a['b']} {credential}"}],
                        'structuredContent':{'value':a['a']+a['b']},'isError':False}
                else:self.send_error(400);return
                raw=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}).encode();self.send_response(200)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Mcp-Session-Id','scoped-fixture-session');self.end_headers();self.wfile.write(raw)
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            installed={'kind':'http','endpoint':f'http://127.0.0.1:{server.server_port}/mcp','allow_http_loopback':True,'credential':credential,'allowed_tools':['add']}
            listing=self.invoke({'server':installed,'operation':'list'})
            self.assertNotIn(credential,json.dumps(listing));self.assertIn('[redacted credential]',listing['protocol']['server_info']['name'])
            result=self.invoke({'server':installed,'operation':'call','name':'add','arguments':{'a':17,'b':25},'catalog_digest':listing['result']['catalog_digest']})
            self.assertEqual(result['result']['structured_content'],{'value':42});self.assertNotIn(credential,json.dumps(result))
            self.assertIn('tools/call',events)
            bad={**installed,'allow_http_loopback':False}
            self.assertEqual(self.invoke({'server':bad,'operation':'list'},success=False)['status'],'failed')
        finally:server.shutdown();server.server_close();thread.join(timeout=2)
