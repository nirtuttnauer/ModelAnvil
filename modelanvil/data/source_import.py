"""Bounded source extraction into canonical envelopes; no network or file writes."""
import csv
import hashlib
import io
import json
import uuid
import zipfile
from xml.etree import ElementTree

VERSION = "modelanvil.source-extraction.v1"
MEDIA_TYPES = {"csv": "text/csv", "json": "application/json",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 10000


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys.")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Nonfinite JSON.")


def extract_source(raw, *, source_format, text_field="text", group_field=None):
    """CSV/JSON require explicit string text. DOCX reads main-body paragraphs.

    Without a group field the whole source is one protected split group;
    splitting paragraphs/rows of one document independently would leak context.
    """
    if source_format not in MEDIA_TYPES or not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("Unsupported or oversized source.")
    if not isinstance(text_field, str) or not 0 < len(text_field) <= 128:
        raise ValueError("A text field of at most 128 characters is required.")
    if group_field is not None and (not isinstance(group_field, str) or not 0 < len(group_field) <= 128):
        raise ValueError("Invalid group field.")
    if source_format == "docx" and (text_field != "text" or group_field is not None):
        raise ValueError("DOCX does not support field mappings.")
    digest = hashlib.sha256(raw).hexdigest()
    if source_format == "docx":
        records = _docx(raw)
    elif source_format == "json":
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object, parse_constant=_constant)
        if not isinstance(data, list):
            raise ValueError("JSON must be an array of records.")
        records = ((row, f"/{index}") for index, row in enumerate(data))
    else:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        headers = reader.fieldnames
        if not headers or any(not h for h in headers) or len(set(headers)) != len(headers):
            raise ValueError("CSV requires unique nonempty headers.")
        records = ((row, f"record/{index}") for index, row in enumerate(reader, 1))
    rows = []
    for record, location in records:
        if len(rows) >= MAX_ROWS or not isinstance(record, dict) or (source_format == "csv" and (None in record or any(v is None for v in record.values()))):
            raise ValueError("Source records are invalid or exceed the row limit.")
        text = record.get(text_field)
        group = record.get(group_field) if group_field else f"source-sha256:{digest}"
        if not isinstance(text, str) or not text.strip() or not isinstance(group, str) or not group.strip():
            raise ValueError("Text and source group must be nonempty strings.")
        rows.append({
            "schema_version": "1.0", "sample_id": str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(
                [VERSION, source_format, digest, text_field, group_field, location], ensure_ascii=False, separators=(",", ":")))),
            "source_group_id": group,
            "blocks": [{"block_id": "text", "type": "text", "text": text,
                        "location": {"source_path": location}}],
            "provenance": {"source_snapshot_ref": f"sha256:{digest}", "source_record_key": location,
                           "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                           "transformation_revision_ref": VERSION},
            "metadata": {"source_format": source_format},
        })
    if not rows:
        raise ValueError("Source contains no supported text records.")
    return rows


def _docx(raw):
    # Read only the main document; never extract ZIP paths or follow relationships.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 1000 or len({e.filename for e in entries}) != len(entries) or sum(e.file_size for e in entries) > MAX_BYTES:
            raise ValueError("DOCX archive exceeds extraction limits or has duplicate entries.")
        entry = archive.getinfo("word/document.xml")
        if entry.flag_bits & 1 or entry.file_size > MAX_BYTES:
            raise ValueError("Encrypted or oversized DOCX is unsupported.")
        with archive.open(entry) as stream:
            xml = stream.read(MAX_BYTES + 1)
        xml_text = xml.decode("utf-8-sig")
        if len(xml) > MAX_BYTES or "\x00" in xml_text or "<!DOCTYPE" in xml_text.upper() or "<!ENTITY" in xml_text.upper():
            raise ValueError("DOCX XML declarations are unsupported.")
        root = ElementTree.fromstring(xml_text)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        body = root.find(ns + "body")
        if root.tag != ns + "document" or body is None:
            raise ValueError("Missing DOCX main document body.")
        for index, paragraph in enumerate(body.iter(ns + "p"), 1):
            text = "".join((node.text or "") if node.tag == ns + "t" else "\t" if node.tag == ns + "tab" else "\n" if node.tag in (ns + "br", ns + "cr") else "" for node in paragraph.iter())
            if text.strip():
                yield {"text": text}, f"word/document.xml/paragraph/{index}"
