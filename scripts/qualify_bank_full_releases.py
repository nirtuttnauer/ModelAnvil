"""Whole-release format qualification; requires fully checksummed local files.

Use the inventories, publisher pins and byte chunks in catalog/full-datasets.
pyarrow is required for Parquet. Payloads and reports stay in an operator cache.
"""

import argparse
import csv
import hashlib
import io
import json
import pathlib
import struct
import tarfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pyarrow.parquet as pq


def safe(n):
    p = pathlib.PurePosixPath(n)
    assert not p.is_absolute() and ".." not in p.parts and "\\" not in n, n


def json_array(stream):
    decoder = json.JSONDecoder()
    buf = ""
    end = False
    started = False
    count = 0
    need_separator = False
    while True:
        if not end and len(buf) < 1048576:
            x = stream.read(1048576)
            end = not x
            buf += x
        buf = buf.lstrip()
        if not started:
            assert buf.startswith("[")
            buf = buf[1:]
            started = True
            continue
        if buf.startswith("]"):
            assert not buf[1:].strip() and not stream.read().strip()
            return count
        if need_separator:
            assert buf.startswith(","), "Missing JSON array separator"
            buf = buf[1:].lstrip()
            assert not buf.startswith("]"), "Trailing JSON array comma"
            need_separator = False
        try:
            row, k = decoder.raw_decode(buf)
        except json.JSONDecodeError:
            assert not end and len(buf) < 32 * 1048576, (
                "Truncated or oversized JSON record"
            )
            buf += stream.read(1048576)
            continue
        assert (
            isinstance(row, dict)
            and isinstance(row.get("system"), str)
            and isinstance(row.get("chat"), str)
        )
        count += 1
        need_separator = True
        buf = buf[k:]


