"""Content-pinned, bounded HTTP subsets; never execute dataset loading scripts."""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import re
import tarfile
import zipfile
import zlib
from pathlib import Path
from urllib.parse import urlsplit

CONNECTOR = "qualified_http_subset_v1"
MAX_TRANSFER_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_SAMPLE_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 64 * 1024 * 1024
CATALOG_ROOT = Path(__file__).resolve().parents[3] / "catalog" / "qualified-datasets"
ALLOWED_HOSTS = {
    "huggingface.co",
    "dl.fbaipublicfiles.com",
    "datashare.ed.ac.uk",
    "openslr.trmal.net",
    "archive.ics.uci.edu",
}


class SnapshotError(ValueError):
    """Sanitized public-source integrity, format, or resource refusal."""


def canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise SnapshotError("Qualified upstream URL is not an allowed HTTPS source.")
    return url


def cached_transport(transport):
    """Cache range responses only within one preview or tenant acquisition."""
    cache = {}
    cache_bytes = 0

    def fetch(url, headers):
        nonlocal cache_bytes
        key = (url, tuple(sorted(headers.items())))
        if key not in cache:
            result = transport(url, headers)
            if cache_bytes + len(result[1]) <= MAX_CACHE_BYTES:
                cache[key] = result
                cache_bytes += len(result[1])
            return result
        return cache[key]

    return fetch


def fetch_range(url, size, start, length, transport):
    _url(url)
    if (
        not all(type(v) is int for v in (size, start, length))
        or start < 0
        or length < 1
        or length > MAX_TRANSFER_BYTES
        or start + length > size
    ):
        raise SnapshotError("Qualified byte range exceeds its resource bounds.")
    status, body, headers = transport(
        url,
        {
            "User-Agent": "modelanvil-dataset-bank",
            "Range": f"bytes={start}-{start + length - 1}",
            "Accept-Encoding": "identity",
        },
    )
    response_range = next(
        (value for key, value in headers.items() if key.lower() == "content-range"), ""
    )
    if status == 200 and size <= MAX_TRANSFER_BYTES and len(body) == size:
        return body[start : start + length]
    if (
        status != 206
        or response_range != f"bytes {start}-{start + length - 1}/{size}"
        or len(body) != length
    ):
        raise SnapshotError("Upstream did not return the exact qualified byte range.")
    return body


class RangeFile(io.RawIOBase):
    """Seekable remote file; reads are captured for qualification or digest-pinned."""

    def __init__(self, container, transport, *, capture=False):
        self.container = container
        self.transport = transport
        self.capture = capture
        self.position = 0
        self.segments = {}
        self.bytes_received = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        target = (
            offset
            if whence == 0
            else self.position + offset
            if whence == 1
            else self.container["size"] + offset
            if whence == 2
            else -1
        )
        if target < 0 or target > self.container["size"]:
            raise SnapshotError("Upstream reader requested an invalid offset.")
        self.position = target
        return target

    def read(self, length=-1):
        length = (
            self.container["size"] - self.position
            if length is None or length < 0
            else min(length, self.container["size"] - self.position)
        )
        if not length:
            return b""
        start = self.position
        if self.capture:
            whole_file = self.container.get("transfer_mode") == "whole_file"
            fetch_start, fetch_length = (
                (0, self.container["size"]) if whole_file else (start, length)
            )
            block = fetch_range(
                self.container["url"],
                self.container["size"],
                fetch_start,
                fetch_length,
                self.transport,
            )
            payload = block[start : start + length] if whole_file else block
            key = (fetch_start, fetch_length)
            if key not in self.segments:
                self.bytes_received += len(block)
                if self.bytes_received > MAX_CACHE_BYTES:
                    raise SnapshotError("Subset qualification exceeds the transfer bound.")
                self.segments[key] = {
                    "start": fetch_start,
                    "length": fetch_length,
                    "sha256": digest(block),
                }
        else:
            payload = bytearray()
            end = start + length
            cursor = start
            for segment in sorted(self.container["segments"], key=lambda item: item["start"]):
                left, right = segment["start"], segment["start"] + segment["length"]
                if left <= cursor < right:
                    block = fetch_range(
                        self.container["url"],
                        self.container["size"],
                        left,
                        segment["length"],
                        self.transport,
                    )
                    if digest(block) != segment["sha256"]:
                        raise SnapshotError("Upstream range failed its qualified SHA-256 digest.")
                    stop = min(end, right)
                    payload.extend(block[cursor - left : stop - left])
                    cursor = stop
                    if cursor == end:
                        break
            if cursor != end:
                raise SnapshotError("Reader requested bytes outside the qualified subset.")
            payload = bytes(payload)
        self.position += len(payload)
        return payload

    def readinto(self, buffer):
        payload = self.read(len(buffer))
        buffer[: len(payload)] = payload
        return len(payload)


