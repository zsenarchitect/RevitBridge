"""Tests for the static RVT probe.

Byte-level units use synthetic payloads (committed). The container-level
test uses a real Autodesk sample ONLY if present at /tmp (never committed);
it skips otherwise.
"""

import os
import zlib

import pytest

from revit_bridge import rvt_probe
from revit_bridge.rvt_probe import (
    decompress_stream,
    extract_preview,
    parse_basic_file_info,
    parse_part_atom,
    schema_class_names,
)

REAL_SAMPLE = "/tmp/racbasicsamplefamily-2024.rfa"


def _truncated_gzip(payload: bytes) -> bytes:
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = comp.compress(payload) + comp.flush()
    return b"\x1f\x8b\x08\x00" + b"\x00" * 6 + raw  # 10-byte header + raw DEFLATE


def test_decompress_stream_plain():
    data = _truncated_gzip(b"hello-revit")
    assert decompress_stream(data, "Formats/Latest") == b"hello-revit"


def test_decompress_stream_global_header():
    data = b"\x00" * 8 + _truncated_gzip(b"global-payload")
    assert decompress_stream(data, "Global/Latest") == b"global-payload"


def test_decompress_stream_bad_magic():
    with pytest.raises(ValueError):
        decompress_stream(b"not-gzip", "Formats/Latest")


def test_parse_basic_file_info():
    raw = "2024\x0020230308_1635(x64)\x00C:\\models\\x.rvt\x00".encode("utf-16-le")
    info = parse_basic_file_info(raw)
    assert info["version"] == "2024"
    assert info["build"] == "20230308_1635(x64)"
    assert info["original_path"] == "C:\\models\\x.rvt"


def test_extract_preview():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    blob = bytes.fromhex("62192205") + b"\x00" * 40 + png
    assert extract_preview(blob) == png
    assert extract_preview(b"no-magic-here") is None


def test_parse_part_atom():
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<entry xmlns="http://www.w3.org/2005/Atom">'
        b"<title>demo-family</title><id>Some-Id</id></entry>"
    )
    assert parse_part_atom(xml) == {"title": "demo-family", "id": "Some-Id"}
    assert parse_part_atom(b"<broken") == {}


def test_schema_class_names():
    n, sample = schema_class_names(b"\x00ADocument\x00DBView\x00ADocument\x00x1\x00")
    assert n == 2
    assert sample == ["ADocument", "DBView"]


@pytest.mark.skipif(not os.path.exists(REAL_SAMPLE), reason="no real sample at /tmp")
def test_probe_real_autodesk_sample():
    """Cross-witness smoke test against Autodesk's own sample family file."""
    res = rvt_probe.probe(REAL_SAMPLE)
    assert res.is_revit_container
    assert res.version == "2024"
    assert res.build == "20230308_1635(x64)"
    assert len(res.streams) == 13
    assert any(s["name"] == "Partitions/67" for s in res.streams)
    assert res.preview_png is not None and res.preview_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert res.schema_classes > 1000
    assert res.part_atom.get("title") == "racbasicsamplefamily"


def test_probe_rejects_non_ole(tmp_path):
    p = tmp_path / "not-revit.rvt"
    p.write_bytes(b"definitely not a compound document")
    with pytest.raises(ValueError):
        rvt_probe.probe(str(p))
