"""Pinned CPU SpeechT5 output-head recipe and bounded PCM audio preparation."""
import hashlib
import io
import math
from pathlib import Path

SOURCE = {'tts': {'repo_id': 'microsoft/speecht5_tts', 'revision': '30fcde30f19b87502b8435427b5f5068e401d5f6', 'license': 'MIT', 'upstream_weights_sha256': 'd60d28067349ef66b50d8cd643ae56b6d6b8f27def929bc4ef6fcad907954190'}, 'vocoder': {'repo_id': 'microsoft/speecht5_hifigan', 'revision': 'bb6f429406e86a9992357a972c0698b22043307d', 'license': 'MIT', 'upstream_weights_sha256': 'b171e9bcd8a2b50dc9780040478dfa26783a9ee4be012cf5776914f091d6887b'}, 'speaker': {'repo_id': 'Matthijs/cmu-arctic-xvectors', 'revision': '5c1297a9eb6c91714ea77c0d4ac5aca9b6a952e5', 'license': 'MIT', 'archive_sha256': '28ea1b685a49fedce92d1af7e68b22bf511a23432bc7a13d621a4deeee9fe9a1', 'member': 'spkrec-xvect/cmu_us_slt_arctic-wav-arctic_a0001.npy', 'speaker_sha256': '21719c0414a470561e6d037466fd239ab59c1f9ed4e1b97db557dad6d0223e73', 'norm': 0.9999998807907104}}
FILE_HASHES = {'config.json': '2caf62dde93699a90cfc35ff2a8de27b02b479a0c98881cbc55f9682cc43e258', 'preprocessor_config.json': '9461d890ff65badba5ad726f9059436bc69963883dc803fa6ed3cdb8f8af3687', 'tokenizer_config.json': 'd589430c619db2d95ff0fa757a187b55ef5ea44eff7fb08a6fbf0e78e32a6247', 'special_tokens_map.json': '2a098b61fe8ec4cfd7674832ca00b4268c07569743a4ad15c8164e8f60ebf981', 'added_tokens.json': '74be21ecff0a1fb1f304fe7c72ab21e4f0c046f8359fdf2852eb1b80967069ad', 'spm_char.model': '7fcc48f3e225f627b1641db410ceb0c8649bd2b0c982e150b03f8be3728ab560', 'model.safetensors': 'aec2409d90f7f8e521021d7dea905cf11245cf9e4f2013634b478183aeb1349d', 'vocoder/config.json': 'ac281bbb65c617a3fe7c5c082c8106f5a35b14d236b6a12f99cbbb12e576ab96', 'vocoder/model.safetensors': '38907fe505de5bfc5ebd8c956d56721a2c30fdf8f5c7d4d9604f24759186246b', 'speaker.npy': '21719c0414a470561e6d037466fd239ab59c1f9ed4e1b97db557dad6d0223e73'}
HEAD_NAMES = {f'speech_decoder_postnet.{layer}.{kind}' for layer in ('feat_out', 'prob_out') for kind in ('weight', 'bias')}
LEGACY_BUFFERS = {'speecht5.encoder.prenet.encode_positions.pe': (1, 600, 768),
    'speecht5.decoder.prenet.encode_positions.pe': (1, 1876, 768)}
SAMPLE_RATE, MAX_SAMPLES, MAX_MEL_FRAMES = 16000, 96000, 376