def load_manifest(source):
    if not re.fullmatch(r"[a-z0-9-]+", source.id):
        raise SnapshotError("Invalid qualified source identity.")
    try:
        raw = (CATALOG_ROOT / f"{source.id}.json").read_bytes()
        if len(raw) > MAX_TRANSFER_BYTES:
            raise SnapshotError("Qualification manifest exceeds its bound.")
        manifest = json.loads(raw)
        if (
            digest(canonical_json(manifest)) != source.acquisition.pinned_revision
            or manifest["source_id"] != source.id
        ):
            raise SnapshotError("Qualification manifest does not match the pinned revision.")
        validate_manifest(manifest)
        return manifest
    except (OSError, KeyError, TypeError, ValueError):
        raise SnapshotError(
            "The pinned subset qualification manifest is invalid or unavailable."
        ) from None


def validate_manifest(manifest):
    records = manifest["records"]
    if not records or len(records) > 100 or len({r["path"] for r in records}) != len(records):
        raise SnapshotError("Qualified inventory is empty, duplicated, or oversized.")
    if not manifest["licenses"] or len(manifest["containers"]) > 16:
        raise SnapshotError("Qualification has no notices or exceeds its container bound.")
    for container in manifest["containers"].values():
        _url(container["url"])
        if type(container["size"]) is not int or not 1 <= container["size"] <= 32 * 1024**3:
            raise SnapshotError("Qualified container exceeds its size bound.")
        if (
            not container["segments"]
            or len(container["segments"]) > 256
            or sum(s["length"] for s in container["segments"]) > MAX_CACHE_BYTES
        ):
            raise SnapshotError("Qualified ranges exceed their transfer bound.")
        for segment in container["segments"]:
            if (
                not re.fullmatch(r"[a-f0-9]{64}", segment["sha256"])
                or not 0 <= segment["start"] < container["size"]
                or not 1 <= segment["length"] <= MAX_TRANSFER_BYTES
                or segment["start"] + segment["length"] > container["size"]
            ):
                raise SnapshotError("Qualified range is malformed.")
    for record in records + manifest["licenses"]:
        if (
            not isinstance(record["path"], str)
            or not record["path"]
            or type(record["size"]) is not int
            or not 1 <= record["size"] <= MAX_SAMPLE_BYTES
            or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])
        ):
            raise SnapshotError("Qualified record is malformed or exceeds its bound.")


def _zip_member(archive, name):
    info = archive.getinfo(name)
    if info.is_dir() or info.file_size > MAX_EXPANDED_BYTES:
        raise SnapshotError("Archive member exceeds its expansion bound.")
    return archive.read(info)


