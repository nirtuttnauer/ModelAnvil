"""Operator bootstrap for the fixed public embedding model; inference is offline."""

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def cache_pinned_model() -> str:
    from huggingface_hub import snapshot_download

    import json
    from pathlib import Path
    pins = json.loads(Path(__file__).with_name('embedding-pins.json').read_text())
    return snapshot_download(MODEL_ID, revision=REVISION, allow_patterns=list(pins['files']), token=False)
