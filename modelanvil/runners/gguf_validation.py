"""Bounded-process structural GGUF validation; no model execution or ready claim."""
import importlib.metadata
import json
from pathlib import Path
import struct
import subprocess
import sys


def inspect_gguf(path):
    path=Path(path)
    with path.open('rb') as stream:header=stream.read(24)
    if len(header)!=24 or header[:4]!=b'GGUF':
        raise ValueError('GGUF header is incomplete or invalid.')
    version=int.from_bytes(header[4:8],'little')
    endian='<' if version in (2,3) else '>'
    version,tensors,fields=struct.unpack(endian+'IQQ',header[4:])
    if version not in (2,3) or not 1<=tensors<=100000 or not 1<=fields<=100000:
        raise ValueError('GGUF version, tensor count or metadata count is unsupported.')
    from gguf import GGUFReader
    reader=GGUFReader(path)
    architecture=reader.get_field('general.architecture')
    tokens=reader.get_field('tokenizer.ggml.tokens')
    template=reader.get_field('tokenizer.chat_template')
    if architecture is None or tokens is None or not 1<=len(tokens.data)<=256000:
        raise ValueError('GGUF needs architecture and bounded tokenizer metadata.')
    ranges=sorted((t.data_offset,t.data_offset+t.n_bytes) for t in reader.tensors)
    if len(ranges)!=tensors or any(start<reader.data_offset or end<=start or end>path.stat().st_size for start,end in ranges):
        raise ValueError('GGUF tensor payload is missing, empty or truncated.')
    if any(left[1]>right[0] for left,right in zip(ranges,ranges[1:])):
        raise ValueError('GGUF tensor payloads overlap.')
    chat=template.contents() if template is not None else ''
    if not isinstance(chat,str) or len(chat)>1024*1024:
        raise ValueError('GGUF chat template exceeds the supported bound.')
    return {'architecture':architecture.contents(),'vocabulary_size':len(tokens.data),'chat_template':chat,
        'tensor_count':len(ranges),'reader_version':importlib.metadata.version('gguf'),
        'validation':'structure-and-payload-bounds','load_tested':False}


def validate_gguf(path):
    """Keep malformed metadata parsing outside the API process with a fixed deadline."""
    try:
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),str(path)],
            capture_output=True,text=True,timeout=20,check=False)
        if result.returncode or len(result.stdout)>2*1024*1024:
            raise ValueError('GGUF is incomplete, corrupt or lacks the optional pinned gguf reader; install requirements.inference.txt.')
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
        raise ValueError('GGUF validation exceeded its bound or returned invalid evidence.') from exc


if __name__=='__main__':
    try:print(json.dumps(inspect_gguf(sys.argv[1])))
    except Exception:sys.exit(1)