def json_prefix_rows(raw, key):
    text = codecs.getincrementaldecoder("utf-8")().decode(raw, final=False)
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*\[', text)
    if match is None:
        raise SnapshotError("Qualified JSON array is absent from the prefix.")
    position = match.end()
    decoder = json.JSONDecoder()
    rows = []
    while position < len(text):
        position += len(text[position:]) - len(text[position:].lstrip(" \t\r\n,"))
        if position >= len(text) or text[position] == "]":
            break
        try:
            row, end = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            break
        rows.append(row)
        position = end
    if not rows:
        raise SnapshotError("Qualified JSON prefix contains no complete rows.")
    return rows


def _bundle(members, read_member):
    result = {}
    for member in members:
        raw = read_member(member["name"])
        kind = member["encoding"]
        if kind == "hex":
            result[member["field"]] = raw.hex()
        elif kind == "text":
            result[member["field"]] = raw.decode("utf-8").strip()
        elif kind in ("json_filter", "json_prefix_filter"):
            selection = member["selection"]
            data = (
                json_prefix_rows(raw, selection["key"])
                if kind == "json_prefix_filter"
                else json.loads(raw)[selection["key"]]
            )
            result[member["field"]] = [
                row for row in data if row[selection["match_field"]] == selection["match_value"]
            ]
        else:
            raise SnapshotError("Unsupported archive member reader.")
    return canonical_json(result)


def decode_record(record, files):
    """Decode an explicitly selected row or paired media sample from pinned bytes."""
    reader = record["reader"]
    stream = files[reader["container"]]
    kind = reader["kind"]
    if kind == "parquet_row":
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(stream)
        group = reader["row_group"]
        metadata = parquet.metadata.row_group(group)
        if metadata.total_byte_size > MAX_EXPANDED_BYTES or metadata.num_rows > 10000:
            raise SnapshotError("Parquet row group exceeds its decode bound.")
        return canonical_json(
            parquet.read_row_group(group).slice(reader["row_index"], 1).to_pylist()[0]
        )
    if kind == "json_slice":
        stream.seek(reader["start"])
        return canonical_json(json.loads(stream.read(reader["length"])))
    if kind in ("zip_bundle", "zip_csv_row"):
        with zipfile.ZipFile(stream) as archive:
            if kind == "zip_bundle":

                def read_member(name):
                    member = next(item for item in reader["members"] if item["name"] == name)
                    if member["encoding"] == "json_prefix_filter":
                        with archive.open(name) as stream:
                            return stream.read(min(member["prefix_bytes"], MAX_EXPANDED_BYTES))
                    return _zip_member(archive, name)

                return _bundle(reader["members"], read_member)
            raw = _zip_member(archive, reader["member"]).decode("utf-8")
            rows = csv.DictReader(
                io.StringIO(raw), delimiter=reader["delimiter"], fieldnames=reader.get("fieldnames")
            )
            for index, row in enumerate(rows):
                if index == reader["row_index"]:
                    for name in reader.get("numeric_fields", []):
                        row[name] = float(row[name])
                    return canonical_json(row)
            raise SnapshotError("Qualified CSV row is absent.")
    if kind == "tar_bundle":
        stream.seek(0)
        compressed = stream.read(reader["prefix_bytes"])
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        expanded = decoder.decompress(compressed, MAX_EXPANDED_BYTES + 1)
        if len(expanded) > MAX_EXPANDED_BYTES or decoder.unconsumed_tail:
            raise SnapshotError("Archive prefix exceeds its expansion bound.")
        selected = {member["name"] for member in reader["members"]}
        found = {}
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r|") as archive:
            for item in archive:
                if item.name in selected:
                    if not item.isfile() or item.size > MAX_SAMPLE_BYTES or item.issparse():
                        raise SnapshotError("Qualified tar member is not a bounded regular file.")
                    found[item.name] = archive.extractfile(item).read()
                    if len(found) == len(selected):
                        break
        if found.keys() != selected:
            raise SnapshotError("Qualified archive members are absent from the bounded prefix.")
        return _bundle(reader["members"], lambda name: found[name])
    raise SnapshotError("Unsupported qualified subset reader.")


def record_url(manifest, record):
    if "reader" in record:
        return manifest["containers"][record["reader"]["container"]]["url"]
    return record["upstream_url"]


def fetch_qualified_record(source, record, transport):
    manifest = load_manifest(source)
    expected = next(
        (
            entry
            for entry in manifest["records"] + manifest["licenses"]
            if entry["path"] == record.path
        ),
        None,
    )
    if (
        expected is None
        or expected["size"] != record.size
        or expected["blob_sha1"] != record.blob_sha1
    ):
        raise SnapshotError("Transfer plan is outside the pinned qualification manifest.")
    try:
        if "reader" not in expected:
            path = CATALOG_ROOT / "notices" / expected["archive_name"]
            if path.parent != CATALOG_ROOT / "notices" or path.name != expected["archive_name"]:
                raise SnapshotError("Notice archive path is invalid.")
            raw = path.read_bytes()
        else:
            files = {
                key: RangeFile(container, transport)
                for key, container in manifest["containers"].items()
            }
            raw = decode_record(expected, files)
        if len(raw) != expected["size"] or digest(raw) != expected["sha256"]:
            raise SnapshotError("Upstream sample failed its qualified SHA-256 digest.")
        return raw
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        ImportError,
        zipfile.BadZipFile,
        tarfile.TarError,
        zlib.error,
    ):
        raise SnapshotError("Qualified subset bytes could not be decoded and verified.") from None


