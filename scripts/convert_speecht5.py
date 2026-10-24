"""Convert only the two exact published SpeechT5 checkpoints to pinned SafeTensors.

No network, custom pickle globals or remote code. Run in requirements.audio.txt.
"""
import argparse
import hashlib
from pathlib import Path

PINS={
    'tts':('d60d28067349ef66b50d8cd643ae56b6d6b8f27def929bc4ef6fcad907954190','aec2409d90f7f8e521021d7dea905cf11245cf9e4f2013634b478183aeb1349d',700*1024**2),
    'vocoder':('b171e9bcd8a2b50dc9780040478dfa26783a9ee4be012cf5776914f091d6887b','38907fe505de5bfc5ebd8c956d56721a2c30fdf8f5c7d4d9604f24759186246b',64*1024**2),
}


def convert(source,destination,kind):
    import torch
    from safetensors.torch import save_file
    expected,converted,maximum=PINS[kind]
    if source.is_symlink() or not source.is_file() or not 0<source.stat().st_size<=maximum:
        raise ValueError('Use the bounded original published checkpoint.')
    with source.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if sha!=expected:raise ValueError('Publisher checkpoint checksum differs; refusing pickle deserialization.')
    if destination.exists() or destination.is_symlink():raise ValueError('Destination already exists; refusing replacement.')
    state=torch.load(source,map_location='cpu',weights_only=True,mmap=True)
    counters={f'speech_decoder_postnet.layers.{i}.batch_norm.num_batches_tracked' for i in range(5)} if kind=='tts' else set()
    if (not isinstance(state,dict) or not state or not counters.issubset(state)
            or any(not isinstance(n,str) or not isinstance(t,torch.Tensor)
                or not (t.dtype==torch.float32 or n in counters and t.dtype==torch.int64 and t.ndim==0 and t.item()>=0)
                or not torch.isfinite(t).all().item() for n,t in state.items())):
        raise ValueError('Published checkpoint needs finite FP32 tensors and the exact five scalar integer BatchNorm counters.')
    try:
        save_file({n:t.contiguous().clone() for n,t in state.items()},str(destination))
        with destination.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if sha!=converted:raise ValueError('SafeTensor conversion differs from the pinned qualified bytes.')
    except Exception:
        destination.unlink(missing_ok=True);raise
    return sha


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=PINS);parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(convert(args.source,args.destination,args.kind))
