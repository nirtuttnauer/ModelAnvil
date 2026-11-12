"""Invalid GGUF bytes are refused before any process, with no ready claim."""
import importlib.util
import struct
import tempfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.test import SimpleTestCase
from modelanvil.runners import gguf_validation
from modelanvil.runners.gguf_validation import inspect_gguf, validate_gguf

FORBIDDEN=('production-ready','qualified','first')


def _spawned(*args, **kwargs):
    raise AssertionError('validation spawned a process')


class GGUFValidationBoundTests(SimpleTestCase):
    def _samples(self):
        return (
            b'',
            b'GGUF',
            b'GGUF'+struct.pack('<I',3),
            b'GGUF'+struct.pack('<IQQ',3,1,1),
            b'GGUF'+struct.pack('<IQQ',3,2**63,1),
            b'GGUF'+struct.pack('<IQQ',1,1,1),
            b'GGUF'+struct.pack('<IQQ',3,0,1),
            b'NOTA'+b'\x00'*20,
            b'\x00'*64,
        )

    def _claim_hits(self, value):
        hits=[]
        if isinstance(value, dict):
            for key, item in value.items():
                folded=str(key).lower().replace('_','-')
                if 'production-ready' in folded or 'qualified' in folded or folded=='ready' or folded.endswith('-ready'):
                    hits.append(str(key))
                hits.extend(self._claim_hits(item))
        elif isinstance(value, (list, tuple)):
            for item in value:hits.extend(self._claim_hits(item))
        elif isinstance(value, str):
            folded=value.lower()
            for word in FORBIDDEN:
                if word in folded:hits.append(value)
        return hits

    def test_invalid_bytes_are_rejected_without_spawning(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'model.gguf'
            with patch('modelanvil.runners.gguf_runtime.GGUFSession',side_effect=_spawned), \
                    patch('modelanvil.runners.inference.generate',side_effect=_spawned), \
                    patch.object(gguf_validation.subprocess,'run',side_effect=_spawned), \
                    patch.object(gguf_validation.subprocess,'Popen',side_effect=_spawned), \
                    patch.object(gguf_validation.subprocess,'call',side_effect=_spawned), \
                    patch.object(gguf_validation.subprocess,'check_call',side_effect=_spawned), \
                    patch.object(gguf_validation.subprocess,'check_output',side_effect=_spawned):
                for raw in self._samples():
                    path.write_bytes(raw)
                    with self.subTest(length=len(raw),prefix=raw[:4]):
                        with self.assertRaises(ValueError):inspect_gguf(path)
                        with self.assertRaises(ValueError):validate_gguf(path)

    @skipUnless(importlib.util.find_spec('gguf'),'Optional pinned GGUF reader not installed')
    def test_result_does_not_claim_the_model_is_ready(self):
        import numpy as np
        from gguf import GGUFWriter
        real=gguf_validation.subprocess.run
        def run(argv, *args, **kwargs):
            if not isinstance(argv,(list,tuple)) or len(argv)<2 or not str(argv[1]).endswith('gguf_validation.py'):
                raise AssertionError('unexpected process %r'%(argv,))
            return real(argv,*args,**kwargs)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'model.gguf'
            writer=GGUFWriter(path,'llama')
            writer.add_tokenizer_model('gpt2');writer.add_token_list(['a','b','c'])
            writer.add_chat_template('{% for message in messages %}{{ message.content }}{% endfor %}')
            writer.add_tensor('token_embd.weight',np.ones((3,4),dtype=np.float32))
            writer.write_header_to_file();writer.write_kv_data_to_file();writer.write_tensors_to_file();writer.close()
            with patch('modelanvil.runners.gguf_runtime.GGUFSession',side_effect=_spawned), \
                    patch('modelanvil.runners.inference.generate',side_effect=_spawned), \
                    patch.object(gguf_validation.subprocess,'run',side_effect=run):
                inspected=inspect_gguf(path)
                validated=validate_gguf(path)
        for payload in (inspected,validated):
            self.assertEqual(self._claim_hits(payload),[])
            self.assertIs(payload['load_tested'],False)
            self.assertEqual(payload['validation'],'structure-and-payload-bounds')
        self.assertEqual(inspected,validated)

    def test_docstrings_and_raised_messages_omit_claim_words(self):
        texts=[Path(gguf_validation.__file__).read_text(encoding='utf-8'),
            gguf_validation.__doc__ or '',inspect_gguf.__doc__ or '',validate_gguf.__doc__ or '']
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'model.gguf'
            for raw in self._samples():
                path.write_bytes(raw)
                for fn in (inspect_gguf,validate_gguf):
                    with self.assertRaises(ValueError) as caught:fn(path)
                    texts.append(str(caught.exception))
        folded='\n'.join(texts).lower()
        for word in FORBIDDEN:self.assertNotIn(word,folded)
