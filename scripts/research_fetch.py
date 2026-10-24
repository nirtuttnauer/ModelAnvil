"""Independent bounded public-page fetcher; never executes page code or follows redirects."""
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import resource
import socket
import ssl
import sys
import time
from datetime import datetime,timezone
from urllib.parse import urlsplit

class Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.hidden=0;self.parts=[];self.title=[];self.in_title=False
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','template','svg'):self.hidden+=1
        if tag=='title':self.in_title=True
        if tag in ('p','br','li','h1','h2','h3','pre','div'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','template','svg'):self.hidden=max(0,self.hidden-1)
        if tag=='title':self.in_title=False
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
        if self.in_title:self.title.append(data)


def fetch(url,*,allow_local=False,timeout=8):
    parsed=urlsplit(url);host=parsed.hostname
    if (parsed.scheme not in ('https','http') or not host or parsed.username or parsed.password or parsed.fragment
        or len(url)>2048 or any(ord(c)<33 or ord(c)>126 for c in url)):
        raise ValueError('Use an ASCII HTTPS page URL without credentials or fragments.')
    local=allow_local and host in ('localhost','127.0.0.1','::1')
    if parsed.scheme!='https' and not local:raise ValueError('HTTPS is required.')
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses) and not local:
        raise ValueError('Only public destination addresses are supported.')
    # Pin the checked address while keeping the original TLS hostname and HTTP Host.
    started=time.monotonic();sock=None
    for family,kind,protocol,_,address in addresses:
        try:
            sock=socket.socket(family,kind,protocol);sock.settimeout(max(.1,timeout-(time.monotonic()-started)));sock.connect(address);break
        except OSError:
            if sock:sock.close();sock=None
    if sock is None:raise ValueError('The reviewed destination could not be reached.')
    connection=http.client.HTTPConnection(host,port,timeout=timeout)
    try:
        if parsed.scheme=='https':sock=ssl.create_default_context().wrap_socket(sock,server_hostname=host)
        connection.sock=sock
        connection.request('GET',(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),headers={
            'Accept':'text/html,text/plain','Accept-Encoding':'identity','User-Agent':'ModelAnvil-ReviewedResearch/1.0'})
        response=connection.getresponse()
        if response.status!=200:raise ValueError('Page fetch requires an exact200 response; redirects are refused.')
        if response.getheader('Content-Encoding','identity').lower()!='identity':raise ValueError('Compressed responses are unavailable in this bounded path.')
        kind=response.getheader('Content-Type','').split(';')[0].strip().lower()
        if kind not in ('text/html','text/plain'):raise ValueError('Only HTML or plain-text pages are supported.')
        data=bytearray()
        while True:
            sock.settimeout(max(.1,timeout-(time.monotonic()-started)))
            block=response.read(min(65536,1024**2+1-len(data)))
            if not block:break
            data.extend(block)
            if len(data)>1024**2 or time.monotonic()-started>timeout:raise ValueError('Page exceeded its byte or time budget.')
        text=bytes(data).decode('utf-8-sig')
        title=host
        if kind=='text/html':
            parser=Text();parser.feed(text);title=' '.join(''.join(parser.title).split())[:180] or host
            text='\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
        if not text.strip() or len(text.encode())>500000:raise ValueError('Page has no supported text or exceeds extraction limits.')
        return {'url':url,'title':title,'text':text,'retrieved_at':datetime.now(timezone.utc).isoformat(),
            'http_status':200,'content_type':kind,'source_sha256':hashlib.sha256(data).hexdigest(),
            'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'bytes':len(data),'elapsed_seconds':time.monotonic()-started}
    finally:connection.close()


def main():
    resource.setrlimit(resource.RLIMIT_CPU,(5,5));resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024**2,2*1024**2))
    if sys.platform!='darwin':resource.setrlimit(resource.RLIMIT_AS,(256*1024**2,256*1024**2))
    payload=json.loads(sys.stdin.buffer.read(16385))
    if set(payload)!={'urls','allow_local'} or not isinstance(payload['urls'],list) or not 1<=len(payload['urls'])<=2:raise ValueError()
    pages=[fetch(url,allow_local=payload['allow_local'] is True) for url in payload['urls']]
    sys.stdout.write(json.dumps({'pages':pages},allow_nan=False))

if __name__=='__main__':
    try:main()
    except Exception:sys.exit(3)
