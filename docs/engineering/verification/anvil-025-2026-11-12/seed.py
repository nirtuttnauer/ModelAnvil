#!/usr/bin/env python3
"""Drill data helper (not part of the repository).

seed <scripts-dir> <instance> <credentials>: run the controller's `example` import, sign in, greedy-chat the imported
model, run its 4-step full_sft launch to completion, greedy-chat the trained model. Prints a JSON summary, no secrets.
chat <scripts-dir> <instance> <credentials> <model>...: greedy-chat each model through the authenticated API.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

action,scripts,directory,credentials=sys.argv[1],sys.argv[2],Path(sys.argv[3]).resolve(),json.loads(Path(sys.argv[4]).read_text())
sys.path.insert(0,scripts)
from qualify_selfhost import Client


def chat(client,model):
    body={'model':model,'messages':[{'role':'user','content':'a tiny'}],'max_tokens':8,'temperature':0,'seed':42,'device':'cpu','prompt_format':'plain'}
    result=client.request('/api/v1/inference/chat/completions',body)
    return {'model':model,'content':result['choices'][0]['message']['content'],'finish_reason':result['choices'][0]['finish_reason'],'usage':result['usage']}


if action=='seed':
    controller=directory/'release/modelanvil.py'
    done=subprocess.run([sys.executable,str(controller),'example','--directory',str(directory),'--name','drill-example'],capture_output=True,timeout=300)
    assert done.returncode==0,'example import failed: '+done.stderr.decode()[-300:]
    imported=json.loads(done.stdout)
    client=Client(directory,credentials)
    base=chat(client,imported['model'])
    preview=client.request('/api/v1/training-runs/preflight/',imported['launch']);assert preview['status']=='approved',preview.get('status')
    run=client.request('/api/v1/training-runs/',{**imported['launch'],'preflight_token':preview['preflight_token']},expected=201,headers={'Idempotency-Key':str(uuid.uuid4())})
    started=time.monotonic()
    while run['status'] not in ('completed','failed','cancelled'):
        assert time.monotonic()-started<300,'training exceeded 300 s'
        time.sleep(.5);run=client.request('/api/v1/training-runs/'+run['run_id']+'/')
    assert run['status']=='completed',run['status']
    trained=chat(client,run['output_model_version_uuid'])
    print(json.dumps({'imported_model':imported['model'],'run_id':run['run_id'],'run_status':run['status'],'current_step':run['current_step'],
        'checkpoints':len(run['checkpoints']),'training_seconds':round(time.monotonic()-started,1),'trained_model':run['output_model_version_uuid'],
        'chat':[base,trained]},indent=2))
elif action=='chat':
    client=Client(directory,credentials)
    print(json.dumps({'chat':[chat(client,model) for model in sys.argv[5:]]},indent=2))
else:raise SystemExit('unknown action')
