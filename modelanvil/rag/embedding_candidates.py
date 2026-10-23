"""Serve only artifact-pinned, operator-published embedding candidates."""
from functools import lru_cache
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.annotation.feedback import artifact_live
from modelanvil.identity.models import check_resource_access
from modelanvil.rag.models import EmbeddingCandidate
from modelanvil.rag import embedding_adapter as adapter
from modelanvil.runners.training.runtime import digest


def checked(space,project_id=None):
    candidate=EmbeddingCandidate.all_objects.select_related('source','export').filter(space=space,tenant_id=space.tenant_id).first()
    if not candidate or not all(check_resource_access(row,project_id=project_id,tenant_id=space.tenant_id) for row in (candidate,candidate.source,candidate.export)):
        raise ValueError('Embedding candidate or its source/export is unavailable in this project.')
    for artifact,expected in [(candidate.source,candidate.source_digest),(candidate.export,candidate.export_digest)]:
        artifact_live(artifact)
        if (artifact.state!='committed' or artifact.storage_location_id!='local' or artifact.object_version is not None
                or artifact.sha256!=expected or artifact.project_id!=candidate.project_id
                or DeletionTombstone.all_objects.filter(tenant_id=space.tenant_id,resource_id__in=[str(artifact.artifact_id),artifact.sha256]).exists()):
            raise ValueError('Embedding candidate artifacts changed or were deleted.')
    if (space.model_name!=adapter.PINS['model'] or space.model_revision!=candidate.files['model.safetensors']['sha256']
            or space.dimension!=384 or not space.normalized or space.distance_metric!='cosine' or space.license_expression!='apache-2.0'
            or space.metadata.get('profile_digest')!=digest(candidate.files)
            or space.metadata.get('candidate_artifact')!=str(candidate.export.artifact_id)):
        raise ValueError('Embedding candidate space pins changed.')
    adapter.environment()
    return candidate


def pins(space,project_id=None):
    candidate=checked(space,project_id)
    return {'space':str(space.space_id),'model':space.model_name,'revision':space.model_revision,
        'license':space.license_expression,'dimension':space.dimension,'normalized':space.normalized,
        'profile_digest':space.metadata['profile_digest'],'candidate_artifact':str(candidate.export.artifact_id),
        'candidate_export_sha256':candidate.export_digest,'training_protocol_digest':digest(candidate.protocol)}


@lru_cache(maxsize=2)
def _load(tenant,key,expected,size,files_json,storage_root):
    from sentence_transformers import SentenceTransformer
    from modelanvil.rag.embedding_training import FILES
    backend=artifact_storage_backend();files=json.loads(files_json)
    if set(files)!=FILES or not 1<=size<=110*1024**2:raise ValueError('Candidate package layout or size is unsupported.')
    # A temporary directory belongs to this loader only. No archive path is trusted.
    with tempfile.TemporaryDirectory(prefix='modelanvil-embedding-load-') as folder:
        root=Path(folder);archive_path=root/'candidate.zip';observed=hashlib.sha256();total=0
        with backend.open(tenant,key) as stream,archive_path.open('wb') as output:
            for block in iter(lambda:stream.read(1024**2),b''):
                total+=len(block)
                if total>size:raise ValueError('Candidate archive exceeds its pinned size.')
                observed.update(block);output.write(block)
        if total!=size or observed.hexdigest()!=expected:raise ValueError('Candidate archive checksum changed.')
        with zipfile.ZipFile(archive_path) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)) or set(names)!=(FILES|{'LICENSE.txt','NOTICE.txt'}):raise ValueError('Candidate archive has unexpected files.')
            for name,pin in files.items():
                info=archive.getinfo(name)
                if info.file_size!=pin['byte_size'] or info.file_size>100*1024**2:raise ValueError('Candidate member size differs from its pin.')
                raw=archive.read(name)
                if hashlib.sha256(raw).hexdigest()!=pin['sha256']:raise ValueError('Candidate member checksum changed.')
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        model=SentenceTransformer(str(root),device='cpu',local_files_only=True,trust_remote_code=False,token=False)
        if model.get_embedding_dimension()!=384 or model.max_seq_length!=256:raise ValueError('Candidate model shape differs from its pinned profile.')
        model.eval()
        return model


def encode(texts,space,project_id=None):
    candidate=checked(space,project_id);backend=artifact_storage_backend()
    # Include physical object identity in the cache key; each request checks metadata and access.
    # Local store files are immutable; a changed mtime/size must force re-verification.
    path=backend._path(space.tenant_id,candidate.export.object_key,create_parent=False)
    try:signature=(path.stat().st_size,path.stat().st_mtime_ns)
    except OSError:raise ValueError('Candidate export bytes are unavailable.') from None
    with adapter._LOCK:
        try:
            model=_load(str(space.tenant_id),candidate.export.object_key,candidate.export_digest,candidate.export.byte_size,
                        json.dumps(candidate.files,sort_keys=True),str(backend.root)+repr(signature))
        except (OSError,zipfile.BadZipFile,KeyError):
            raise ValueError('Candidate export bytes could not be verified or loaded.') from None
        return adapter.encode_with_model(texts,model)
