# Partitions/* wire format: finding ledger

**Goal (narrow):** determine where Revit element instances live in a `.rvt`/`.rfa`
file and what framing they use — not full geometry decoding.

**Prior art (read first, per skill rule 4):**
[rvt-rs](https://github.com/DrunkOnJava/rvt-rs) (Apache-2.0, clean-room) is
the furthest public effort. As of this writing it recovers typed elements at
~100% of Revit's own IFC export on several Revit 2024/2025 **project** files
(RE1 Architecture/Mechanical/Plumbing, Snowdon walls 1062/1078), via the
record wrapper below. Its corpus is projects; **family** files (like our
sample) are outside its measured set — which is where this ledger's new
observations come from.

**Witness:** `racbasicsamplefamily-2024.rfa` (Autodesk-distributed, CC
BY-NC-SA; 397312 bytes, SHA-256 `fe9ffd26cec4fa66…`). Never committed;
smoke analysis reads it from `/tmp`.

## Layer 1 — partition stream framing (proven on this file)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| P1 | A `Partitions/N` stream is: 44-byte stream header, then gzip members separated by 40-byte gaps | Raw `Partitions/67` (131657 B): gzip magics at 44, 12398, 19074, 21706, 41630, 62355, 79008, 94062, 109009, 118013; every inter-member gap is exactly 40 B | **proven** (observation) | `Partitions/67` of the 2024 sample, all 10 members | Whether other partitions/versions share the 44/40 sizes |
| P2 | Each 40-byte gap = 8-byte gzip trailer (CRC32 + ISIZE) + 32-byte chunk header | Gap after member0: `83 fe 41 9f` + `a7 ff 01 00` = ISIZE 130983 = member0's decompressed size exactly; same check holds for members 1–4 | **proven** (observation) | Gaps after members 0–4 | — |
| P3 | Members share one deflate window: later members need the previous output tail as dictionary | Members 0–4 inflate standalone; member5+ fail with "invalid distance too far back" until inflated with `zdict` = previous output's last 32 KB; then all 10 decode (total 1150625 B) | **proven** (observation) | All 10 members of `Partitions/67` | Whether the window reset rule is per-member or per-stream |
| P4 | The 32-byte chunk header has stable + chaining fields | Every header: u16 `3701`, u32 `265852`, trailing u64 `101`/`102`; header(n+1).field_b == header(n).field_f across 4 consecutive pairs (12330→6652→2608→19804→20669) | **proven** (observation); semantics **inference** at best | 5 chunk headers | What the fields mean (offsets? ids? counters?) |

## Layer 2 — the RE-35 record wrapper (confirmed on a family file)

rvt-rs's RE-35 (2026-09-23) defines the record as: `u64 ElementId`,
`u32 size (header included)`, `u16 prologue constant (release + 28)`,
`u16 count`, body, then a 16-byte trailer (`u64 unread`, `u32 flag`,
`u32 size again`); the next record starts right after the trailer.

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| R1 | The wrapper holds on a 2024 **family** file, not just projects | Chain walk from offset 0 of decompressed `Partitions/67`: **1975 records**, every one with prologue constant `0x059f` (the 2024 value) and trailer echoing its size; walk stops exactly where the first invalid header appears (offset 314095, 27.3% of the stream) | **proven** (observation) | Decompressed `Partitions/67` (1150625 B) | Whether other family files / versions walk the same way |
| R2 | The stream header independently declares the record count | 44-byte stream header, u16 at offset 14 = **1975** = the walked record count | **proven** (observation, second witness for R1) | Stream header bytes 0–44 | Other header fields (u64@0 = 9, u32@8 = 891) uninterpreted |
| R3 | Record ids are sequential element ids with small gaps | ids run 7247 (rec0), then 0, 1, 3, 4, 5, … (gaps at 2, 13, 16, 20, …); all 1975 unique | **proven** (observation) | The 1975 chain records | Why rec0 is 7247 (document-level record?); what the gaps are |
| R4 | After the chain, a different region begins | Bytes at 314095 start with `FF×8` + zero words — the same marker shape as `Global/ElemTable` rows, not a record header | **proven** (observation) | 64 bytes at the chain end | What the post-chain region is (see R5–R7) |
| R5 | The post-chain region holds NO further RE-35 chains | Signature scan over all 836530 post-chain bytes (const `0x059f` at +12 + trailer echo): **0 hits** | **proven** (observation) | Whole post-chain region | — |
| R6 | The post-chain region is string/parameter metadata, not element records | **5129** UTF-16LE strings ≥3 chars, opening with a hierarchical code tree (`A`, `A10`, `A20`, `A1010`, `A1020`, `A1030`, `A2010`, … `A1010100`, …); **795** hits of a tagged-string pattern (`e9 02` + u32 char-count + UTF-16LE); later strings include `Standard`, `Path`, `PathType`, `Absolute`, and GUID `b6305212-4915-4526-b659-be2d6f97174f` | **proven** (observation); "metadata section" is an **inference** from the content | Whole post-chain region | What the `e9 02` tag denotes; what the A-code tree names (type tree? parameter tree?) |
| R7 | The post-chain region opens by referencing the chain's first record | First 24 bytes: `FF×8`, u64 `0`, u64 `7247` (= rec0's id) | **proven** (observation); linkage is **unproven** | 24 bytes at 314095 | Whether this is an index, a back-pointer, or coincidence |

