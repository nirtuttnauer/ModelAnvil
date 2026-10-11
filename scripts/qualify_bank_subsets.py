"""Fetch, pin, and independently refetch bounded public Dataset Bank subsets.

Run from the repository with the pinned requirements installed. Only license
notices, selectors, hashes, and aggregate measurements are committed; dataset
payloads and pilot artifacts belong in temporary/ignored storage.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import io
import json
import time
import urllib.request
import zipfile
import zlib
import tarfile
from pathlib import Path

from modelanvil.data.bank.http_snapshot import (
    CATALOG_ROOT,
    CONNECTOR,
    MAX_TRANSFER_BYTES,
    RangeFile,
    cached_transport,
    canonical_json,
    decode_record,
    digest,
    json_prefix_rows,
    validate_manifest,
    validate_sample,
)

ROOT = Path(__file__).resolve().parents[1]
HF_SOURCES = {
    "text-smol-magpie-ultra": ("HuggingFaceTB/smoltalk", "data/smol-magpie-ultra/train-00000"),
    "text-ultrachat-200k": ("HuggingFaceH4/ultrachat_200k", "data/train_sft-00000"),
    "text-squad": ("rajpurkar/squad", "plain_text/train-00000"),
    "preference-ultrafeedback-binarized": (
        "HuggingFaceH4/ultrafeedback_binarized",
        "data/train_prefs-00000",
    ),
    "tools-glaive-v2": ("glaiveai/glaive-function-calling-v2", "glaive-function-calling-v2.json"),
}
ARCHIVES = {
    "image-clevr": "https://dl.fbaipublicfiles.com/clevr/CLEVR_v1.0.zip",
    "audio-vctk": "https://datashare.ed.ac.uk/server/api/core/bitstreams/535f4286-e54c-4038-838c-a02285e32cb2/content",
    "audio-libritts-r": "https://openslr.trmal.net/resources/141/train_clean_100.tar.gz",
    "numeric-iris": "https://archive.ics.uci.edu/static/public/53/iris.zip",
    "numeric-wine-quality": "https://archive.ics.uci.edu/static/public/186/wine+quality.zip",
}


def transport(url, headers):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(MAX_TRANSFER_BYTES + 1)
        if len(payload) > MAX_TRANSFER_BYTES:
            raise ValueError("Upstream response exceeds bounded transfer size.")
        return response.status, payload, dict(response.headers)


def get(url):
    status, body, headers = transport(url, {"User-Agent": "modelanvil-dataset-bank"})
    if status != 200:
        raise ValueError("Upstream metadata is unavailable.")
    return body


def blob_sha1(raw):
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def size_at(url):
    status, raw, headers = transport(url, {"Range": "bytes=0-1023", "Accept-Encoding": "identity"})
    if status == 206:
        value = next(v for k, v in headers.items() if k.lower() == "content-range")
        return int(value.rsplit("/", 1)[1]), headers
    if status == 200:
        headers["transfer_mode"] = "whole_file"
        return len(raw), headers
    raise ValueError("Archive must support bounded byte ranges.")


def group_for(source_id, row):
    if source_id == "text-squad":
        return "squad:passage:" + digest(row["context"].encode())
    if source_id in ("text-ultrachat-200k", "preference-ultrafeedback-binarized"):
        return "prompt:" + row["prompt_id"]
    if "messages" in row:
        return "prompt:" + digest(
            canonical_json([m for m in row["messages"] if m["role"] == "user"][:1])
        )
    if source_id == "tools-glaive-v2":
        return "glaive:schema:" + digest(row["system"].encode())
    return source_id + ":" + digest(canonical_json(row))


def qualify(source, date):
    source_id = source["id"]
    started = time.monotonic()
    measured_transport = cached_transport(transport)
    manifest = {
        "schema_version": "1.0",
        "source_id": source_id,
        "upstream": {},
        "containers": {},
        "records": [],
        "licenses": [],
    }
    files = {}
    notice_payloads = {}

    def archive_notice(source_id, name, raw, url):
        archive_name = source_id + "-" + name + ".txt"
        notice_payloads[archive_name] = raw
        return {
            "path": "notice/" + name,
            "archive_name": archive_name,
            "upstream_url": url,
            "size": len(raw),
            "sha256": digest(raw),
            "blob_sha1": blob_sha1(raw),
        }

    def add_file(key, url, size):
        container = {"url": url, "size": size}
        manifest["containers"][key] = container
        files[key] = RangeFile(container, measured_transport, capture=True)
        return files[key]

    def add_sample(path, reader, group, metadata):
        record = {"path": path, "reader": reader, "source_group_id": group, "metadata": metadata}
        raw = decode_record(record, files)
        if len(raw) > 1024 * 1024:
            raise ValueError("Selected sample exceeds 1 MiB.")
        validate_sample(source_id, raw)
        record.update(size=len(raw), sha256=digest(raw), blob_sha1=blob_sha1(raw))
        manifest["records"].append(record)

    if source_id in HF_SOURCES:
        repo, prefix = HF_SOURCES[source_id]
        info = json.loads(get("https://huggingface.co/api/datasets/" + repo + "/revision/main"))
        revision = info["sha"]
        listing = json.loads(
            get(
                f"https://huggingface.co/api/datasets/{repo}/tree/{revision}?recursive=true&limit=1000"
            )
        )
        entry = next(e for e in listing if e["path"].startswith(prefix) and e["type"] == "file")
        url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{entry['path']}"
        stream = add_file("data", url, entry["size"])
        manifest["upstream"] = {
            "repository": repo,
            "commit": revision,
            "file": entry["path"],
            "file_size": entry["size"],
            "publisher_lfs_sha256": entry.get("lfs", {}).get("oid"),
            "full_file_checksum_verified": False,
        }
        readme_url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/README.md"
        manifest["licenses"].append(
            archive_notice(source_id, "publisher-card", get(readme_url), readme_url)
        )
        if source_id != "tools-glaive-v2":
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(stream)
            groups = sorted(set(int(i * (parquet.num_row_groups - 1) / 3) for i in range(4)))
            for group in groups:
                count = parquet.metadata.row_group(group).num_rows
                rows = parquet.read_row_group(group)
                for index in sorted(set(int(i * (count - 1) / 4) for i in range(5))):
                    row = rows.slice(index, 1).to_pylist()[0]
                    reader = {
                        "kind": "parquet_row",
                        "container": "data",
                        "row_group": group,
                        "row_index": index,
                    }
                    add_sample(
                        f"{entry['path']}#group={group}&row={index}",
                        reader,
                        group_for(source_id, row),
                        {
                            "upstream_split": "train_prefs"
                            if "preference-" in source_id
                            else "train_sft"
                            if "ultrachat" in source_id
                            else "train",
                            "configuration": source["fetch"].get("configuration"),
                        },
                    )
        else:
            stream.seek(0)
            raw = stream.read(256 * 1024)
            text = raw.decode("utf-8")
            decoder = json.JSONDecoder()
            position = text.index("[") + 1
            for index in range(20):
                position += len(text[position:]) - len(text[position:].lstrip(" \t\r\n,"))
                row, end = decoder.raw_decode(text, position)
                start = len(text[:position].encode("utf-8"))
                length = len(text[position:end].encode("utf-8"))
                reader = {
                    "kind": "json_slice",
                    "container": "data",
                    "start": start,
                    "length": length,
                }
                add_sample(
                    f"{entry['path']}#row={index}",
                    reader,
                    group_for(source_id, row),
                    {"upstream_split": "train"},
                )
                position = end
    else:
        url = ARCHIVES[source_id]
        size, headers = size_at(url)
        stream = add_file("data", url, size)
        if headers.get("transfer_mode") == "whole_file":
            stream.container["transfer_mode"] = "whole_file"
        manifest["upstream"] = {
            "release_url": url,
            "archive_size": size,
            "archive_etag": next((v for k, v in headers.items() if k.lower() == "etag"), None),
            "full_archive_checksum_verified": False,
        }
        if source_id != "audio-libritts-r":
            with zipfile.ZipFile(stream) as archive:
                names = archive.namelist()
                if source_id == "image-clevr":
                    questions = "CLEVR_v1.0/questions/CLEVR_train_questions.json"
                    with archive.open(questions) as q:
                        rows = json_prefix_rows(q.read(2 * 1024 * 1024), "questions")
                    indexes = list(dict.fromkeys(row["image_index"] for row in rows))[:10]
                    for index in indexes:
                        image = f"CLEVR_v1.0/images/train/CLEVR_train_{index:06d}.png"
                        reader = {
                            "kind": "zip_bundle",
                            "container": "data",
                            "members": [
                                {"name": image, "field": "image_hex", "encoding": "hex"},
                                {
                                    "name": questions,
                                    "field": "questions",
                                    "encoding": "json_prefix_filter",
                                    "prefix_bytes": 2 * 1024 * 1024,
                                    "selection": {
                                        "key": "questions",
                                        "match_field": "image_index",
                                        "match_value": index,
                                    },
                                },
                            ],
                        }
                        add_sample(
                            image,
                            reader,
                            "clevr:train:" + str(index),
                            {
                                "upstream_split": "train",
                                "question_selection": "complete questions present in the first 2 MiB of the question member",
                            },
                        )
                    for name in ["LICENSE.txt", "COPYRIGHT.txt", "README.txt"]:
                        member = "CLEVR_v1.0/" + name
                        manifest["licenses"].append(
                            archive_notice(
                                source_id,
                                name.replace(".txt", "").lower(),
                                archive.read(member),
                                url + "#" + member,
                            )
                        )
                elif source_id == "audio-vctk":
                    speakers = sorted(
                        set(
                            name.split("/")[1]
                            for name in names
                            if name.endswith("_mic1.flac")
                            and name.startswith("wav48_silence_trimmed/")
                            and not "/p315/" in name
                        )
                    )
                    for speaker in speakers[:10]:
                        audio_names = sorted(
                            name
                            for name in names
                            if name.startswith("wav48_silence_trimmed/" + speaker + "/")
                            and name.endswith("_mic1.flac")
                        )
                        for name in audio_names[:2]:
                            utterance = name.rsplit("/", 1)[1].removesuffix("_mic1.flac")
                            text_name = f"txt/{speaker}/{utterance}.txt"
                            reader = {
                                "kind": "zip_bundle",
                                "container": "data",
                                "members": [
                                    {"name": name, "field": "audio_hex", "encoding": "hex"},
                                    {"name": text_name, "field": "text", "encoding": "text"},
                                ],
                            }
                            add_sample(
                                utterance,
                                reader,
                                "vctk:speaker:" + speaker,
                                {
                                    "speaker_id": speaker,
                                    "utterance_id": utterance,
                                    "microphone": "mic1",
                                    "upstream_split": None,
                                },
                            )
                    notice_url = source["license"]["evidence_urls"][0]
                    manifest["licenses"].append(
                        archive_notice(
                            source_id, "publisher-declaration", get(notice_url), notice_url
                        )
                    )
                else:
                    members = (
                        ["iris.data"]
                        if source_id == "numeric-iris"
                        else ["winequality-red.csv", "winequality-white.csv"]
                    )
                    for member in members:
                        import csv

                        rows = list(
                            csv.reader(
                                io.StringIO(archive.read(member).decode()),
                                delimiter="," if source_id == "numeric-iris" else ";",
                            )
                        )
                        rows = [row for row in rows if row]
                        fields = (
                            [
                                "sepal_length",
                                "sepal_width",
                                "petal_length",
                                "petal_width",
                                "species",
                            ]
                            if source_id == "numeric-iris"
                            else None
                        )
                        numeric = fields[:4] if fields else rows[0]
                        count = len(rows) if fields else len(rows) - 1
                        for index in sorted(set(int(i * (count - 1) / 19) for i in range(20))):
                            reader = {
                                "kind": "zip_csv_row",
                                "container": "data",
                                "member": member,
                                "delimiter": "," if fields else ";",
                                "fieldnames": fields,
                                "numeric_fields": numeric,
                                "row_index": index,
                            }
                            record = {"reader": reader}
                            row = json.loads(decode_record(record, files))
                            group = (
                                source_id
                                + ":features:"
                                + digest(
                                    canonical_json(
                                        {
                                            k: v
                                            for k, v in row.items()
                                            if k not in ("species", "quality")
                                        }
                                    )
                                )
                            )
                            add_sample(
                                member + "#row=" + str(index),
                                reader,
                                group,
                                {"wine_type": member.split("-")[1].split(".")[0]}
                                if not fields
                                else {"feature_units": "cm"},
                            )
                    notice_url = source["source_url"]
                    manifest["licenses"].append(
                        archive_notice(
                            source_id, "publisher-declaration", get(notice_url), notice_url
                        )
                    )
        else:
            prefix_bytes = 8 * 1024 * 1024
            stream.seek(0)
            compressed = stream.read(prefix_bytes)
            expanded = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(
                compressed, 64 * 1024 * 1024 + 1
            )
            if len(expanded) > 64 * 1024 * 1024:
                raise ValueError("Archive prefix expansion exceeds bound.")
            available = {}
            with tarfile.open(fileobj=io.BytesIO(expanded), mode="r|") as archive:
                try:
                    for item in archive:
                        if item.isfile() and item.size <= 1024 * 1024:
                            available[item.name] = archive.extractfile(item).read()
                except tarfile.ReadError:
                    pass
            audio = sorted(name for name in available if name.endswith(".wav"))
            for name in audio:
                base = name.removesuffix(".wav")
                if base + ".normalized.txt" not in available:
                    continue
                # Canonical media is hex encoded; keep the paired sample within 1 MiB.
                if (
                    2 * len(available[name]) + len(available[base + ".normalized.txt"]) + 128
                    > 1024 * 1024
                ):
                    continue
                utterance = base.rsplit("/", 1)[1]
                speaker = utterance.split("_")[0]
                reader = {
                    "kind": "tar_bundle",
                    "container": "data",
                    "prefix_bytes": prefix_bytes,
                    "members": [
                        {"name": name, "field": "audio_hex", "encoding": "hex"},
                        {"name": base + ".normalized.txt", "field": "text", "encoding": "text"},
                    ],
                }
                add_sample(
                    utterance,
                    reader,
                    "libri:speaker:" + speaker,
                    {
                        "speaker_id": speaker,
                        "utterance_id": utterance,
                        "upstream_split": "train-clean-100",
                        "restored_audio": True,
                    },
                )
                if len(manifest["records"]) == 10:
                    break
            if not manifest["records"]:
                raise ValueError("No paired speech examples found in bounded prefix.")
            notice_url = "https://www.openslr.org/141/"
            manifest["licenses"].append(
                archive_notice(source_id, "publisher-declaration", get(notice_url), notice_url)
            )

    for key, stream in files.items():
        manifest["containers"][key]["segments"] = list(stream.segments.values())
    validate_manifest(manifest)
    raw_manifest = canonical_json(manifest)
    revision = digest(raw_manifest)
    # Independently refetch before replacing any existing qualification evidence.
    refetch = cached_transport(transport)
    for record in manifest["records"]:
        pinned = {
            key: RangeFile(container, refetch) for key, container in manifest["containers"].items()
        }
        raw = decode_record(record, pinned)
        assert digest(raw) == record["sha256"] and len(raw) == record["size"]
    (CATALOG_ROOT / "notices").mkdir(parents=True, exist_ok=True)
    for name, raw in notice_payloads.items():
        (CATALOG_ROOT / "notices" / name).write_bytes(raw)
    (CATALOG_ROOT / (source_id + ".json")).write_text(json.dumps(manifest, indent=2) + "\n")
    transfer_bytes = sum(
        s["length"] for c in manifest["containers"].values() for s in c["segments"]
    )
    sample_bytes = sum(r["size"] for r in manifest["records"])
    source["license"]["reviewed_revision"] = revision
    source["connector_status"] = "implemented_qualified_bounded_subset"
    source["publication_status"] = "qualified_bounded_download_enabled"
    source["size_bytes"] = transfer_bytes + sum(r["size"] for r in manifest["licenses"])
    source["record_count"] = len(manifest["records"])
    source["acquisition"] = {
        "status": "qualified",
        "qualified_on": date,
        "connector": CONNECTOR,
        "upstream_repository": source["source_url"],
        "pinned_revision": revision,
        "revision_resolved_on": date,
        "revision_selection": "SHA-256 of the frozen subset manifest: observed upstream ranges, decoded samples, and archived publisher license notices. Full archives/shards are not qualified.",
        "qualified_revisions": [revision],
        "include_patterns": [r["path"] for r in manifest["records"]],
        "license_paths": [r["path"] for r in manifest["licenses"]],
        "record_selection": "deterministic evenly spaced selection of the frozen, explicitly qualified sample inventory",
        "record_limit": len(manifest["records"]),
        "record_limit_max": len(manifest["records"]),
        "preview_limit": 3,
        "measured_upstream_records": len(manifest["records"]),
        "measured_upstream_bytes": source["size_bytes"],
        "measured_selected_records": len(manifest["records"]),
        "measured_selected_bytes": sample_bytes,
        "measured_transfer_seconds": round(time.monotonic() - started),
        "measurement_environment": "macOS arm64; CPython 3.12; PyArrow 26.0.0; public HTTPS byte-range downloads and independent refetch through the runtime decoder.",
        "verified_record_digests": True,
        "blocked_reason": "",
        "evidence": {
            "manifest_path": "catalog/qualified-datasets/" + source_id + ".json",
            "manifest_sha256": revision,
            "download_range_bytes": transfer_bytes,
            "decoded_sample_bytes": sample_bytes,
            "full_corpus_qualified": False,
            "checks": [
                "Actual upstream bytes fetched over HTTPS; every admitted range SHA-256 recorded.",
                "Each selected sample decoded without executing remote dataset code.",
                "Independent refetch through pinned range reader reproduced every selected sample digest.",
                "Publisher license declaration/notice bytes archived and digest-pinned.",
            ],
        },
    }
    return {
        "source_id": source_id,
        "manifest_sha256": revision,
        "records": len(manifest["records"]),
        "decoded_sample_bytes": sample_bytes,
        "download_range_bytes": transfer_bytes,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=list(HF_SOURCES) + list(ARCHIVES), action="append")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument(
        "--report", type=Path, help="Optional measurement report in temporary or ignored storage."
    )
    args = parser.parse_args()
    catalog_path = ROOT / "catalog/dataset-presets.json"
    catalog = json.loads(catalog_path.read_text())
    selected = args.source or list(HF_SOURCES) + list(ARCHIVES)
    output = args.report
    previous = json.loads(output.read_text()) if output and output.exists() else {"sources": []}
    by_id = {item["source_id"]: item for item in previous["sources"]}
    for source_id in selected:
        source = next(source for source in catalog["sources"] if source["id"] == source_id)
        print("Qualifying " + source_id, flush=True)
        report = qualify(source, args.date)
        catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
        by_id[source_id] = report
        if output:
            output.write_text(
                json.dumps(
                    {
                        "date": args.date,
                        "scope": "bounded source subsets; full corpora and training recipes are not qualified",
                        "sources": list(by_id.values()),
                    },
                    indent=2,
                )
                + "\n"
            )
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
