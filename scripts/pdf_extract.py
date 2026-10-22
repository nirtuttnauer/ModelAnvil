"""Isolated bounded PDF text parser. Raw stdin in; safe JSON stdout out."""
import io
import json
import logging
import resource
import sys

MAX_INPUT = 16 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
MAX_STREAM = 1024 * 1024
MAX_PAGES = 100


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    # macOS refuses RLIMIT_AS; stream/page/output caps and a parent timeout still apply.
    import pypdf
    from pypdf import filters
    if pypdf.__version__ != "6.21.2":
        return 2
    logging.disable(logging.CRITICAL)
    for setting in ("ZLIB_MAX_OUTPUT_LENGTH", "LZW_MAX_OUTPUT_LENGTH", "RUN_LENGTH_MAX_OUTPUT_LENGTH",
                    "JBIG2_MAX_OUTPUT_LENGTH", "MAX_DECLARED_STREAM_LENGTH", "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH"):
        setattr(filters, setting, MAX_STREAM)
    filters.ZLIB_MAX_RECOVERY_INPUT_LENGTH = 0
    filters.JBIG2DEC_BINARY = None
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if not raw.startswith(b"%PDF-") or len(raw) > MAX_INPUT:
        return 3
    reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        return 4
    if not 0 < len(reader.pages) <= MAX_PAGES:
        return 5
    pages = []
    decoded = 0
    for number, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content is None:
            return 6
        size = len(content.get_data())
        decoded += size
        if size > MAX_STREAM or decoded > MAX_OUTPUT:
            return 5
        text = page.extract_text()
        if not text or not text.strip():
            return 6
        pages.append({"page": number, "text": text})
    output = json.dumps({"pages": pages}, ensure_ascii=True, allow_nan=False).encode("utf-8")
    if len(output) > MAX_OUTPUT:
        return 5
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Parser diagnostics can contain source text; only fixed exit codes cross the boundary.
        sys.exit(3)
