"""One exact CPU tool model; staging and execution never acquire remote code or weights."""
from contextlib import contextmanager
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from django.conf import settings
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.inference import verified_artifact,copy_verified
from modelanvil.runners.training.runtime import digest
from modelanvil.runners import tool_schema

RUNTIME_ID='modelanvil.qwen3-cpu-tools.v1'
SOURCE={'repo_id': 'Qwen/Qwen3-0.6B', 'revision': 'c1899de289a04d12100db370d81485cdf75e47ca', 'license': 'Apache-2.0'}
FILES={'config.json': {'sha256': '660db3b73d788119c04535e48cf9be5f55bc3100841a718637ae695b442f27dd', 'byte_size': 726}, 'generation_config.json': {'sha256': '2325da0f15bb848e018c5ae071b7943332e9f871d6b60e2ed22ca97d4cb993d2', 'byte_size': 239}, 'tokenizer.json': {'sha256': 'aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4', 'byte_size': 11422654}, 'tokenizer_config.json': {'sha256': 'd5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101', 'byte_size': 9732}, 'model.safetensors': {'sha256': 'f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b', 'byte_size': 1503300328}, 'LICENSE': {'sha256': '832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e', 'byte_size': 11343}}
PACKAGES={'torch':'2.13.0','transformers':'5.14.0','safetensors':'0.8.0','tokenizers':'0.22.2'}
LIMITS={'memory_bytes':16*1024**3,'context_tokens':1536,'output_tokens':128,'model_turns':3,'tool_calls':2,'attempts':3}
CONTRACT_DIGEST=digest({'runtime':RUNTIME_ID,'source':SOURCE,'files':FILES,'packages':PACKAGES,'limits':LIMITS,'precision':'fp32','thinking':False})
ROOT=Path(__file__).resolve().parents[2]
CONSUMER=ROOT/'scripts/tool_candidate_infer.py'


def _source_digest():
    names=['modelanvil/runners/tool_runtime.py','modelanvil/runners/tool_schema.py','modelanvil/runners/tool_sandbox.py',
        'modelanvil/runners/mcp_connections.py','scripts/tool_candidate_infer.py','scripts/mcp_tool_client.py',
        'scripts/bounded_math_mcp.py','scripts/tool_sandbox_guard.py','modelanvil/runners/tool_jobs.py',
        'modelanvil/runners/management/commands/reconcile_tool_completions.py','modelanvil/runners/management/commands/setup_tools.py',
        'modelanvil/api/views/tools.py','modelanvil/runners/tool_completion.py','modelanvil/api/views/model_workspace.py','modelanvil/core/privacy.py','modelanvil/jobs/models.py','modelanvil/device_admission.py']
    return hashlib.sha256(b''.join((ROOT/n).read_bytes() for n in names)).hexdigest()


_BUILD_DIGEST=_source_digest()


def build_digest():
    if _source_digest()!=_BUILD_DIGEST:raise ValueError('Tools code changed on disk; restart API and worker.')
    return _BUILD_DIGEST


def require_packages():
    for name,pin in PACKAGES.items():
        try:version=importlib.metadata.version(name).split('+')[0]
        except importlib.metadata.PackageNotFoundError:version=None
        if version!=pin:raise ValueError(f'Install {name}=={pin} for the CPU tools profile.')


def observed_device(selector='cpu'):
    from modelanvil.runners.training.cpu_hf_runtime import observed_device as observed
    return {**observed(selector),'packages':PACKAGES}


def capable_worker(worker):
    caps=worker.capabilities
    return (caps.get('tool_runtime')==CONTRACT_DIGEST and caps.get('gpu_device')=='cpu'
        and caps.get('tool_packages')==PACKAGES and type(caps.get('memory_bytes')) is int
        and caps['memory_bytes']>=LIMITS['memory_bytes'] and worker.slots in (0,1))


def candidate_bundle(version,tenant,project):
    tokenizer=version.tokenizer
    if (version.architecture_ref!=RUNTIME_ID or version.state in ('archived','rejected') or tokenizer is None
            or not all(check_resource_access(v,project,tenant) for v in (version,tokenizer))
            or not isinstance(version.metadata,dict) or not isinstance(tokenizer.compatibility,dict)
            or tokenizer.compatibility.get('hf_snapshot')!=SOURCE or tokenizer.vocabulary_size!=151669
            or tokenizer.configuration_digest!=digest(FILES) or not tokenizer.chat_template):
        raise ValueError('Select the accessible exact native Qwen3 CPU tool model and tokenizer.')
    ref=version.metadata.get('snapshot_manifest');artifact=verified_artifact(ref,tenant,project)
    if (artifact.byte_size>65536 or str(artifact.artifact_id)!=version.artifact_manifest_id
            or tokenizer.artifact_manifest_id!=version.artifact_manifest_id):raise ValueError('Tool model and tokenizer manifest differ.')
    raw=io.BytesIO();copy_verified(ref,tenant,project,raw);bundle=tool_schema.loads(raw.getvalue())
    files=bundle.get('files')
    if bundle.get('source')!=SOURCE or not isinstance(files,dict) or set(files)!=set(FILES):raise ValueError('Tool model requires its complete pinned snapshot.')
    for name,pin in FILES.items():
        item=verified_artifact(files[name],tenant,project)
        if item.sha256!=pin['sha256'] or item.byte_size!=pin['byte_size']:raise ValueError('Tool source/tokenizer pin differs.')
    return {'format':'tools','source':SOURCE,'files':files,'trained':False,'production_qualified':False}


