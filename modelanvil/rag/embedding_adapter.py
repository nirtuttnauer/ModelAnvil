"""Verified local CPU Sentence Transformers adapter; inference never downloads files."""
from functools import lru_cache
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import threading

import numpy as np
from django.conf import settings

PINS = json.loads(Path(__file__).with_name('embedding-pins.json').read_text())
PACKAGES = {'sentence-transformers':'6.2.0','torch':'2.13.0','transformers':'5.14.0',
            'tokenizers':'0.22.2','safetensors':'0.8.0','numpy':'2.3.3',
            'huggingface-hub':'1.33.0','scikit-learn':'1.9.1','scipy':'1.18.1','joblib':'1.6.0',
            'threadpoolctl':'3.7.0','cloudpickle':'3.1.2','narwhals':'2.27.1'}
MEMORY_BYTES = 1024**3
BATCH_SIZE = 16
MAX_CHUNKS = 1000
_LOCK = threading.Lock()


def environment():
    try:
        found = {name: importlib.metadata.version(name) for name in PACKAGES}
    except importlib.metadata.PackageNotFoundError:
        raise ValueError('Install the pinned requirements.embeddings.txt CPU runtime.') from None
    comparable = {**found, 'torch':found['torch'].split('+')[0]}
    if comparable != PACKAGES:
        raise ValueError('Embedding runtime versions differ from requirements.embeddings.txt.')
    return {**found, 'architecture':platform.machine(), 'device':'cpu'}


def model_directory():
    explicit = getattr(settings,'MODELANVIL_EMBEDDING_MODEL_DIR',None) or os.environ.get('MODELANVIL_EMBEDDING_MODEL_DIR')
    if explicit:
        path = Path(explicit)
    else:
        from huggingface_hub import try_to_load_from_cache
        cached = try_to_load_from_cache(PINS['model'],'config.json',revision=PINS['revision'])
        if not isinstance(cached,str):
            raise ValueError('Cache the pinned public embedding model in the operator environment first.')
        path = Path(cached).parent
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('Configure an absolute local embedding model cache directory.')
    return path


def file_signature(path):
    try:
        return tuple((name,(path/name).stat().st_size,(path/name).stat().st_mtime_ns) for name in PINS['files'])
    except OSError:
        raise ValueError('Pinned embedding model files are missing.') from None


@lru_cache(maxsize=2)
def _verified(root, signature):
    verify_files(Path(root))


def verified_directory():
    path = model_directory(); _verified(str(path),file_signature(path)); return path


def verify_files(path):
    for name, pin in PINS['files'].items():
        file = path / name
        if not file.is_file() or file.stat().st_size != pin['byte_size']:
            raise ValueError('Pinned embedding model files are missing or changed.')
        value = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda:stream.read(1024**2),b''):value.update(block)
        if value.hexdigest() != pin['sha256']:
            raise ValueError('Pinned embedding model checksum verification failed.')


@lru_cache(maxsize=1)
def _model(root, signature):
    path = Path(root); verify_files(path); environment()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(path),device='cpu',local_files_only=True,
        trust_remote_code=False,token=False)
    if model.get_embedding_dimension() != PINS['dimension'] or model.max_seq_length != PINS['max_tokens']:
        raise ValueError('Embedding model dimension or context window differs from the pinned profile.')
    return model


def validate_vectors(vectors, count):
    matrix = np.asarray(vectors,dtype=np.float32)
    if matrix.shape != (count,PINS['dimension']) or not np.isfinite(matrix).all():
        raise ValueError('Embedding output has invalid dimensions or nonfinite values.')
    if count and not np.allclose(np.linalg.norm(matrix,axis=1),1,atol=1e-5,rtol=0):
        raise ValueError('Embedding output is not normalized to the declared space.')
    return matrix


def encode(texts):
    if (not isinstance(texts,list) or not 1 <= len(texts) <= BATCH_SIZE
            or any(not isinstance(t,str) or not t.strip() or len(t.encode()) > 32768 for t in texts)):
        raise ValueError('Encode 1–16 nonempty texts, each at most 32 KiB.')
    environment(); path = verified_directory()
    signature = file_signature(path)
    with _LOCK:
        model = _model(str(path),signature)
        # The Sentence Transformers encode path truncates by default. Refuse
        # overlong input before calling it, including actual model special tokens.
        ids = model.tokenizer(texts,add_special_tokens=True,truncation=False,padding=False)['input_ids']
        if any(len(row)>PINS['max_tokens'] for row in ids):
            raise ValueError('Text exceeds the pinned 256-token embedding context; rechunk without truncation.')
        try:
            result = model.encode(texts,batch_size=BATCH_SIZE,device='cpu',show_progress_bar=False,
                convert_to_numpy=True,normalize_embeddings=True,precision='float32')
        except Exception:
            raise ValueError('Local embedding inference failed; no vectors were published.') from None
    return validate_vectors(result,len(texts))


def vector_digest(vector):
    return hashlib.sha256(np.asarray(vector,dtype='<f4').tobytes()).hexdigest()
