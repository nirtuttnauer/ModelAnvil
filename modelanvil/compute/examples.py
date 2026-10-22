"""Small, executable plugin example; replace with an operator-installed package."""
import hashlib
import uuid


def uppercase(descriptor, context, configuration):
    text = configuration["text"].upper()
    if not context.heartbeat():
        return None
    return {"schema_version": "1.0", "sample_id": str(uuid.uuid4()),
            "source_group_id": descriptor["job_id"],
            "blocks": [{"block_id": "output", "type": "text", "text": text}],
            "provenance": {"source_snapshot_ref": "plugin:uppercase:1.0", "source_record_key": descriptor["job_id"],
                           "content_sha256": hashlib.sha256(text.encode()).hexdigest()}}