def validate_sample(source_id, payload):
    """Validate the admitted source shape without inventing task labels or running tools."""
    try:
        if not payload or len(payload) > MAX_SAMPLE_BYTES:
            raise ValueError()
        value = json.loads(payload)
        if not isinstance(value, dict) or canonical_json(value) != payload:
            raise ValueError()
        if source_id in (
            "text-smol-magpie-ultra",
            "text-ultrachat-200k",
            "preference-ultrafeedback-binarized",
        ):
            columns = (
                ("chosen", "rejected") if source_id.startswith("preference-") else ("messages",)
            )
            for column in columns:
                messages = value[column]
                if not isinstance(messages, list) or not messages:
                    raise ValueError()
                for message in messages:
                    if (
                        not isinstance(message, dict)
                        or message["role"]
                        not in ("system", "developer", "user", "assistant", "tool")
                        or not isinstance(message["content"], str)
                    ):
                        raise ValueError()
        elif source_id == "text-squad":
            context, question, answers = value["context"], value["question"], value["answers"]
            if (
                not isinstance(context, str)
                or not isinstance(question, str)
                or not question
                or not answers["text"]
                or len(answers["text"]) != len(answers["answer_start"])
            ):
                raise ValueError()
            for text, start in zip(answers["text"], answers["answer_start"]):
                if (
                    type(start) is not int
                    or start < 0
                    or context[start : start + len(text)] != text
                ):
                    raise ValueError()
        elif source_id == "tools-glaive-v2":
            if (
                not isinstance(value["system"], str)
                or not isinstance(value["chat"], str)
                or not value["chat"]
            ):
                raise ValueError()
        elif source_id == "image-clevr":
            if (
                not bytes.fromhex(value["image_hex"]).startswith(b"\x89PNG\r\n\x1a\n")
                or not isinstance(value["questions"], list)
                or not value["questions"]
            ):
                raise ValueError()
            for question in value["questions"]:
                if not isinstance(question["question"], str) or "answer" not in question:
                    raise ValueError()
        elif source_id in ("audio-vctk", "audio-libritts-r"):
            raw = bytes.fromhex(value["audio_hex"])
            valid_audio = (
                raw.startswith(b"fLaC")
                if source_id == "audio-vctk"
                else raw.startswith(b"RIFF") and raw[8:12] == b"WAVE"
            )
            if not valid_audio or not isinstance(value["text"], str) or not value["text"]:
                raise ValueError()
        elif source_id in ("numeric-iris", "numeric-wine-quality"):
            import math

            fields = [key for key in value if key != "species"]
            if not fields or any(
                type(value[key]) not in (float, int) or not math.isfinite(value[key])
                for key in fields
            ):
                raise ValueError()
        else:
            raise ValueError()
        return value
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError):
        raise SnapshotError("Sample does not match the qualified source schema.") from None
