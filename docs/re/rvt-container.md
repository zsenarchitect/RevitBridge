# RVT container reverse-engineering notes

Method: static-only (bytes in, claims out). Witness: `racbasicsamplefamily-2024.rfa`
(Autodesk-distributed, CC BY-NC-SA; SHA-256 `fe9ffd26cec4fa66…`, 397312 bytes).
Sample never committed; smoke test reads it from `/tmp` and skips if absent.

## Layer 1 — Container: OLE2 Compound Document (public MS-CFB)

- Magic `D0 CF 11 E0 A1 B1 1A E1` at offset 0. Opens with `olefile`.
- 13 streams enumerable, total 397312 bytes — matches the independent rvt-rs
  report for the same file byte-for-byte (cross-witness #1).

## Layer 2 — Compression: truncated gzip (PROVEN)

- Stream layout: `[8-byte Revit framing | Global/* only][10-byte gzip header][raw DEFLATE]`.
- No trailing CRC/ISIZE — `zlib.decompress(body[10:], -15)` after skipping the
  10-byte header. Verified on `Formats/Latest` (156854 → 473249 bytes).

## Layer 3 — Records (PROVEN, metadata only)

| Stream | Encoding | Yields |
|---|---|---|
| `BasicFileInfo` | UTF-16LE text | version `2024`, build `20230308_1635(x64)`, original path |
| `RevitPreview4.0` | wrapper magic `62 19 22 05`, then PNG at offset 302 | valid 128×128 RGBA PNG (1133 bytes) |
| `PartAtom` | Atom XML | title, id, updated |
| `Formats/Latest` | decompressed ASCII | 10,973 distinct class names (embedded schema) |
| `Partitions/67` | — | release bulk-data stream; 2024 → 67 per the 2016–2026 index map |

## Layer 4 — Element geometry (UNVERIFIED)

- `Partitions/*` wire envelope not reverse-engineered here. The schema-directed
  scanners in public RE efforts hit only document-level classes on real files.
- Status stays UNVERIFIED until two independent witnesses agree on decoded
  elements from a real file. Do not promote it.

## What this means for the converter

RVT geometry is only reachable through Autodesk tooling (local Revit API or
APS Design Automation). The probe gives us everything short of geometry —
enough to identify, inventory, and thumbnail any Revit file with zero
Autodesk software installed.