@contextmanager
def staged_files(files,tenant,project):
    if not isinstance(files,dict) or set(files)!=set(FILES):raise ValueError('Tool snapshot filenames differ.')
    with tempfile.TemporaryDirectory(prefix='modelanvil-tool-model-') as temp:
        directory=Path(temp)
        for name,pin in FILES.items():
            artifact=verified_artifact(files[name],tenant,project)
            if artifact.sha256!=pin['sha256'] or artifact.byte_size!=pin['byte_size']:raise ValueError('Tool artifact differs from its exact source pin.')
            with (directory/name).open('wb') as output:copy_verified(files[name],tenant,project,output)
        yield directory


def native_input(messages,offered,max_tokens):
    tool_schema.tools(offered)
    if type(max_tokens) is not int or not 1<=max_tokens<=128 or not isinstance(messages,list) or not 1<=len(messages)<=12:
        raise ValueError('Use1–12 native messages and1–128 generated tokens.')
    for message in messages:
        if (not isinstance(message,dict) or message.get('role') not in ('system','user','assistant','tool')
                or not isinstance(message.get('content',''),str) or len(message.get('content','').encode())>16384):raise ValueError('Native tool message exceeds its bound.')
    raw=json.dumps({'messages':messages,'tools':offered,'max_tokens':max_tokens},sort_keys=True,allow_nan=False).encode()
    if len(raw)>65536:raise ValueError('Native tool request exceeds64KiB.')
    return raw


def validate_report(report,raw,max_tokens):
    usage=report.get('usage',{})
    if (report.get('schema_version')!='modelanvil.independent-tool-generation.v1' or report.get('source')!=SOURCE
            or report.get('file_sha256')!={n:p['sha256'] for n,p in FILES.items()}
            or report.get('input_sha256')!=hashlib.sha256(raw).hexdigest() or report.get('parameters')!=596049920
            or report.get('device')!='cpu' or report.get('precision')!='fp32' or report.get('thinking') is not False
            or report.get('consumer_imported_modelanvil_or_django') is not False or report.get('finish_reason') not in ('stop','length')
            or not isinstance(report.get('content'),str) or len(report['content'].encode())>16384
            or any(type(usage.get(k)) is not int for k in ('prompt_tokens','completion_tokens','total_tokens'))
            or not 1<=usage['prompt_tokens'] or not 1<=usage['completion_tokens']<=max_tokens
            or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens'] or usage['total_tokens']>1536):
        raise ValueError('Tool model returned incomplete native source/usage evidence.')
    for name,maximum in (('cpu_seconds',45),('wall_seconds',60)):
        if type(report.get(name)) not in (int,float) or not math.isfinite(report[name]) or not 0<=report[name]<=maximum:
            raise ValueError('Tool model timing evidence is missing or outside its bound.')
    return report


def generate(directory,messages,offered,max_tokens,*,cancelled=lambda:False,lease_descriptor=None):
    raw=native_input(messages,offered,max_tokens)
    with tempfile.TemporaryDirectory(prefix='modelanvil-tool-input-') as temp:
        root=Path(temp);path=root/'input.json';path.write_bytes(raw);path.chmod(0o600)
        env={'PATH':os.environ.get('PATH',''),'HOME':temp,'HF_HOME':str(root/'hub'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
            'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1'}
        with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
            child=subprocess.Popen([sys.executable,'-I',str(CONSUMER),str(directory),'--input',str(path)],
                stdout=output,stderr=errors,env=env,pass_fds=() if lease_descriptor is None else (lease_descriptor,))
            deadline=time.monotonic()+65
            try:
                while child.poll() is None:
                    if cancelled():raise ValueError('Tool generation cancelled or lost authorization.')
                    if time.monotonic()>deadline:raise ValueError('Tool generation exceeded its wall bound.')
                    time.sleep(.1)
                if child.returncode:raise ValueError('Native tool generation did not complete; inspect the bounded profile and context.')
                output.seek(0);data=output.read(65537)
                if not 0<len(data)<=65536:raise ValueError('Tool generation report exceeds its bound.')
                return validate_report(tool_schema.loads(data),raw,max_tokens)
            finally:
                if child.poll() is None:child.kill()
                child.wait()
