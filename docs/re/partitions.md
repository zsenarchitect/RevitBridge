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

**Correction (2026-11-04, same day — read before trusting P3):** the
first version of this ledger claimed members share one deflate window
(P3, "proven"). That was WRONG. The real mechanism is page-checksum
stripping (P0): two members' deflate spans cross stored-page checksum
regions, and decoding them without stripping silently produces wrong
bytes (inflate success is not correctness). The corrected decode
reproduces rvt-rs's `rvt-dump` output byte-for-byte (1145136 B).
Findings in the chain region (members 0–2) and members 0–4, 6–8 are
unaffected — they are byte-identical either way. Post-chain counts were
recomputed on the corrected bytes (R5, R6).

## Layer 1 — partition stream framing (proven on this file)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| P0 | Stored `Partitions/*` streams are checksum-paged: strip before inflate | Stored page = 65249 B = 64896 payload + 353 checksum. This stream: 2 full pages + 1159 remainder; stripped size 130951 B. After stripping, all 10 members inflate standalone and the concatenation matches rvt-rs's `rvt-dump` output byte-for-byte (1145136 B) | **proven** (observation, cross-witnessed) | Whole `Partitions/67` | — |
| P1 | A `Partitions/N` stream is: 44-byte stream header, then gzip members separated by 40-byte gaps | Raw `Partitions/67` (131657 B): gzip magics at 44, 12398, 19074, 21706, 41630, 62355, 79008, 94062, 109009, 118013; every inter-member gap is exactly 40 B | **proven** (observation) | `Partitions/67` of the 2024 sample, all 10 members | Whether other partitions/versions share the 44/40 sizes |
| P2 | Each 40-byte gap = 8-byte gzip trailer (CRC32 + ISIZE) + 32-byte chunk header | Gap after member0: `83 fe 41 9f` + `a7 ff 01 00` = ISIZE 130983 = member0's decompressed size exactly; same check holds for members 1–4 | **proven** (observation) | Gaps after members 0–4 | — |
| P3 | ~~Members share one deflate window~~ — REFUTED | Member5's standalone failure was checksum bytes (raw 64896..65249) inside its deflate span, not a shared window. Stripped member5 inflates standalone to 130945 B (not 134478 B); stripped member9 to 82683 B (not 84639 B). The chained-dict decode was wrong by 5489 B total, silently | **refuted** (observation) | Members 5 and 9 | — |
| P4 | The 32-byte chunk header has stable + chaining fields | Every header: u16 `3701`, u32 `265852`, trailing u64 `101`/`102`; header(n+1).field_b == header(n).field_f across 4 consecutive pairs (12330→6652→2608→19804→20669) | **proven** (observation); semantics **inference** at best | 5 chunk headers | What the fields mean (offsets? ids? counters?) |

## Layer 2 — the RE-35 record wrapper (confirmed on a family file)

rvt-rs's RE-35 (2026-09-23) defines the record as: `u64 ElementId`,
`u32 size (header included)`, `u16 prologue constant (release + 28)`,
`u16 count`, body, then a 16-byte trailer (`u64 unread`, `u32 flag`,
`u32 size again`); the next record starts right after the trailer.

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| R1 | The wrapper holds on a 2024 **family** file, not just projects | Chain walk from offset 0 of decompressed `Partitions/67`: **1975 records**, every one with prologue constant `0x059f` (the 2024 value) and trailer echoing its size; walk stops exactly where the first invalid header appears (offset 314095, 27.4% of the stream) | **proven** (observation) | Decompressed `Partitions/67` (1145136 B) | Whether other family files / versions walk the same way |
| R2 | The stream header independently declares the record count | 44-byte stream header, u16 at offset 14 = **1975** = the walked record count | **proven** (observation, second witness for R1) | Stream header bytes 0–44 | Other header fields (u64@0 = 9, u32@8 = 891) uninterpreted |
| R3 | Record ids are sequential element ids with small gaps | ids run 7247 (rec0), then 0, 1, 3, 4, 5, … (gaps at 2, 13, 16, 20, …); all 1975 unique | **proven** (observation) | The 1975 chain records | Why rec0 is 7247 (document-level record?); what the gaps are |
| R4 | After the chain, a different region begins | Bytes at 314095 start with `FF×8` + zero words — the same marker shape as `Global/ElemTable` rows, not a record header | **proven** (observation) | 64 bytes at the chain end | What the post-chain region is (see R5–R7) |
| R5 | The post-chain region holds NO further RE-35 chains | Signature scan over all 831041 post-chain bytes (const `0x059f` at +12 + trailer echo): **0 hits** | **proven** (observation) | Whole post-chain region | — |
| R6 | The post-chain region is string/parameter metadata, not element records | **5341** UTF-16LE strings ≥3 chars, opening with a hierarchical code tree (`A`, `A10`, `A20`, `A1010`, `A1020`, `A1030`, `A2010`, … `A1010100`, …); **795** hits of a tagged-string pattern (`e9 02` + u32 char-count + UTF-16LE); later strings include `Standard`, `Path`, `PathType`, `Absolute`, and GUID `cf823dbb-21d2-42e0-a39c-1cb523a8cec2` | **proven** (observation); "metadata section" is an **inference** from the content | Whole post-chain region | What the `e9 02` tag denotes; what the A-code tree names (type tree? parameter tree?) |
| R7 | The post-chain region opens by referencing the chain's first record | First 24 bytes: `FF×8`, u64 `0`, u64 `7247` (= rec0's id) | **proven** (observation); linkage is **unproven** | 24 bytes at 314095 | Whether this is an index, a back-pointer, or coincidence |

