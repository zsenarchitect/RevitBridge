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

## Layer 14 — parameter definitions found; type values stable across versions (2026-11-05, goal finish-all-revitbridge-research)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| L1 | The post-chain region contains parameter definitions: [group "parameter.group:dimensions-1.0.0"][u32 name-len][name][u32 65][ForgeTypeId "revit.local.family:<guid>"] | Height (582275), Width (582731), Length (587087) all sit in that structure; each has a distinct ForgeTypeId GUID (Height/Width share the `12e67…` stem, Length uses `4c055…`). "Thickness" hits exist too; "Depth" has none | **proven** (observation) | Post-chain region | The full parameter list (6 per type) and each definition's record framing |
| L2 | The type-record f64 values are version-stable: 2023 has the identical values at its own offsets | 2023 type records are 218 bytes (vs 266), spacing 218; f64s at +10/+70 = [762, 610, 762] mm and +198 = [762, 457, 762] mm — byte-identical values to 2024. The "inversion" (610-long types carry 762; 762-long type carries 610/457) is systematic, not a misread | **proven** (observation, two files) | 3 type records, both files | — |
| L3 | The values are round inches: 762 = 30″, 610 = 24″, 457 = 18″ | 762/610/457 mm are exactly 30/24/18 inches; the type names are likewise round (610 = 24″, 762 = 30″, 915 = 36″). +242 = [30″, 18″, 30″] reads like a height (30″ dining vs 18″ side-table), +14 = [30″, 24″, 30″] like a length — but both are inverted against the names | **proven** (observation); slot readings **inference** | 3 type records | Which slot is which parameter, and why the values run opposite to the names — needs the parameter-definition → element → slot link (the type records' u32 refs 5446/5447/5264/4253/4209, codes 3009/2607, are the candidates) |

Still open: B4 code meaning; B5/D6 override meaning; D7 nature; E5 rec51; the parameter-slot mapping (L3); the post-chain binary record framing (J3) beyond the type records and parameter definitions; 2023 second-list layout; 2025+ framing (Partitions/68).

## Layer 13 — type records decoded (2026-11-05, goal finish-all-revitbridge-research)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| K1 | The 3 type records are fixed 266-byte records in the post-chain region, spaced exactly 266 apart, with the structure [f64 @+14 and @+90, identical][element refs][u32 13][UTF-16LE name][u32 6 = param count][FF sentinels][f64 @+242] | Exactly 3 mm-names in the whole post-chain region; the three 266-byte windows differ at only 25 byte positions (the name digits + 3 numeric fields). The dictionary block is contiguous: 794 entries, +170 to +19996, zero gaps | **proven** (observation) | Post-chain region | The record's exact field boundaries outside the name/values |
| K2 | The f64 values are exact mm→ft conversions — but they do NOT match the type's own name dimensions in the naive way | +14/+90 = [762, 610, 762] mm; +242 = [762, 457, 762] mm (2.5, 2.001312335958005, 1.4993438320209973 ft — exact to the last bit). The 610-long types (0610×0160, 0610×0915) carry 762; the 762-long type (0762×0762) carries 610 and 457. 457 mm is none of the name dimensions | **proven** (observation) | 3 type records | Which parameter each f64 slot is — the mapping needs the parameter definitions. The record's u32 refs (5446, 5447, 5264, 4253, 4209 — all chain records, owner 17, codes 3009/2607; 3908 is not in the chain) may be the parameter definitions |
| K3 | The type records' numeric fields are real parameter values, not noise | Exact mm→ft conversions (610.0, 762.0, 457.0 mm) rule out coincidence; the two identical slots (+14, +90) suggest a [default, current] or [min, max] pair | **proven** (observation); pair reading **inference** | 3 type records | — |

Still open: B4 code meaning; B5/D6 override meaning; D7 nature; E5 rec51; the parameter-slot mapping (K2); the post-chain binary record framing (J3) beyond the type records; 2023 second-list layout; 2025+ framing (Partitions/68).

## Layer 12 — post-chain region structure (2026-11-05, goal finish-all-revitbridge-research)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| J1 | The post-chain region opens with a 7247-tagged structure (the document id appears twice as u64, with 17 nearby) — possibly a chain trailer | Head bytes: FF×8, zeros, `4f 1c…` (= 7247), `cf 01…`, zeros, `d3 02 01 00`, 7247 again, FF×8, `11 00` (= 17) | **proven** (observation); "trailer" **inference** | Post-chain head (314095) | What the `04 2f d8 43` / `cf 01` / `d3 02` fields are |
| J2 | The tagged strings are a code dictionary: [e9 02][u32 char-count][UTF-16LE][ff ff ff ff], 795 entries, hierarchical (A, A10, A20, A1010, A1020, A1030…) | First entries decode cleanly: count 1 "A", count 3 "A10", count 3 "A20", count 5 "A1010"… each followed by 4× FF | **proven** (observation) | Post-chain region | Whether the dictionary is Omniclass codes (matches PartAtom's omniclass 23.40.20.14.17 family) |
| J3 | The region mixes strings with binary parameter records; the box coordinates appear as f64s there, but the binary record framing is not yet decoded | f64 hits: 1.75 ×5, −0.75 ×6, 2.5 ×1, 1/24 ×4, 1/48 ×7. The −0.75 value repeats 4× consecutively; a different 8-byte pattern (`ea 8c a0 39 59 3e 29 46`) repeats 5× nearby. Context bytes are packed binary (u32s, sentinels, doubles), not text | **proven** (observation) | Post-chain region | The binary record framing — the remaining curve-hunt work |
| J4 | E5 note: rec51's wild f64s (9.3857, −27.8013, 61.4571, 8.1397, 46.9665) are version-stable but still unexplained | Identical values in 2023 (offsets −24) and 2024. As feet they sit far outside the family (61 ft); as mm (9.4, −27.8, 61.5, 8.1, 47.0) they fit inside the 610×915 mm table; as degrees they are plausible angles. No structural evidence picks one | **proven** (observation, two files); unit **unknown** | Record 51, both files | What rec51 is |

Still open: B4 code meaning; B5/D6 override meaning; D7 nature; E5 rec51 (see J4); decoding the post-chain binary record structure (J3) — the curve hunt's next step; 2023 second-list layout; 2025+ framing (Partitions/68).

## Layer 11 — second lists, 6090/6096 direction, curve lead (2026-11-05, goal finish-all-revitbridge-research)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| I1 | D2 RESOLVED: second list = [type] (count2=1) or [related-element, type] (count2=2); the LAST entry is always the type | Type-like records are count2=0 and referenced by others: 5714 (135, ref'd ×3), 5865 (135, ×1), 6153 (135, ×1), 612 (143, ×12) — each is the last entry of a 2-entry second list ([5713, 5714], [5864, 5865], [819, 6153], [85/86/87/88, 612]). rec21's "exception" is not one: types chain — 1716/6830/6831 → 21 → 5602 (rec21 is both a type, ref'd ×3, and typed by 5602) | **proven** (observation) | Second lists, 2024 file | What the first entry (related element) means — a second type, a parent, a profile? |
| I2 | D7 direction established: 6096 references 6090, not vice versa | 6090 is in 6096's list in both versions (2024 [17, 64, 6090, 6096]; 2023 [4, 17, 64, 6090]); 6090's own list is just [scope, self]. They share a 54-byte body prefix, diverging at the enum (30 vs 26) and code (696 vs 1105) | **proven** (observation, two files) | Records 6090/6096, both files | Base/instance vs predecessor/successor |
| I3 | Curve lead: the post-chain region holds binary parameter records containing the box coordinates as f64s | 8-aligned f64 hits in the post-chain region: 1.75 ×5, −0.75 ×6, 2.5 ×1, 1/24 ×4, 1/48 ×7. The −0.75 value repeats 4× consecutively (a vertex table sharing the sketch's bottom edge?). Global/Latest has zero f64 hits. The region is strings + binary parameter values, not strings alone | **proven** (observation); "vertex table" **inference** | Post-chain region, Global/Latest | The post-chain binary record structure — the next decode target |
| I4 | 2023 lists start [X, 17, self, …] where X is a small even per-record value (2, 4, 6…) | rec6090 X=2, rec6096 X=4, rec11 X=6, rec4 X=2 (swapped: [2, self, 17]) | **proven** (observation) | 2023 chain | What X means |

Still open: B4 code meaning; B5/D6 override meaning; D7 nature; E5 rec51; the post-chain binary record structure (curve hunt); 2023 second-list layout; 2025+ framing (Partitions/68).

## Layer 10 — index membership, swap, and code groups resolved (2026-11-05, goal finish-all-revitbridge-research)

Corrections to Layer 5 (C1, C2): the 5701 array has **114 values**,
not 113 — the count field (114) EQUALS the value count; the "off by
one" was a miscount against slots-including-padding. And 5855 is NOT
in the 5701 array in either version, so the C1 "overlap {17, 5701,
5855}" is withdrawn (overlap is {17, 5701}).

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| H1 | 5701's array = {17, 5701} ∪ (subtree − {5855}) ∪ {0, 5852}; identical in both versions | Set-based count: 114 values both files, zero diff. Subtree(5701) via owners = 111 descendants; the array holds 110 of them (all but 5855) plus 0 and 5852 as shared refs. rec17's array = all ids − (subtree − {5855}) — verified exactly (`arr17 == all − (sub − {5855})` is True) | **proven** (observation, two files) | Both chains + ElemTables | Why 5855 is the excluded one; what 0 and 5852 are doing in 5701's array |
| H2 | C2 RESOLVED: count field = value count (114 = 114), no fencepost | Set-based counts in both versions; the Layer 5 "114 vs 115" compared the count against slots-including-padding | **proven** (observation, two files) | Records 5701, both files | — |
| H3 | 5855 is the single 5701-descendant excluded from 5701's index but included in 17's index, in both versions | Owner 5701 in both ElemTables (2023 stride-28 parse, 100% owner match semantically); in rec17's array both files; absent from rec5701's array both files. It is also the only record found with F1 (17) ≠ owner (5701), and it carries the tiny 0.5″ box + two lists | **proven** (observation, two files); "indexes are scope-based (F1), not owner-based" **inference** (one witness) | Records 5855/17/5701, both files | Why 5855 is scoped to 17; whether other scope/owner splits exist in other size classes |
| H4 | B3 RESOLVED as a group marker: the F2/F3 swap marks exactly the 1952-code group (rec4–rec10), in both versions | 2024: swapped = rec4–rec10 = the entire 7-record 1952 group. 2023: same records show list [2, self, 17] vs the normal [2, 17, self…] (rec4066: [2, 17, 4066]) | **proven** (observation, two files) | Records 4–10, both files | Why this group is inverted |
| H5 | B5 refined: the 12-record override set is identical across versions | Same 12 ids in both files (5499, 5500, 5660, 5784, 5785, 5838, 6084, 6195, 6364, 6513, 6935, 7131), all with +4=225; owners mixed {17, 5701} in both | **proven** (observation, two files) | 12 records, both files | What the override bytes mean |
| H6 | B4 refined: code groups are version-stable, but the code is NOT a class-table index — refuted on a second file | 2023 class table (4,078 classes): GenSweepGStep at 1857, ArcCurveCenterGStep at 332 — neither equals the 2023 group ids (69, 127, 99, 122) nor the 2024 codes (2157, 393). 2024: indices 1892/341 vs codes 2157/393. The partition is stable (2023 +33 high byte tracks the 2024 code 1:1 for the groups checked: 0x45↔2157, 0x7F↔393, 0x63↔2448, 0x7A↔1952) | **proven** (observation, two files); code meaning **unknown** | Both files + both schemas | Whether the code is an enum, a hash, or an index into an unfound table |
| H7 | 2023 dominant-kind body layout partially mapped | F1 (owner) at +6; flag at +26 (= 2024 +50: 0x8000 base, 0x8020 in the same 27 records); enum+flag at +30 as one u16 (= 2024 +54/+55: 0x201E/0x200E/0x201A); code-group byte at +33 (high byte); u32 list at +46 = [2, self, 17, …] (leading constant 2, vs 2024's 17) | **proven** (observation, two files) | 2023 dominant kind | Full 2023 body map (code field itself, second list) |
| H8 | The 11 new 2024 records are all dominant-kind: 10× code 2157 + rec7650 code 1309 | All size 127; rec7650's code 1309 is a rarer code not in the 2024 top-8 | **proven** (observation) | Records 7645–7655 | What rec7650 (code 1309) is |
| H9 | 2023 ElemTable: 28-byte stride, [u32 id]…[u32 owner @+24]; owners match 2024 100% semantically | 1,964 ids parsed; 1,954/1,964 match 2024 exactly and the 10 diffs are only the none-sentinel width (0xFFFFFFFF vs 0xFFFFFFFFFFFFFFFF) | **proven** (observation, two files) | Both ElemTables | — |

Still open: B4 code meaning; B5/D6 override meaning; D2 second-list 2-entry meaning + rec21 exception; D7 6090/6096 relation; E5 rec51; where the actual sketch curves live (boxes give bounds only); 2025+ framing (Partitions/68).

## Layer 9 — cross-file verification: Revit 2023 vs 2024 (2026-11-05, goal finish-all-revitbridge-research)

Second file: `racbasicsamplefamily-2023.rfa` (376,832 B, SHA-256
1cdff09b…, from phi-ag/rvt via Git LFS media URL), Partitions/66
(2023 = 66, 2024 = 67 — the partition index advances per release).
Same checksum-page strip + member inflate procedure works; 8
members, 905,111 B decompressed.

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| G1 | Record framing CHANGED between 2023 and 2024 — the parser must be version-aware | 2023: 12-byte header [u32 id][u32 size=body][u16 prologue][u16 count], step = 12+size. 2024: 16-byte header [u64 id][u32 size=total][u16 prologue][u16 count], step = size. The 2024 walk (step=size) fails on 2023 at record 1; the 12-byte walk yields a clean 1,964-record chain ending exactly at the header's candidate count | **proven** (observation, two files) | Both chains | Whether the framing changes again in 2025+ (Partitions/68 exists in phi-ag/rvt) |
| G2 | Prologue = internal version + 28, confirmed on two files | 2023: ElemTable first u16 = 1370, prologue 0x0576 = 1398 = 1370+28. 2024: 1411, prologue 0x059f = 1439 = 1411+28. ElemTable's first u16 IS the internal version | **proven** (observation, two files) | Both files | — |
| G3 | Same family, slightly evolved: 2023 id set ⊂ 2024 id set | 2023: 1,964 records; 2024: 1,975. Every 2023 id exists in 2024; 2024 adds exactly 11 records (7645–7655). Stream header's count field matches the chain count in both files | **proven** (observation, two files) | Both chains | What the 11 new records are |
| G4 | Bounding boxes are version-stable: identical f64 values, only offsets shift | rec81/rec82/rec51 boxes are byte-identical between 2023 and 2024 (e.g. rec81 [0.0122, −0.75, 2.5122, 1.75] in both; rec51's wild values 9.3857/−27.8013/61.4571 identical). 2023 offsets sit 24 bytes earlier (smaller header/body layout) | **proven** (observation, two files) | Large records, both files | — |
| G5 | Id width shrank u64→u32 consistently in 2023: header id, lists, and the rec17 index | 2023 dominant kind (91-byte bodies, 1,302 records) carries its list as u32s at +46 = [2, self, 17, …] (vs 2024's u64s at +74 = [17, self]). rec17's body is 7,507 B in 2023 vs 15,031 B in 2024 — roughly half, consistent with 4-byte vs 8-byte entries. 16 varying positions in both versions' dominant kinds (same count, different positions) | **proven** (observation, two files) | Both chains | The 2023 body's full field layout (F1/code positions differ — the @body+58 code read returns all zeros); whether the +58-59 codes are stable across versions |
| G6 | rec51's anomaly is version-stable, hence a real feature, not noise | Same wild f64s in both files (see G4) | **proven** (observation, two files) | Record 51, both files | What rec51 is (different class/units/transform?) |

## Layer 8 — Formats/Latest schema stream and Global/Latest (2026-11-05, goal finish-all-revitbridge-research)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| F1 | Formats/Latest decompresses to 470,502 B: the serialization schema (class table), one gzip member | Checksum-page strip + member @0 → 470,502 B; member 0 consumed 155,837/156,148 stripped bytes, so the "second gzip magic" at 113,720 is a false positive inside the deflate stream (same class of error as before: a magic pattern ≠ a member boundary). rvt-schema parses it as 4,126 classes with fields/parents/offsets (e.g. A3PartyAImage @2, ACDPtrWrapper @129 with field m_pACD, ImportVocabulary @203 with m_mapIntValues). My naive 4,492-name scan overcounts: it also catches field names (m_name, m_id, m_categoryId…) and std::pair<…> type spellings | **proven** (observation, cross-witnessed by rvt-schema) | Formats/Latest | Full per-class field decoding of record bodies (needs the code→class map, F4) |
| F2 | Global/Latest (938,578 B) is document metadata/history, NOT a record chain | Single gzip member (consumed 53,048/53,478); 0× the 0x059f prologue, no sorted-id run longer than 2; 2,581 UTF-16 strings including the Revit upgrade history (2018–2024 builds) and view/level names (Elevation 0, A100, Level 1, Section 0, 3D Views, Floor Plans…) | **proven** (observation) | Global/Latest | Its internal structure (not decoded) |
| F3 | Global/History (2,667 B) is revision history; TransmissionData is plain UTF-16LE XML; Contents (307 B) is small ints | Single gzip member @8 for History, containing a GUID blob; TransmissionData starts `<?xml version=` with no compression; Contents has one gzip magic at 91 inside 307 B of small integers | **proven** (observation) | Those streams | None material — none holds geometry |
| F4 | B4 CLOSED as honestly unknown: the +58-59 code maps to NEITHER the class-table index NOR the class tag | (a) Index refuted by rvt-schema cross-check: class[2157] = LinkHostedRoomTagCellHelper (GenSweepGStep is at 1892), class[393] = AssemblyCodeTable (ArcCurveCenterGStep at 341), class[696] = CompoundStructureLayer, class[1105] = SpacingRule. The earlier "registry[2157]=GenSweepGStep" was an artifact of my naive scan counting field names. (b) Tag refuted: no class has tag 2157/393/696/1105 (except 914 → ContourLabelingElem, coincidental); the GStep classes have tag None | **proven** (negative, cross-witnessed) | Formats/Latest + rvt-schema | Whether the code is an enum, a hash, or an index into a table not yet found — needs a second file |

## Layer 7 — bounding boxes: first geometry (2026-11-05, goal finish-all-revitbridge-research)

### Correction to D5
The −400/−432/−384 "f64 values" were misaligned-read phantoms
(offsets ≡ 2 mod 8). Correctly aligned reads (offsets ≡ 0 mod 8)
give the boxes below. Same trap as the f64 2.0 phantom — alignment
must be verified before any float reading is trusted.

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| E1 | Large records' numeric sections are 3D bounding boxes [minX, minY, minZ=0, maxX, maxY, maxZ=0] in feet — the first geometry content found | 6 f64s at +72..+112 in all 32 large records. Hub records share the 2.5×2.5 sketch bounds [0.012249, −0.75]–[2.512249, 1.75] (rec81 = rec82 = rec6662 = rec6663; 2.5 ft = 762 mm, the 0762×0762 type footprint). Children hold nested sub-boxes: 2″×2″ squares at the big box's corners (rec3637 bottom-right, rec3644 top-right), a vertical line on the right edge (rec88/rec6670: width 0, height 2.1667), a 2.25×2.25 rectangle inset exactly 0.125 (1.5″) on all sides (rec613/rec614). Z is 0 throughout — planar sketch entities | **proven** (observation); "sketch bounding box" reading **inference** | 32 large records | What each box's entity is (line? rectangle? profile?); the 0.012249 X offset; whether boxes alone suffice to reconstruct profiles (they give bounds, not the curve itself) |
| E2 | D3 partly resolved: geometry IS in Partitions — as sketch bounding boxes, not tessellated coordinates | E1 boxes + the D3 negative (no dense coordinate arrays anywhere) together say family geometry is parametric/sketch-based, with bounds stored per record | **proven** (observation) | Whole chain | Where the actual curves/profiles live (inside these same records? another stream?); whether any record holds tessellation |
| E3 | Record 5855 has TWO lists plus a 0.5″×0.5″ box | Main list @124 (6): [17, 5701, 5707, 5812, 5855, 5856]; second list @176 (8): [5779, 5809, 5819, 5820, 5823, 5828, 5829, 5833] — all 5701-subtree members. Box from its f64s: [~0, −1/48]–[1/24, 1/48] | **proven** (observation) | Record 5855 | Why it is dual-homed and double-listed; its tiny box's role |
| E4 | Second lists exist in large records too, with more entries | rec81 [21, 48, 1083, 1084, …] ×5; rec613 [21, 85, 86, 87, …] ×5; rec82 [47, 80]; rec614 [47, 612]; rec6663 [7650]; rec51 [6097] (possibly twice). Layout [u32 count][u64 entries] right after the main list. So bodies can hold multiple counted id-lists | **proven** (observation) | 32 large records | Second-list semantics by class (type-ref in small records vs member-links in large ones?) |
| E5 | Record 51 is an anomaly: its numeric section does not fit the box pattern | f64s 9.38, −27.8, 61.45, 8.14, 46.97 — no clean box, no shared values with its cluster | **proven** (observation) | Record 51 | Different class, different units, or a 3D transform? |

## Layer 6 — unified lists, type references, no geometry arrays (2026-11-05)

### Correction to Layer 4 (B3, B8, B9, B10) and C6 — READ FIRST

The "f64 2.0 dimension field", "stride-8 slots", "+83 field", and
"+70 = slots+2" readings are **withdrawn**: they were all
misreadings of one structure. Every record body carries a single
**sorted u64 id-list** starting at +74 (length = the +70 count field
after `ab 05`). The f64 2.0 at +75 is a **byte phantom**: list[0]=17
(bytes `11 00…`) followed by list[1] with low byte 0x40 (64, 4160,
5184, 5696, 6208, 6464, 6976, 7232, 7488, all ≡ 0x40 mod 256) puts
`00×7 40` across +75..+82, which reads as f64 2.0. The "slots" at
+90 were list entries 3+. "+83" is the second byte of list[1].
"+70" is the list length. C6's "slot lists are DFS" is withdrawn
too: rec64's entries [65, 4103, 5137] are sorted AND DFS-identical,
so sorted is the parsimonious reading for every list. The
observations underneath (which records share which ids) stand; only
the field interpretation changes.

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| D1 | Unified per-record sorted id-list: [scope root, self/owner, neighbors, subtree, shared refs], length = count field | Present in 1943/1975 records at +74; the 32 large records (D5) carry it at +124 with a u16 count at +120 (rec81: 20). Count distribution: 2×1316, 3×387, 4×123, 5×25, 6×35, 7×27, 8×12, 9×12, 10×2, 11×1, 12×1, 114 (5701), 1867 (rec17). Examples: rec64 [17, 64, 65, 4103, 5137]; rec31 [17, 30, 31, 32, 4122, …]; rec5615 [17, 5184, 5615, 5616, 5618, 5619, 5623] | **proven** (observation) | Whole chain | Role of each member (neighbor vs shared ref) is by position in a sorted list, so it is set membership only — role must come from cross-record analysis |
| D2 | A second list (type reference) follows the main list: [u32 count][u64 entries], usually 1 entry | 101 records, count2 = 1 (87) or 2 (14), sizes ≥143 only (none in 127/135 kinds). Top entries by referrer count: 612×12, 5602×10, 6661×9, 80×8, 7044×8, 6096×4, 5825×4; −2 (none) ×15. The top entries have count2 = 0 themselves (612, 5602, 6661, 80, 7044, 6096, 5825 all verified) — type-like records reference no type; rec21 is the exception (referenced ×3, yet has its own second list) | **proven** (observation); "type" reading **inference** | Whole chain | Whether second-list entries are FamilyTypes; what a 2-entry second list means; rec21's exception |
| D3 | NO tessellated geometry in Partitions/67: no dense coordinate arrays anywhere | Stride-1 f32 scan (runs ≥12 in [−10, 10] ft) and aligned f64 scan (runs ≥8) both return zero records. Family geometry is not stored as bulk float coordinates in these record bodies | **proven** (observation, negative) | Whole chain | Geometry is likely parametric (sketch + parameters) or lives in another stream (Global/Latest?); the numeric sections in D5 are the next lead |
| D4 | Record 5855 holds genuine numeric content: f64 −1/48, 1/24, 1/48 ft at +80/+96/+104 | 8-aligned f64 reads: @80 −0.0208333 (−1/48), @96 0.0416667 (1/24), @104 0.0208333 (1/48). First non-phantom floats in any record body. 5855 is also the dual-homed record (F1=17 but ElemTable owner 5701) | **proven** (observation); parameter/dimension reading **inference** | Record 5855 | Whether these are dimensions (½″, ¼″) or ratios; why 5855 is dual-homed |
| D5 | The 32 large records (sizes 209–393) are a separate class: numeric section + list at +124, no `ab 05` idiom | The 32 no-ab05 records cluster as hub families: {81, 82, 85–88, 3626, 3631, 3637, 3644}, {613, 614, 3736–3772}, {6662, 6663, 6667–6670, 6700–6739}, plus 5855 and 51. rec81/rec613 numeric sections contain f64 −400.0 / −432.0 (meaning unverified); lists start at +124 (rec81: [17, 80, 81, 82, 85, 86, …], count u16 20 at +120) | **proven** (observation) | 32 records | What the numeric sections encode (transform? sketch?); the −400/−432 values |
| D6 | 183-kind uniformly carries the +2/+3/+4 override bytes | All 22 183-records: +4=225, +3=122, +2=124/123; +70=5 mostly. The 12 127-records with +4=225 (B5) are the exception to their kind, not the rule | **proven** (observation) | Whole chain | Meaning of the override bytes; whether 183-kind is a distinct class |
| D7 | C5 reframed: 6096's list is [17, 64, 6090, 6096]; 6096 is a type-like record, 6090 a list member | 6096's main list (count 4) is [17, 64, 6090, 6096] — 64 is the shared ref creating the f64 phantom, 6090 is a member. 6096 is referenced by 4 second lists (rec30/34/38/42) and has count2 = 0. The 54-byte shared prefix with 6090 still stands (same-kind variants) | **proven** (observation) | Records 6090/6096 | Base/instance vs predecessor/successor still open |

## Layer 5 — index records and the count idiom (2026-11-04, continued)

| # | Conclusion | Evidence | Confidence | Search boundary | Unknowns |
|---|---|---|---|---|---|
| C1 | Record 5701 holds the complementary index: [17, 5701, sorted descendants] | 5701 body (1007 B): same index-record header shape as rec17 (`ab 05` + count, see C2), then a fully-sorted u64 array [17, 5701, 5702, …, 7200] + zero padding. Together the two indexes cover every element id | **proven** (observation) | Record 5701 only | Why 5855 (size 273, owner 5701) is dual-homed — it is the ONE descendant also present in rec17's array (B6's "exactly the subtree" corrected: 110 excluded, 5855 excepted) |
| C2 | A universal `ab 05` + u16 count idiom: [FF FF][ab 05][count] | At +66..+71 in small records (count = the +70 value: 2 for 127-kind, slots+2 for f64-class — so B8's "+70" IS this count field); at header +68..+71 in index records (rec17: 1867 = its array slots exactly; rec5701: 114 vs 115 slots, off by one, flagged not smoothed) | **proven** (observation) | 127-kind, f64-class, rec17, rec5701 | What the count counts in each class (id-fields? slots+fixed?); the 5701 off-by-one |
| C3 | Index/list records are a family, not just 17/5701 | Ascending-u64-run scan (≥10) finds: rec23/rec27 (10 entries at +74, heads [17, 21, …]), rec81/rec613/rec6662 (20–24 entries at +124, heads [17, self−1, self, self+1, …]), rec5817/rec5826 (subtree lists at +74, heads [5701, 5710, self−1, self, …]). Lists head with scope root(s) + neighborhood; 5710 is the subtree's second head entry (a hub: size 183, owner 5701) | **proven** (observation); list semantics **inference** | Whole chain | What the lists denote (linked elements? groups?); runs <10 not yet scanned |
| C4 | All size families share the 127-head pattern and F1 = owner | Sizes 135 (370), 143 (124), 151 (25), 159 (11), 175 (16), 183 (22) all open `00 00 FF×8 11 00…`; F1@10 splits 17/5701 in every family. +70 count varies WITHIN a size (135: all 3; 143: mostly 4; 151: 5/3/4; 183: 5/7/9/8) — count is per-record, not per-size. 183-kind heads differ at +2..+4 (like B5's override set) | **proven** (observation) | Whole chain | Whether 183-kind IS the override class |
| C5 | rec6096's extra slot 6090 is a non-descendant sibling sharing a 54-byte body prefix | 6090 (127-kind, owner 17, deviant code 696 with +55=0/+57=0) and 6096 (143-kind, owner 17) share 54 body bytes, then diverge (enum 30 vs 26, code 696 vs 1105); neither owns anything; 6096's slots are [6090, self] | **proven** (observation); relation **unknown** | Two records | Base/instance? Predecessor/successor? Needs a second file |
| C6 | Ordering distinguishes structure types: index arrays are sorted, slot lists are DFS pre-order | rec17 and rec5701 arrays fully sorted (verified pairwise); rec64's slots [65, 4103, 5137] follow DFS (65, then 65's child 4103, then 5137), not sorted order | **proven** (observation) | rec17, rec5701, rec64 | — |

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