def decode_audio(raw, media_type):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    if type(raw) is not bytes or not 0 < len(raw) <= 4 * 1024**2 or media_type not in ('audio/wav', 'audio/flac'):
        raise ValueError('Use a PCM16 WAV or FLAC file of at most 4 MiB.')
    try:
        with sf.SoundFile(io.BytesIO(raw)) as stream:
            rate, channels, frames, format = stream.samplerate, stream.channels, stream.frames, stream.format
            if (format != ('WAV' if media_type == 'audio/wav' else 'FLAC') or stream.subtype != 'PCM_16'
                    or rate not in (8000,16000,22050,24000,32000,44100,48000) or channels not in (1,2)
                    or not rate / 4 <= frames <= 6 * rate):
                raise ValueError('Use 0.25–6 seconds of mono/stereo PCM16 WAV/FLAC at a supported 8–48 kHz rate.')
            data = stream.read(frames + 1, dtype='float32', always_2d=True)
            if data.shape != (frames, channels) or not np.isfinite(data).all():
                raise ValueError('Audio frames are incomplete or non-finite.')
    except (sf.SoundFileError, OSError, RuntimeError):
        raise ValueError('Audio decoding failed; use a complete supported PCM16 WAV or FLAC.') from None
    mono = data.mean(axis=1, dtype=np.float32)
    divisor = math.gcd(rate, SAMPLE_RATE)
    normalized = resample_poly(mono, SAMPLE_RATE // divisor, rate // divisor, window=('kaiser',5.0)) if rate != SAMPLE_RATE else mono
    clipped = int(np.count_nonzero(np.abs(normalized) > 1))
    normalized = np.clip(normalized, -1, 1).astype('<f4')
    if not 0 < len(normalized) <= MAX_SAMPLES or not np.isfinite(normalized).all():
        raise ValueError('Normalized audio exceeds the bounded sample profile.')
    return normalized, {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw), 'media_type': media_type,
        'sample_rate': rate, 'channels': channels, 'frames': frames, 'duration_seconds': frames / rate,
        'normalized_sample_rate': SAMPLE_RATE, 'normalized_frames': len(normalized),
        'normalized_sha256': hashlib.sha256(normalized.tobytes()).hexdigest(), 'clipped_samples': clipped,
        'normalized_rms': float(np.sqrt(np.mean(normalized.astype(np.float64)**2))),
        'transform': 'pcm16_mean_channels_scipy_resample_poly_kaiser5_clip_v1'}


def processor(directory):
    from transformers import SpeechT5Processor
    value = SpeechT5Processor.from_pretrained(str(directory), local_files_only=True)
    if len(value.tokenizer) != 81 or value.feature_extractor.sampling_rate != SAMPLE_RATE:
        raise ValueError('Use the exact pinned SpeechT5 text/audio processor.')
    return value


def speaker(directory):
    import numpy as np
    import torch
    value = np.load(Path(directory) / 'speaker.npy', allow_pickle=False)
    if value.shape != (512,) or value.dtype != np.float32 or not np.isfinite(value).all() or not .99 < np.linalg.norm(value) < 1.01:
        raise ValueError('Use the pinned finite published demo-conditioning vector; voice cloning is unsupported.')
    return torch.from_numpy(value.copy())[None]


