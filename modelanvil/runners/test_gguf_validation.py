"""Incomplete GGUF bytes never become a registered model candidate."""
import importlib.util
import struct
import tempfile
from pathlib import Path
from unittest import skipUnless
from django.test import SimpleTestCase
from modelanvil.runners.gguf_validation import validate_gguf


class GGUFValidationTests(SimpleTestCase):
    def test_header_only_and_excessive_counts_refuse(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'model.gguf'
            for raw in [b'GGUF'+struct.pack('<I',3),b'GGUF'+struct.pack('<IQQ',3,1,1),b'GGUF'+struct.pack('<IQQ',3,2**63,1)]:
                path.write_bytes(raw)
                with self.assertRaises(ValueError):validate_gguf(path)

    @skipUnless(importlib.util.find_spec('gguf'),'Optional pinned GGUF reader not installed')
    def test_real_gguf_structure_tokenizer_and_truncated_tensor(self):
        import numpy as np
        from gguf import GGUFWriter
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'model.gguf'
            writer=GGUFWriter(path,'llama')
            writer.add_tokenizer_model('gpt2');writer.add_token_list(['a','b','c'])
            writer.add_chat_template('{% for message in messages %}{{ message.content }}{% endfor %}')
            writer.add_tensor('token_embd.weight',np.ones((3,4),dtype=np.float32))
            writer.write_header_to_file();writer.write_kv_data_to_file();writer.write_tensors_to_file();writer.close()
            evidence=validate_gguf(path)
            self.assertEqual(evidence['vocabulary_size'],3)
            self.assertEqual(evidence['tensor_count'],1)
            self.assertEqual(evidence['architecture'],'llama')
            self.assertIn('message.content',evidence['chat_template'])
            self.assertFalse(evidence['load_tested'])
            from gguf import GGUFReader
            reader=GGUFReader(path)
            end=max(t.data_offset+t.n_bytes for t in reader.tensors)
            path.write_bytes(path.read_bytes()[:end-4])
            with self.assertRaises(ValueError):validate_gguf(path)
