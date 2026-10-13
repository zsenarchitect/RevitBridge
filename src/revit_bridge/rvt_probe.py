"""Static-only probe for Autodesk Revit files (.rvt/.rfa/.rte/.rft).

Built by applying the reverse-engineer-anything skill to the RVT container:

Phase 0 (intake): samples are Autodesk-distributed files (e.g. the
``rac_basic_sample_family`` series, CC BY-NC-SA per Autodesk's terms).
Samples are NEVER committed; tests use synthetic fixtures plus an optional
real-file smoke test that skips when no sample is present.

Phase 1 (triage): magic bytes say OLE2 Compound Document (public MS-CFB).
Stream inventory is fully enumerable.

Phase 2 (structure), outermost first:
  1. Container: OLE/CFB via ``olefile`` (public standard).
  2. Compression: truncated gzip (10-byte header + raw DEFLATE, no CRC/ISIZE).
     ``Global/*`` streams prepend an 8-byte Revit framing header before the
     gzip member; ``Formats/Latest`` omits it.
  3. Records: ``BasicFileInfo`` is UTF-16LE text (version/build/path);
     ``RevitPreview4.0`` is a PNG after a ~300-byte wrapper headed by magic
     ``62 19 22 05``; ``PartAtom`` is Atom XML; ``Formats/Latest``
     decompresses to the embedded class schema (ASCII class names).

Phase 3 (verification): every claim below is cross-witnessed against the
independent rvt-rs/phi-ag RE writeups AND a real Autodesk sample file
(``racbasicsamplefamily-2024.rfa``, 397312 bytes, 13 streams).

What this is NOT: element-geometry extraction. The ``Partitions/NN``
element streams' wire envelope is not reverse-engineered here; anyone
claiming full RVT->geometry without Autodesk tooling is selling vaporware.
See the README capability matrix.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

REVT_MAGIC_CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE2 compound document
PREVIEW_WRAPPER_MAGIC = bytes.fromhex("62192205")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GZIP_MAGIC = b"\x1f\x8b"

#: Partitions/NN stream index per Revit release (cross-witnessed).
PARTITION_INDEX = {
    2016: 58, 2017: 60, 2018: 62, 2019: 63, 2020: 64,
    2021: 65, 2022: 65, 2023: 66, 2024: 67, 2025: 68, 2026: 69,
}

_STREAMS_8BYTE_HEADER = ("Global/",)  # streams with 8-byte framing before gzip


@dataclass
class ProbeResult:
    path: str
    is_revit_container: bool
    version: str | None = None          # e.g. "2024"
    build: str | None = None            # e.g. "20230308_1635(x64)"
    original_path: str | None = None
    streams: list[dict] = field(default_factory=list)
    part_atom: dict = field(default_factory=dict)
    schema_classes: int = 0
    schema_sample: list[str] = field(default_factory=list)
    preview_png: bytes | None = None
    notes: list[str] = field(default_factory=list)


def _open_ole(path: str | Path):
    import olefile  # lazy: only needed for probing

    if not olefile.isOleFile(str(path)):
        raise ValueError(f"Not an OLE compound document: {path}")
    return olefile.OleFileIO(str(path))


def list_streams(path: str | Path) -> list[dict]:
    """Phase 1: enumerate every stream in the container."""
    ole = _open_ole(path)
    out = []
    for entry in ole.listdir(streams=True):
        name = "/".join(entry)
        out.append({"name": name, "size": ole.get_size(entry)})
    ole.close()
    return sorted(out, key=lambda s: s["name"])


def decompress_stream(data: bytes, stream_name: str = "") -> bytes:
    """Phase 2: undo Revit's truncated-gzip framing.

    Layout: [8-byte Revit header for Global/* streams][10-byte gzip header]
    [raw DEFLATE ...] (no trailing CRC/ISIZE).
    """
    body = data
    if stream_name.startswith(_STREAMS_8BYTE_HEADER):
        body = body[8:]
    if body[:2] != GZIP_MAGIC:
        raise ValueError(f"Stream {stream_name!r}: expected gzip magic, got {body[:2].hex()}")
    return zlib.decompress(body[10:], -15)  # raw DEFLATE


def parse_basic_file_info(data: bytes) -> dict:
    """Phase 2: BasicFileInfo is UTF-16LE text: version, build, original path."""
    text = data.decode("utf-16-le", errors="ignore")
    # Strings are length-prefixed; pull the printable runs.
    runs = re.findall(r"[ -~]{3,}", text)
    info: dict[str, str | None] = {"version": None, "build": None, "original_path": None}
    for run in runs:
        run = run.strip()
        if re.fullmatch(r"20\d\d", run) and info["version"] is None:
            info["version"] = run
        elif re.match(r"20\d{6}_\d+\(x64\)", run):
            info["build"] = re.match(r"20\d{6}_\d+\(x64\)", run).group(0)
        elif run.startswith("C:\\") or run.startswith("Z:"):
            info["original_path"] = run
    return info


def extract_preview(data: bytes) -> bytes | None:
    """Phase 2: RevitPreview4.0 = wrapper (magic 62 19 22 05) + PNG."""
    if not data.startswith(PREVIEW_WRAPPER_MAGIC):
        return None
    at = data.find(PNG_MAGIC)
    if at < 0:
        return None
    png = data[at:]
    if len(png) < 8 or png[:8] != PNG_MAGIC:
        return None
    return png


def parse_part_atom(data: bytes) -> dict:
    """Phase 2: PartAtom is plain Atom XML (family title, id, ...)."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out: dict[str, str] = {}
    for tag in ("title", "id", "updated"):
        el = root.find(f"a:{tag}", ns)
        if el is not None and el.text:
            out[tag] = el.text.strip()
    return out


def schema_class_names(data: bytes, limit: int = 12) -> tuple[int, list[str]]:
    """Phase 2: harvest ASCII class names from decompressed Formats/Latest.

    Returns (distinct_count, sample). This is the embedded type dictionary,
    not decoded element instances (see module docstring).
    """
    names = sorted(set(re.findall(rb"[A-Z][A-Za-z0-9_]{2,40}", data)))
    decoded = [n.decode("ascii") for n in names]
    return len(decoded), decoded[:limit]


def probe(path: str | Path) -> ProbeResult:
    """Run the full static probe. Never executes anything; reads bytes only."""
    import olefile  # noqa: F401  (checked for a clear error if missing)

    path = str(path)
    ole = _open_ole(path)
    res = ProbeResult(path=path, is_revit_container=True)

    names = ["/".join(e) for e in ole.listdir(streams=True)]
    for name in sorted(names):
        res.streams.append({"name": name, "size": ole.get_size(name.split("/"))})

    def read(name: str) -> bytes | None:
        try:
            return ole.openstream(name).read()
        except OSError:
            return None

    basic = read("BasicFileInfo")
    if basic:
        info = parse_basic_file_info(basic)
        res.version, res.build, res.original_path = (
            info["version"], info["build"], info["original_path"],
        )
    else:
        res.notes.append("BasicFileInfo stream missing; cannot determine version.")

    preview = read("RevitPreview4.0")
    if preview:
        res.preview_png = extract_preview(preview)
        if res.preview_png is None:
            res.notes.append("RevitPreview4.0 present but PNG not found after wrapper.")

    part_atom = read("PartAtom")
    if part_atom:
        res.part_atom = parse_part_atom(part_atom)

    formats = read("Formats/Latest")
    if formats:
        try:
            dec = decompress_stream(formats, "Formats/Latest")
            res.schema_classes, res.schema_sample = schema_class_names(dec)
        except ValueError as e:
            res.notes.append(f"Formats/Latest decompression failed: {e}")

    if res.version and res.version.isdigit():
        expected = PARTITION_INDEX.get(int(res.version))
        want = f"Partitions/{expected}" if expected else None
        if want and want not in names:
            res.notes.append(f"Expected {want} for Revit {res.version} not found.")
        elif want:
            res.notes.append(f"Release bulk-data stream {want} present as expected.")

    res.notes.append(
        "Element geometry is NOT extracted: Partitions/* wire envelope "
        "is unverified (see README capability matrix)."
    )
    ole.close()
    return res