def load_model(directory, *, training=False):
    import torch
    from safetensors.torch import load_file
    from transformers import SpeechT5ForTextToSpeech
    model, info = SpeechT5ForTextToSpeech.from_pretrained(str(directory), local_files_only=True,
        use_safetensors=True, dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
    if set(info['unexpected_keys']) != set(LEGACY_BUFFERS) or any(info[k] for k in ('missing_keys','mismatched_keys','error_msgs')):
        raise ValueError('SpeechT5 weights do not match the exact supported architecture.')
    saved = load_file(str(Path(directory) / 'model.safetensors'), device='cpu')
    # Transformers 5 made these publisher buffers nonpersistent; restore their exact original values.
    for name, shape in LEGACY_BUFFERS.items():
        value = saved[name]
        if tuple(value.shape) != shape or value.dtype != torch.float32 or not torch.isfinite(value).all().item():
            raise ValueError('Publisher positional buffer is missing, changed or non-finite.')
        parent, key = name.rsplit('.',1); module = model.get_submodule(parent)
        if key not in module._buffers: raise ValueError('SpeechT5 positional buffer layout changed.')
        module._buffers[key] = value.clone()
    del saved
    if any(p.is_meta or p.device.type != 'cpu' or p.dtype != torch.float32 or not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError('Audio execution requires complete finite CPU FP32 weights.')
    model.eval().requires_grad_(False)
    parameters = dict(model.named_parameters())
    head_path = Path(directory) / 'audio_head.safetensors'
    if head_path.exists():
        head = load_file(str(head_path),device='cpu')
        if set(head) != HEAD_NAMES or any(head[n].shape != parameters[n].shape or head[n].dtype != torch.float32 or not torch.isfinite(head[n]).all().item() for n in HEAD_NAMES):
            raise ValueError('Audio output-head tensors are incomplete or incompatible.')
        with torch.no_grad():
            for name in HEAD_NAMES: parameters[name].copy_(head[name])
    for name in HEAD_NAMES: parameters[name].requires_grad_(training)
    if training and sum(p.numel() for p in model.parameters() if p.requires_grad) != 124578:
        raise ValueError('Only the named SpeechT5 mel/stop output head may be trained.')
    return model


def load_vocoder(directory):
    import torch
    from transformers import SpeechT5HifiGan
    model, info = SpeechT5HifiGan.from_pretrained(str(Path(directory) / 'vocoder'), local_files_only=True,
        use_safetensors=True, dtype=torch.float32, output_loading_info=True)
    if any(info[k] for k in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')) or any(p.is_meta or p.device.type != 'cpu' or not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError('Use the complete pinned finite SpeechT5 HiFi-GAN vocoder.')
    return model.eval().requires_grad_(False)


def encode(processor, text, audio=None):
    import torch
    if not isinstance(text,str) or not text.strip() or len(text)>96 or any(t in text for t in processor.tokenizer.all_special_tokens):
        raise ValueError('Use 1–96 transcript characters without tokenizer control tokens.')
    inputs = processor(text=text, **({'audio_target':audio,'sampling_rate':SAMPLE_RATE} if audio is not None else {}), return_tensors='pt')
    if not 1 <= inputs['input_ids'].shape[-1] <= 128 or inputs['input_ids'].eq(processor.tokenizer.unk_token_id).any().item(): raise ValueError('Audio text exceeds 128 tokens or the supported character vocabulary; no truncation.')
    result = {name: inputs[name] for name in ('input_ids','attention_mask','labels') if name in inputs}
    frames = 0
    if audio is not None:
        labels = result['labels']; frames = labels.shape[1]
        if tuple(labels.shape[:1]) != (1,) or labels.shape[-1] != 80 or not 1 <= frames <= MAX_MEL_FRAMES or not torch.isfinite(labels).all().item():
            raise ValueError('Audio mel target exceeds the bounded processor profile.')
        # Preserve every real frame; an odd last frame gets one masked pad for reduction factor two.
        if frames % 2: result['labels'] = torch.cat([labels,torch.full((1,1,80),-100.,dtype=labels.dtype)],dim=1)
    return result, frames


def loss(model, encoded, conditioning):
    return model(**encoded,speaker_embeddings=conditioning,use_cache=False).loss


def wave_bytes(samples):
    import numpy as np
    import wave
    value = np.asarray(samples,dtype=np.float32)
    if value.ndim != 1 or not 0 < len(value) <= MAX_SAMPLES or not np.isfinite(value).all():
        raise ValueError('Missing, non-finite or oversized waveform is not a successful audio generation.')
    if float(np.sqrt(np.mean(value.astype(np.float64)**2))) < 1e-6 or np.mean(np.abs(value) > 1) > .01:
        raise ValueError('Silent or severely clipped output is not a successful speech generation.')
    output=io.BytesIO()
    with wave.open(output,'wb') as stream:
        stream.setparams((1,2,SAMPLE_RATE,0,'NONE','not compressed'))
        stream.writeframes((np.clip(value,-1,1)*32767).round().astype('<i2').tobytes())
    return output.getvalue()