## Layer 3 — neighboring streams (observations)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| S1 | `Global/PartitionTable` (167 B decompressed) carries a UTF-16LE name | Contains `Family : Section Heads: Section Tail - Upgrade` plus a GUID-shaped blob and an `FF×8` marker | **proven** (observation) | Whole stream | What the name denotes (template? section?) |
| S2 | `Global/ElemTable` (79606 B decompressed) header holds 1975; layout now resolved by rvt-elem-table | First bytes: u16 `1411`, u16 `1975`, then zeros; rvt-elem-table: 6-byte header, 40-byte stride, 8-byte owner field at record +28, 1975/1975 records parsed, ids matching this ledger's chain | **proven** (observation, cross-witnessed) | Whole stream | `1411` is a per-release constant, not a count (rvt-elem-table) |
| S3 | Record bodies contain FF-sentinel fields | Example rec4 (id 4, 111-byte body): `00 00`, `FF×8`, `11 00…`, `FF×8` runs, scattered small ints | **proven** (observation) | One record body | Class-specific body decoding is the open frontier (rvt-rs has 300+ per-class reports; not re-derived here) |

## What this means (and does not mean)

- **Means:** the "Partitions wire envelope" question is answered at the
  framing layer: we can now enumerate every element record in a 2024 family
  file (id + size + location) without Revit. That is new, independently
  verified, and narrower than "geometry extraction".
- **Does NOT mean:** geometry is extractable. Record bodies are still
  class-specific byte runs; decoding them is months of per-class work that
  rvt-rs has already done for projects. The honest next question is
  strategic, not technical (below).

## Validation — rvt-rs v0.14.0 on this sample (2026-11-04)

Built from a shallow HEAD clone under Rust 1.99.1. `rvt-info`,
`rvt-elem-table`, `rvt-elements`, `rvt-gltf` built and ran;
`rvt-ifc` failed once with E0599 (`with_family_extrusions` not found)
even though the method exists in source (`export_pipeline.rs:130`) —
a rebuild later succeeded with no code change (only the bin file's
mtime touched), confirming the first failure was transient. Its result
is in the table and confirms `rvt-gltf`.

| Check | rvt-rs result | Against our work | Verdict |
|---|---|---|---|
| version / build / streams | 2024, `20230308_1635(x64)`, 13 streams, same list, `Partitions/67` | Exact match with our probe | Cross-witnessed |
| metadata depth | File GUID, original path, title, last saved, save counter 68, PartAtom (3 table types, omniclass) | Beyond our probe | rvt-info goes further |
| schema class count | 8575 inferred class names | Our 10,973 = distinct ASCII tokens harvested, a different method | Not reconciled; not a contradiction |
| ElemTable | 6-byte header (`1411`, `1975`, flag `0x0011`), 40-byte stride, 8-byte owner field at record +28, **1975/1975 records parsed** | Record ids match this ledger's chain exactly (minus rec0 `7247`) | Chain confirmed by a third witness; **family ElemTable layout RESOLVED** |
| `1411` | "A per-release constant, not a count" (rvt-elem-table's own words) | — | Corrects the RE-01-era "1411 elements" reading |
| typed elements | 24, all `Material` | — | Thin on families |
| glTF export | 5292 bytes, **0 meshes**, 24 materials, 1 node; identical with and without `--saved-meshes` | — | **No family geometry recovered** |
| IFC export | 8790 bytes, scaffold-only (readiness 0.35), warning "no validated building elements were exported"; project/site/building scaffold + 24 materials, zero geometric entities; diagnostics: 24 production walker elements (all Material), 0 proxy candidates | — | Confirms glTF: no family geometry |

## Revised strategic conclusion (replaces the note above)

rvt-rs's project-file strength does **not** transfer to family files on
this sample: the record chain parses fully, but typed extraction yields
only materials and geometry export yields nothing. For RevitBridge this
means: rvt-rs remains a candidate backend for **project** RVT→IFC
(its 100%-recall corpus claims are its own and were **not**
independently verified here — no project file was in this session), but
it does **not** subsume our family-first direction. Family geometry
stays open work, and family-file coverage remains this project's
genuine contribution area.

## Strategic note (inference, for Peter)

RevitBridge should **evaluate rvt-rs as an RVT→IFC backend** (Apache-2.0 is
compatible with our MIT core; attribution required) instead of re-deriving
its 300+ class reports. Verification bar before adopting: run its `rvt-info`
/ `rvt-ifc` on our fixtures and on a real project file, and diff its IFC
against Revit's own export — the same cross-witness bar rvt-rs uses.
Our independent contribution would be **family-file coverage** (this
ledger's new ground: wrapper confirmed, ElemTable layout open), which its
project corpus does not measure.
