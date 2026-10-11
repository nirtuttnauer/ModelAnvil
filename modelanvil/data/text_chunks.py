"""Deterministic character-bounded plain text chunks with exact source spans."""
import copy
import hashlib
import json
import uuid

VERSION = "modelanvil.character-chunks.v1"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


def chunk_envelopes(rows, limit, *, max_rows=10000):
    if type(limit) is not int or not 32 <= limit <= 4096:
        raise ValueError("Chunk character limit must be an integer from 32 to 4096.")
    emitted = 0
    estimated_bytes = 0
    for row in rows:
        blocks = row["blocks"]
        if len(blocks) != 1 or blocks[0]["type"] != "text" or "role" in blocks[0]:
            raise ValueError("Chunking requires one plain text block without conversation roles.")
        block = blocks[0]
        text = block["text"]
        location = block.get("location", {})
        base = location.get("char_start", 0)
        if "char_end" in location and location["char_end"] - base != len(text):
            raise ValueError("Source character span does not match its text length.")
        # Balance chunks to avoid a one-character tail, without dropping or overlapping text.
        count = max(1, (len(text) + limit - 1) // limit)
        if emitted + count > max_rows:
            raise ValueError("Chunked output exceeds the sample limit.")
        text_bytes = len(json.dumps(text, ensure_ascii=False).encode("utf-8"))
        overhead = len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8")) - text_bytes
        # Refuse metadata amplification before copying a large parent into many children.
        estimated_bytes += text_bytes + count * (2 * overhead + 2048)
        if estimated_bytes > MAX_MANIFEST_BYTES:
            raise ValueError("Chunked output exceeds its byte limit.")
        for index in range(count):
            start, end = index * len(text) // count, (index + 1) * len(text) // count
            child = copy.deepcopy(row)
            child["sample_id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
                [VERSION, row["sample_id"], limit, start, end], separators=(",", ":"))))
            child["blocks"][0]["text"] = text[start:end]
            child["blocks"][0]["location"] = {**location, "char_start": base + start, "char_end": base + end}
            child["provenance"].update({"parent_sample_refs": [*row["provenance"].get("parent_sample_refs", []), row["sample_id"]],
                "content_sha256": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest(),
                "transformation_revision_ref": VERSION})
            child.setdefault("metadata", {})["chunk"] = {"parent_sample_id": row["sample_id"],
                "parent_content_sha256": row["provenance"]["content_sha256"],
                "source_transformation_revision": row["provenance"].get("transformation_revision_ref"),
                "index": index, "count": count, "character_limit": limit}
            emitted += 1
            yield child
