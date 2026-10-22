"""Pinned dense embedding model for the Postgres evidence job.

shortcut: CI caches this revision only; retrieval still takes a caller-supplied
vector, until the Sentence Transformers adapter is wired in.
"""

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def cache_pinned_model() -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(MODEL_ID, revision=REVISION)
