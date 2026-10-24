"""Audio decode/normalization boundaries; tones do not qualify speech quality."""
import hashlib
import importlib.util
import io
from unittest import skipUnless
from django.test import SimpleTestCase
from .audio_math import decode_audio, wave_bytes


@skipUnless(importlib.util.find_spec('soundfile') and importlib.util.find_spec('scipy'), 'Optional audio dependencies are not installed')
class AudioBoundsTests(SimpleTestCase):
    def audio(self, *, rate=48000, channels=2, seconds=.5, subtype='PCM_16', format='WAV'):
        import numpy as np
        import soundfile as sf
        tone=.1*np.sin(2*np.pi*440*np.arange(int(rate*seconds))/rate)
        data=np.stack([tone,.5*tone],axis=1) if channels==2 else tone
        output=io.BytesIO();sf.write(output,data,rate,format=format,subtype=subtype)
        return output.getvalue()

    def test_actual_pcm_rate_channels_duration_and_identity_are_retained(self):
        raw=self.audio();data,pin=decode_audio(raw,'audio/wav')
        self.assertEqual((pin['sample_rate'],pin['channels'],pin['frames']),(48000,2,24000))
        self.assertEqual(pin['duration_seconds'],.5)
        self.assertEqual(pin['normalized_frames'],8000)
        self.assertEqual(pin['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(pin['normalized_sha256'],hashlib.sha256(data.tobytes()).hexdigest())
        self.assertGreater(pin['normalized_rms'],.05)
        decoded,export=decode_audio(wave_bytes(data),'audio/wav')
        self.assertEqual((export['sample_rate'],export['channels'],len(decoded)),(16000,1,8000))

    def test_unsupported_truncated_duration_size_and_mime_refused(self):
        for raw,media in [(b'broken','audio/wav'),(self.audio()[:50],'audio/wav'),
                (self.audio(subtype='FLOAT'),'audio/wav'),(self.audio(seconds=.1),'audio/wav'),
                (self.audio(seconds=6.1),'audio/wav'),(self.audio(),'audio/flac'),(b'x'*(4*1024**2+1),'audio/wav')]:
            with self.subTest(media=media,size=len(raw)),self.assertRaises(ValueError):decode_audio(raw,media)

    def test_flac_decodes_actual_pcm_and_failed_waveforms_do_not_export(self):
        import numpy as np
        value,pin=decode_audio(self.audio(channels=1,format='FLAC'),'audio/flac')
        self.assertEqual(pin['normalized_frames'],8000)
        for samples in ([],np.zeros(16000),[np.nan]*16000,np.ones(96001),np.ones(16000)*2):
            with self.assertRaises(ValueError):wave_bytes(samples)