## Layer 3 — neighboring streams (observations)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| S1 | `Global/PartitionTable` (167 B decompressed) carries a UTF-16LE name | Contains `Family : Section Heads: Section Tail - Upgrade` plus a GUID-shaped blob and an `FF×8` marker | **proven** (observation) | Whole stream | What the name denotes (template? section?) |
| S2 | `Global/ElemTable` (79606 B decompressed) header holds 1975; layout now resolved by rvt-elem-table | First bytes: u16 `1411`, u16 `1975`, then zeros; rvt-elem-table: 6-byte header, 40-byte stride, 8-byte owner field at record +28, 1975/1975 records parsed, ids matching this ledger's chain | **proven** (observation, cross-witnessed) | Whole stream | `1411` is a per-release constant, not a count (rvt-elem-table) |
| S3 | Record bodies contain FF-sentinel fields | Example rec4 (id 4, 111-byte body): `00 00`, `FF×8`, `11 00…`, `FF×8` runs, scattered small ints | **proven** (observation) | One record body | Class-specific body decoding is the open frontier (rvt-rs has 300+ per-class reports; not re-derived here) |

## Layer 4 — record bodies (2026-11-04, corrected and extended)

All findings in this layer sit in the chain region (members 0–2),
which is byte-identical between the naive and page-stripped decodes,
so the P3 correction does not touch them. Byte offsets are body-relative
(body = record minus its 16-byte header).

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| B1 | One dominant record kind: 1313/1975 records are 127 bytes; their bodies vary at exactly 16 positions: +2, +3, +4, +10, +11, +50, +51, +54, +55, +57, +58, +59, +74, +75, +82, +83 | Full-body census across all 1313 (earlier "48-byte identical prefix" claim corrected: +2/+3/+4 vary in 12 records) | **proven** (observation) | Chain records | Meanings of most fields (below) |
| B2 | Body+10 (u16) = the record's ElemTable owner, defaulting to 17 when owner-less | Matches ElemTable owner for 1304/1313; the 9 mismatches are exactly the owner-less records (7247, 7650, 7487, 6444, 7170, …), all carrying 17 | **proven** (observation) | Chain records | — |
| B3 | Body+74/+82 (u16 pair) is (owner-group, own id) for 1306 records, but SWAPPED to (own id, 17) for exactly rec4–rec10 | u16 census: (17, own) ×1294, (5701, own) ×12, (own, 17) ×7. Earlier "13 records" count was byte-aliasing (ids ending in 0x11, e.g. 4113, mimic +74 = 17 at byte level) | **proven** (observation); meaning **unknown** | Chain records | Why the earliest 127-records swap the pair (definition records? container inversion?) |
| B4 | The +50/+54/+55/+57/+58-59 region is flags + a code, with coherent subgroups | +50/+51: 0x8000 base, 0x8020 in 27 records; +54: 30 (691) / 14 (595) / 26 / 10; +55: 0x20 set in 1287, clear in 26; +57: 4 in 1254, 0 in 59; +58-59: 2157 in 1203, 393 in exactly the 27 +50=32 records, rare codes in the +55=0 / +57=0 records. NONE of the +58-59 values exists as a record id (checked) | **proven** (observation); code meaning **unknown** | Chain records | What the code denotes (class? style? category?); needs a second file or a class-id map to resolve |
| B5 | Body+2/+3/+4 is an FF sentinel with a 12-record override set | 1301 records carry FF FF FF; 12 carry values (5499, 5500, 5660, 5784, 5785, 5838, 6084, 6195, 6513, 6935, 7131, 6364). Only 3 of the 12 are 69-group members, so it is NOT a group marker | **proven** (observation); meaning **unknown** | Chain records | What the override values are |
| B6 | Record 17 (15047 B, owner-less) is a sorted element-id index, NOT a parameter table | 90-byte header, then a u64 array on a fixed grid (1867 slots: 1865 genuine ids + 2 zero padding). The array = all 1975 element ids ascending EXCEPT the 110-id 5701-subtree (5702–5714, 5719–5728, 5733–5737, 5740–5749, 5752–5754, 5777–5782, 5784–5788, 5790–5794, 5809–5838, 6100–6113, 7171–7178, 7200). 7247 sits at its sorted position, not the chain head | **proven** (observation) | Record 17 only | Header values (26, 1872) uninterpreted; where the 5701-subtree is indexed (5701's own 1023-byte body is the prime suspect) |
| B7 | Record 17's "repeated 2.0f32 values" and "trailing id list" are phantoms of the index array | All 9 f32 2.0 hits sit at array-grid+5 where an id with low byte 0x40 (64, 4160, 5184, 5696, 6208, 6464, 6976, 7232, 7488) follows another id — byte-pattern coincidence, not markers. The "consecutive tail" (7647–7655) is just the sorted array's end | **proven** (observation); corrects the earlier B2 reading | Record 17 only | — |
| B8 | The f64-class records carry a fixed 2.0f64 dimension field at +75 plus an id-slot list | 11 records, exact f64 equality at +75 in all; slots start at +90 with stride 8 = [u16 id][6 zeros]; body+70 = slot count + 2 in 11/11 (0 slots → 2) | **proven** (observation) | 11 records | What the 2.0 dimension is; what +70's "+2" counts |
| B9 | Slot lists enumerate the record's ElemTable subtree (self + descendants, DFS pre-order), with two exceptions | rec5615: [self, 5616, 5618, 5619, 5623] = exactly its owned children + self; rec65: [self, 4103]; rec5137: [self]; rec6209: [self]; rec64: [65, 4103, 5137] = descendants WITHOUT self; rec6096: [6090, self] where 6090 is a sibling owned by 17, relation unknown | **proven** (observation); grouping semantics **inference** | 11 records + ElemTable | The 6090 relation; why rec64 omits self |
| B10 | Two slot-region fields stay open: body+83 and rec5615's terminator | +83: 0 in 4 slot-records, 16/20/22/24/25/27/29 in the other 7 — NOT a sibling index (tested against chain-order sibling positions: 119, 317, 351, 0, 737, 1012, 1477 — all mismatch). rec5615 alone appends `01 00 00 00` + `fe ff ff ff ff ff ff ff` after its 5 slots | **proven** (observation); meanings **unknown** | 11 records | Both need a second file to resolve |
| B11 | Units in record bodies are feet, not meters | Meter values 0.61/0.915/0.16/0.762: zero hits in f32 and f64 across the whole decompressed stream; 2.0/2.5/3.0 ft values present | **proven** (negative search) | Whole decompressed stream | — |
| B12 | Family type names live in the post-chain region, not the chain | UTF-16LE `0610 x 0160mm` @444516, `0762 x 0762mm` @444782, `0610 x 0915mm` @445048 (member4, byte-identical in both decodes) | **proven** (observation) | Post-chain region | — |

Schema landscape (rvt-schema, same sample): 4126 classes, 11562 fields;
top class `FamilyBase` (105 fields: `m_familyParams`,
`m_trivialParamIds`, `m_name`, `m_path`, `m_famCatalogKeys`,
`m_pFamilyTypes`, …). Different measure from rvt-info's 8575 inferred
names; neither maps record kinds to class names yet.

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
| ElemTable | 6-byte header (`1411`, `1975`, then zeros), 40-byte stride, 8-byte owner field at record +28, **1975/1975 records parsed** | Record ids match this ledger's chain exactly, **including** rec0 `7247` (earlier "minus rec0" wording corrected — the id sets are equal). Note: rvt-elem-table's `header_flag` (`0x0011`) is read at stream offset `0x22` (the first entry's owner slot), NOT from the header bytes, which are zero there | Chain confirmed by a third witness; **family ElemTable layout RESOLVED** |
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
ledger's new ground: wrapper confirmed, ElemTable layout resolved,
record-body classes open), which its
project corpus does not measure.
