# RVT container: finding ledger

Method: static-only (bytes in, claims out). Each row states the conclusion,
the byte evidence, its confidence, what was examined, and what remains unknown.
Per-conclusion vocabulary: **observation** (bytes seen), **inference** (best
reading), **unknown** (explicitly not established).

Witness: `racbasicsamplefamily-2024.rfa` (Autodesk-distributed, CC BY-NC-SA;
397312 bytes). Sample never committed; smoke test reads it from `/tmp` and
skips if absent. Cross-witnessed against the independent rvt-rs / phi-ag RE
writeups.

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| 1 | Container is OLE2 Compound Document (public MS-CFB) | Magic `D0 CF 11 E0 A1 B1 1A E1` at offset 0; `olefile` enumerates 13 streams, 397312 bytes total — byte-identical to the independent rvt-rs report for the same file | **proven** (observation) | Full container parse of the 2024 sample | — |
| 2 | Streams use truncated gzip (10-byte header + raw DEFLATE, no CRC/ISIZE); `Global/*` prepend an 8-byte framing header | `Formats/Latest` head `1f 8b 08…`; `zlib.decompress(body[10:], -15)` yields 473249 bytes of ASCII schema | **proven** (observation) | `Formats/Latest` + spot checks on `Global/*` | Exact semantics of the 8-byte header fields |
| 3 | `BasicFileInfo` is UTF-16LE text giving version, build, original path | Decoded runs: `2024`, `20230308_1635(x64)`, `C:\Users\…\racbasicsamplefamily.rfa` | **proven** (observation) | Whole stream | Older (pre-2019) `BasicFileInfo` layout variants |
| 4 | `RevitPreview4.0` holds a PNG after a wrapper headed by magic `62 19 22 05` | PNG magic at offset 302; extracted bytes are a valid 128×128 RGBA PNG (1133 bytes) | **proven** (observation) | Whole stream | Wrapper field semantics beyond the magic |
| 5 | `PartAtom` is Atom XML with family metadata | Parses as XML: title `racbasicsamplefamily`, id, updated timestamp | **proven** (observation) | Whole stream | — |
| 6 | `Formats/Latest` is the embedded class schema (type dictionary) | 10,973 distinct ASCII class names harvested from the decompressed stream | **proven** (observation); the *decoding* of instance data from it is an **inference** at best | ASCII token harvest, not record parsing | Tagged record framing semantics |
| 7 | Release bulk-data stream is `Partitions/67` for Revit 2024 | Stream present; index matches the published 2016→2026 map (58, 60, 62, … 69) | **proven** (observation, cross-witnessed) | Stream inventory | Contents of the stream |
| 8 | Element geometry is extractable without Autodesk | — | **unknown** (explicitly not established) | — | The `Partitions/*` wire envelope is unverified by every public effort to date |

## What this means for the converter

RVT geometry is only reachable through Autodesk tooling (local Revit API or
APS Design Automation). The probe gives us everything short of geometry —
enough to identify, inventory, and thumbnail any Revit file with zero
Autodesk software installed. Row 8 stays **unknown** until two independent
witnesses agree on decoded elements from a real file; it is not promoted on
optimism.