def validate(s, f, root):
    p = root / s["source_id"] / pathlib.Path(f["path"]).name
    out = pathlib.Path(str(p) + ".validated.json")
    # Always repeat content validation when explicitly invoked.
    v = {"all_content_read": True, "format": f["format"]}
    sid = s["source_id"]
    fmt = f["format"]
    start = time.monotonic()
    sha = hashlib.sha256()
    md5 = hashlib.md5()
    position = 0
    with p.open("rb") as stream:
        for chunk in f["chunks"]:
            assert chunk["start"] == position
            raw = stream.read(chunk["length"])
            assert (
                len(raw) == chunk["length"]
                and hashlib.sha256(raw).hexdigest() == chunk["sha256"]
            )
            sha.update(raw)
            md5.update(raw)
            position += len(raw)
        assert not stream.read(1)
    assert position == f["size"] and sha.hexdigest() == f["sha256"]
    if f.get("publisher_sha256"):
        assert sha.hexdigest() == f["publisher_sha256"]
    if f.get("publisher_md5"):
        assert md5.hexdigest() == f["publisher_md5"]
    v["whole_file_sha256_verified"] = True
    if fmt == "parquet":
        q = pq.ParquetFile(p)
        n = 0
        for batch in q.iter_batches(batch_size=512):
            batch.validate(full=True)
            for row in batch.to_pylist():
                if sid in ("text-ultrachat-200k", "text-smol-magpie-ultra"):
                    assert isinstance(row["messages"], list) and row["messages"]
                    assert all(
                        isinstance(m["role"], str) and isinstance(m["content"], str)
                        for m in row["messages"]
                    )
                elif sid == "text-squad":
                    assert all(
                        isinstance(row[k], str)
                        for k in ("id", "title", "context", "question")
                    )
                    a = row["answers"]
                    assert len(a["text"]) == len(a["answer_start"])
                    assert all(
                        row["context"][pos : pos + len(txt)] == txt
                        for txt, pos in zip(a["text"], a["answer_start"])
                    )
                elif sid == "preference-ultrafeedback-binarized":
                    for key in ("chosen", "rejected", "messages"):
                        if key in row:
                            assert isinstance(row[key], list) and row[key]
                            assert all(
                                isinstance(m["role"], str)
                                and isinstance(m["content"], str)
                                for m in row[key]
                            )
                n += 1
        assert n == q.metadata.num_rows
        v.update(
            rows=n,
            row_groups=q.num_row_groups,
            columns=q.schema_arrow.names,
            all_rows_validated=True,
        )
    elif fmt == "json":
        with p.open(encoding="utf8") as stream:
            n = json_array(stream)
        v.update(rows=n, all_rows_validated=True)
    elif fmt == "zip":
        n = unpacked = png = flac = csvrows = 0
        member_summary = {}
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                safe(info.filename)
                assert (info.external_attr >> 16) & 0o170000 != 0o120000
                if info.is_dir():
                    continue
                n += 1
                unpacked += info.file_size
                with z.open(info) as stream:
                    head = stream.read(128)
                    if info.filename.endswith(".png"):
                        assert head.startswith(b"\x89PNG\r\n\x1a\n")
                        png += 1
                    if info.filename.endswith(".flac"):
                        assert head.startswith(b"fLaC")
                        flac += 1
                    if (
                        info.filename.endswith(".csv")
                        or sid == "numeric-iris"
                        and info.filename.endswith(".data")
                    ):
                        data = head + stream.read()
                        rows = list(
                            csv.reader(
                                io.StringIO(data.decode("utf8")),
                                delimiter=";" if sid == "numeric-wine-quality" else ",",
                            )
                        )
                        if sid == "numeric-iris":
                            rows = [r for r in rows if r]
                            assert all(len(r) == 5 for r in rows)
                            assert all(
                                all(float(x) == float(x) for x in r[:4]) for r in rows
                            )
                            csvrows += len(rows)
                        else:
                            assert all(len(r) == 12 for r in rows)
                            assert all(
                                all(float(x) == float(x) for x in r) for r in rows[1:]
                            )
                            csvrows += len(rows) - 1
                    elif sid == "image-clevr" and info.filename.endswith(".json"):
                        data = json.loads(head + stream.read())
                        key = (
                            "questions" if "/questions/" in info.filename else "scenes"
                        )
                        count = len(data[key])
                        member_summary[info.filename] = count
                    else:
                        while stream.read(1048576):
                            pass
        v.update(
            members=n,
            uncompressed_bytes=unpacked,
            png_images=png,
            flac_recordings=flac,
            rows=csvrows,
            all_member_crc_verified=True,
            json_records=member_summary,
        )
        if sid == "image-clevr":
            assert png == 100000 and sum(member_summary.values()) > 850000
        if sid == "numeric-iris":
            assert (
                csvrows == 300
            )  # Both publisher versions, iris.data and bezdekIris.data.
        if sid == "numeric-wine-quality":
            assert csvrows == 6497
    elif fmt == "tar.gz":
        n = wav = txt = unpacked = 0
        with tarfile.open(p, mode="r|gz") as t:
            for info in t:
                safe(info.name)
                assert info.isdir() or info.isfile(), info.name
                if not info.isfile():
                    continue
                n += 1
                unpacked += info.size
                stream = t.extractfile(info)
                head = stream.read(min(128, info.size))
                if info.name.endswith(".wav"):
                    assert head[:4] == b"RIFF" and head[8:12] == b"WAVE"
                    assert struct.unpack("<I", head[24:28])[0] == 24000
                    wav += 1
                if info.name.endswith(".txt"):
                    txt += 1
                while stream.read(1048576):
                    pass
        # Read gzip to its actual EOF as tar iteration can stop before gzip footer.
        import gzip

        with gzip.open(p, "rb") as stream:
            while stream.read(1048576):
                pass
        v.update(
            members=n,
            uncompressed_bytes=unpacked,
            wav_recordings=wav,
            text_members=txt,
            gzip_crc_verified=True,
        )
        if f["path"] not in (
            "doc.tar.gz",
            "libritts_r_failed_speech_restoration_examples.tar.gz",
        ):
            assert wav > 0 and txt > 0
    v["validation_seconds"] = round(time.monotonic() - start, 3)
    out.write_text(json.dumps(v, indent=2) + "\n")
    print(json.dumps({"validated": sid + "/" + f["path"], **v}), flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Verify every byte, row and archive member of complete releases. Reports stay beside local files."
    )
    parser.add_argument("--inventory", type=pathlib.Path, required=True)
    parser.add_argument("--cache", type=pathlib.Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text())
    if isinstance(inventory, dict):
        inventory = [inventory]
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = [
            executor.submit(validate, source, file, args.cache)
            for source in inventory
            for file in source["files"]
        ]
        for job in jobs:
            job.result()


if __name__ == "__main__":
    main()
