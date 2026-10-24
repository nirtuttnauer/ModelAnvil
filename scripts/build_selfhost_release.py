#!/usr/bin/env python3
"""Build a source-pinned offline package; never read instance secrets or publish it."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy.selfhost.modelanvil import Instance,FILES,sha,write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--version')
    args=parser.parse_args();output=args.output.resolve()
    if output.exists():raise ValueError('Use a new output directory; existing releases are immutable.')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():raise ValueError('Commit the release sources before building; source identity must describe the actual checkout.')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();version=args.version or 'cpu-'+revision[:12]
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,79}',version):raise ValueError('Use a lowercase release version of at most80characters.')
    controller=Instance(output);info=json.loads(controller.call(['info','--format','{{json .}}']))
    architecture={'aarch64':'arm64','x86_64':'amd64'}.get(info['Architecture'],info['Architecture'])
    if info['OSType']!='linux' or architecture!='arm64':raise ValueError('This release builder currently qualifies Linux arm64 only. Other architectures need their own tested lock and image qualification.')
    output.mkdir(parents=True,mode=0o700)
    images={}
    for target in ('api','web'):
        tag='modelanvil-selfhost-'+target+':'+version
        existing=subprocess.run([*controller.docker,'image','inspect',tag],env=controller.env,capture_output=True)
        if existing.returncode==0:raise ValueError('An image already uses this immutable release version. Choose a new version.')
        subprocess.run([*controller.docker,'build','--file',str(ROOT/'deploy/selfhost/Dockerfile'),'--target',target,
            '--build-arg','MODELANVIL_BUILD_REVISION='+revision,'--tag',tag,str(ROOT)],env=controller.env,check=True)
        images[target]=json.loads(controller.call(['image','inspect',tag]))[0]['Id']
    database='pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a'
    controller.call(['pull',database],timeout=180);images['db']=json.loads(controller.call(['image','inspect',database]))[0]['Id']
    for name in ('modelanvil.py','compose.yaml','README.md'):shutil.copy2(ROOT/'deploy/selfhost'/name,output/name)
    for name in ('LICENSE','requirements.selfhost.lock.txt'):shutil.copy2(ROOT/name,output/name)
    import os
    os.environ['DJANGO_SETTINGS_MODULE']='modelanvil.settings'
    import django;django.setup()
    from modelanvil.runners.training.general_transformer import GeneralTransformer
    from modelanvil.runners.training.engine import pack_safetensors
    from modelanvil.runners.training.general_runtime import RUNTIME_ID
    model=GeneralTransformer(vocab_size=260,n_layer=1,n_head=1,n_embd=4,context_window=32,seed=123)
    raw,weights=pack_safetensors(model.export_tensors())
    (output/'reference.json').write_text(json.dumps({'config.json':{'runtime':RUNTIME_ID,'vocab_size':260,'n_layer':1,'n_head':1,'n_embd':4,'context_window':32},
        'tokenizer_config.json':{'kind':'byte-v1','vocab_size':260,'pad_id':0,'bos_id':1,'eos_id':2,'unk_id':3},
        'weights_manifest.json':weights,'model.safetensors.b64':base64.b64encode(raw).decode()},sort_keys=True))
    controller.call(['save','--output',str(output/'images.tar'),*images.values()],timeout=600)
    frozen=controller.call(['run','--rm','--network','none','--entrypoint','python',images['api'],'-m','pip','freeze']).decode()
    normalize=lambda text:sorted(line.lower().replace('_','-') for line in text.splitlines() if line and not line.startswith('#'))
    if normalize(frozen)!=normalize((ROOT/'requirements.selfhost.lock.txt').read_text()):raise ValueError('Built Python packages differ from the complete runtime lock.')
    manifest={'schema_version':'modelanvil.selfhost-release.v1','version':version,'source_revision':revision,'architecture':architecture,'os':'linux',
        'images':images,'files':{name:{'sha256':sha(output/name),'bytes':(output/name).stat().st_size} for name in sorted(FILES)},
        'qualified_recipe':{'runtime':RUNTIME_ID,'recipe':'full_sft','profile':'Small numerical CPU transformer reference; no pretrained/task quality claim.'},
        'desktop_launchers':'Experimental unsigned macOS app and Linux desktop shortcut; Docker and Python3.9+ prerequisite.',
        'production_qualified':False}
    write_json(output/'release.json',manifest);print(json.dumps({'output':str(output),'version':version,'source_revision':revision,'images':images,'offline_bytes':(output/'images.tar').stat().st_size}))


if __name__=='__main__':main()
