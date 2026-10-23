"""Offline, pinned WordPiece windows retaining exact original character spans."""
from bisect import bisect_left
from functools import lru_cache
import hashlib
import importlib.metadata
from pathlib import Path
import re

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

TOKENIZERS_VERSION = '0.22.2'
TOKENIZER_SHA256 = 'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037'
RECIPE = 'minilm-wordpiece-spans-v1'
TOKENIZER_PATH = Path(__file__).with_name('assets') / 'minilm-tokenizer.json'
PINS = {'model': MODEL_ID, 'revision': REVISION, 'sha256': TOKENIZER_SHA256,
        'library': 'tokenizers', 'version': TOKENIZERS_VERSION, 'add_special_tokens': False,
        'truncation': False, 'padding': False}
PARAGRAPH = re.compile(r'\n[\t \r]*\n+')
SENTENCE = re.compile(r'''[.!?。！？]+["'”’\)\]]*(?:\s+|$)''')


@lru_cache(maxsize=1)
def tokenizer():
    try:
        installed = importlib.metadata.version('tokenizers')
    except importlib.metadata.PackageNotFoundError:
        installed = None
    if installed != TOKENIZERS_VERSION:
        raise ValueError('Install the pinned requirements.txt tokenizers dependency before indexing.')
    raw = TOKENIZER_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != TOKENIZER_SHA256:
        raise ValueError('The bundled RAG tokenizer checksum is invalid.')
    from tokenizers import Tokenizer
    result = Tokenizer.from_str(raw.decode())
    result.no_truncation(); result.no_padding()
    return result


def encode(text):
    return tokenizer().encode(text, add_special_tokens=False)


def token_chunks(text, size, overlap):
    """Yield windows with <=size content tokens and <=overlap actual overlap tokens.

    Full-source offsets supply Unicode character boundaries; original whitespace,
    combining marks and normalized-away bytes remain in the saved text. A window
    beginning mid-word can re-tokenize differently, so its actual token count and
    overlap are independently checked instead of trusting sliced source IDs.
    """
    if type(size) is not int or not 16 <= size <= 4096 or type(overlap) is not int or not 0 <= overlap <= size // 2:
        raise ValueError('Use 16–4096 tokens per chunk and an overlap up to half its size.')
    encoded = encode(text)
    offsets = encoded.offsets
    if not offsets:
        raise ValueError('Document has no tokenizer-visible text.')
    starts = [pair[0] for pair in offsets]
    paragraphs = sorted({bisect_left(starts, match.end()) for match in PARAGRAPH.finditer(text)})
    sentences = sorted({bisect_left(starts, match.end()) for match in SENTENCE.finditer(text)})
    start = 0; previous_end = 0
    while start < len(offsets):
        end = min(start + size, len(offsets))
        if end < len(offsets):
            lower = start + max(overlap + 1, size // 2)
            for boundaries in (paragraphs, sentences):
                candidate = bisect_left(boundaries, end + 1) - 1
                if candidate >= 0 and boundaries[candidate] >= lower:
                    end = boundaries[candidate]; break
        char_start = starts[start] if start else 0
        char_end = len(text) if end == len(offsets) else starts[end]
        # WordPiece continuation tokens can have different segmentation at a new
        # chunk start. Bound the actual independently encoded chunk, without cuts.
        count = len(encode(text[char_start:char_end]).ids)
        while count > size and end > start + 1:
            end -= 1
            char_end = starts[end]
            count = len(encode(text[char_start:char_end]).ids)
        if count > size or char_end <= char_start:
            raise ValueError('Unable to produce a bounded token window for this source.')
        overlap_count = len(encode(text[char_start:previous_end]).ids) if char_start < previous_end else 0
        yield {'text': text[char_start:char_end], 'span_start': char_start, 'span_end': char_end,
               'token_count': count, 'metadata': {'source_token_start': start, 'source_token_end': end,
               'overlap_tokens': overlap_count, 'tokenizer': PINS, 'chunk_recipe': RECIPE}}
        if end == len(offsets):
            break
        next_start = max(start + 1, end - overlap)
        while next_start < end and len(encode(text[starts[next_start]:char_end]).ids) > overlap:
            next_start += 1
        previous_end = char_end
        start = next_start
