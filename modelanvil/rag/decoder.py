"""Operator bootstrap for the fixed public CPU RAG decoder; requests are offline."""
import hashlib
import json
import os
from pathlib import Path
from django.db import transaction
from modelanvil.identity.models import Tenant
from modelanvil.runners.models import ModelVersion
from modelanvil.runners import model_catalog
from modelanvil.runners.training.runtime import digest

PINS=json.loads(Path(__file__).with_name('decoder-pins.json').read_text())


def cache_decoder():
    from huggingface_hub import snapshot_download
    return snapshot_download(PINS['model'],revision=PINS['revision'],allow_patterns=list(PINS['files']),token=False,cache_dir=os.environ.get('MODELANVIL_RAG_DECODER_CACHE'))


def directory():
    root=os.environ.get('MODELANVIL_RAG_DECODER_DIR')
    if root:path=Path(root)
    else:
        from huggingface_hub import try_to_load_from_cache
        found=try_to_load_from_cache(PINS['model'],'config.json',revision=PINS['revision'],cache_dir=os.environ.get('MODELANVIL_RAG_DECODER_CACHE'))
        if not isinstance(found,str):raise ValueError('Cache the pinned public CPU RAG decoder first.')
        path=Path(found).parent
    if not path.is_absolute():raise ValueError('Use an absolute RAG decoder cache path.')
    for name,pin in PINS['files'].items():
        file=path/name
        if not file.is_file() or file.stat().st_size!=pin['byte_size']:raise ValueError('RAG decoder cache is incomplete.')
        sha=hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda:stream.read(1024**2),b''):sha.update(block)
        if sha.hexdigest()!=pin['sha256']:raise ValueError('RAG decoder checksum changed.')
    return path


@transaction.atomic
def register(project,name='SmolLM2 135M local RAG reference'):
    Tenant.objects.select_for_update().get(pk=project.tenant_id)
    root=directory();profile=digest(PINS)
    prior=ModelVersion.all_objects.filter(tenant_id=project.tenant_id,project=project,metadata__source__rag_decoder_profile=profile).first()
    if prior:return prior
    files={}
    for name_in_cache,pin in PINS['files'].items():
        if name_in_cache=='README.md':continue
        with (root/name_in_cache).open('rb') as stream:
            files[name_in_cache]=model_catalog._store(stream,tenant=project.tenant_id,project=project.pk,
                name=name_in_cache,expected=pin['sha256'],size=pin['byte_size'])
    version=model_catalog.publish_files(files,tenant=project.tenant_id,project=project.pk,name=name,
        source={'repo_id':PINS['model'],'revision':PINS['revision'],'license':PINS['license'],'license_evidence':PINS['license_evidence'],'rag_decoder_profile':profile},
        format='safetensors',license_expression=PINS['license'])
    return version
