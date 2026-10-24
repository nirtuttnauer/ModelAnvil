"""Trusted container PID1: run supplied Python as an unprivileged, bounded child."""
import json
import os
import resource
import selectors
import signal
import subprocess
import sys
import time

OUTPUT_LIMIT=16384


def drop_privileges():
    resource.setrlimit(resource.RLIMIT_CPU,(5,5))
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024**2,1024**2))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    os.setgroups([]);os.setgid(65534);os.setuid(65534);os.umask(0o077)
    with open('/proc/self/status') as stream:fields=dict(line.split(':',1) for line in stream if ':' in line)
    if int(fields['CapEff'].strip(),16)!=0 or fields['NoNewPrivs'].strip()!='1':
        raise ValueError('The untrusted Python child retained privileges.')


def main():
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536:raise ValueError('Sandbox input exceeds its bound.')
    value=json.loads(raw)
    if (set(value)!={'code','wall_seconds'} or not isinstance(value['code'],str) or not 0<len(value['code'].encode())<=8192
            or type(value['wall_seconds']) is not int or not 1<=value['wall_seconds']<=5):
        raise ValueError('Use1–8192 bytes of Python source and1–5 seconds.')
    cancellation_requested=False
    def request_cancel(signum,frame):
        nonlocal cancellation_requested
        cancellation_requested=True
    signal.signal(signal.SIGTERM,request_cancel)
    started=time.monotonic();captured={'stdout':bytearray(),'stderr':bytearray()};status='completed';proc=None
    try:
        proc=subprocess.Popen([sys.executable,'-I','-S','-B','-'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            cwd='/work',env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/work','LANG':'C.UTF-8'},
            start_new_session=True,preexec_fn=drop_privileges)
        proc.stdin.write(value['code'].encode());proc.stdin.close()
        with selectors.DefaultSelector() as selector:
            for label,stream in (('stdout',proc.stdout),('stderr',proc.stderr)):
                os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ,label)
            while selector.get_map():
                if cancellation_requested:status='cancelled';break
                if time.monotonic()-started>=value['wall_seconds']:status='timeout';break
                for key,_ in selector.select(.02):
                    block=os.read(key.fd,4096)
                    if not block:selector.unregister(key.fileobj);continue
                    output=captured[key.data];remaining=OUTPUT_LIMIT-len(output);output.extend(block[:remaining])
                    if len(block)>remaining:status='output_limit';break
                if status!='completed':break
        if status=='completed':
            try:proc.wait(timeout=max(.01,value['wall_seconds']-(time.monotonic()-started)))
            except subprocess.TimeoutExpired:status='timeout'
        if status=='completed' and proc.returncode!=0:status='code_error'
    finally:
        if proc is not None:
            # Exiting this PID namespace's init also kills descendants that escaped the child's process group.
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            proc.wait(timeout=1)
            for stream in (proc.stdout,proc.stderr):stream.close()
    print(json.dumps({'schema_version':'modelanvil.python-sandbox.v1','status':status,
        'exit_code':proc.returncode,'stdout':bytes(captured['stdout']).decode('utf-8','replace'),
        'stderr':bytes(captured['stderr']).decode('utf-8','replace'),'stdout_bytes':len(captured['stdout']),
        'stderr_bytes':len(captured['stderr']),'wall_seconds':time.monotonic()-started,
        'cpu_seconds':None,'execution_uid':65534,'network':'none','persistent_files':False},allow_nan=False))


if __name__=='__main__':main()
