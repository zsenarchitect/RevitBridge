# RevitBridge — agent notes

Public MIT repo (`zsenarchitect/RevitBridge`): IFC → OBJ/STL/GLB via IfcOpenShell,
static RVT probe, local-revit and APS-cloud backends (scaffolded, unproven).
Library + CLI + backends only; see `README.md` for the full picture.

## Stack

- Python package (`pyproject.toml`, `src/`, `tests/`). 43 tests green (2026-11-04).
- Rust survey binaries (`rvt-rs`): `rvt-dump`, `rvt-inspect`, `rvt-schema`,
  `rvt-elem-table`, built under `~/workspace/rvt-rs-survey/target/release/`.

## How to run / test

- Tests: `pytest` from the repo root (sandbox: use the repo `.venv`).
- The Partitions RE ledger lives in `docs/re/partitions.md` — Layers 1–17,
  complete as of 2026-11-05 (goal "Finish all RevitBridge research" completed).
  Remaining unknowns are honestly marked there with their unblockers (third
  family file or Revit ground truth); do not re-derive them from these two files.

## Traps

- Sandbox `/tmp` is wiped between runs. Durable samples live in
  `~/workspace/revitbridge-samples/` (2024 family, SHA-256 `fe9ffd26cec4fa66…`;
  2023 family `racbasicsamplefamily-2023.rfa`, SHA-256 `1cdff09b3fcf6aa5…`).
  Never rely on `/tmp` copies.
- No Revit on this Linux sandbox: anything needing live Revit (family geometry
  ground truth, OBJ→RFA proof run) needs Peter's Windows machine.
- Partitions record framing is version-dependent: 2023 = 12-byte header
  (`[u32 id][u32 size][u16 prologue][u16 count]`), 2024 = 16-byte header
  (`[u64 id][u32 size][u16 prologue][u16 count]`). A parser must be version-aware.
- Stored pages carry a checksum that must be stripped BEFORE inflating
  (65249 = 64896 payload + 353 checksum); members do NOT share a deflate window.
