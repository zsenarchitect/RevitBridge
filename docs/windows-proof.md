# Windows proof: OBJ → RFA family import (the family-first milestone)

Everything that can be prepared off-Revit is done: `ReadTriangles` is
implemented (OBJ + STL parsers, meters→feet at read), non-OBJ inputs are
staged to OBJ automatically, the bundle ships a real `.csproj`, and the
add-in manifest registers both commands. What remains is exactly one thing:
**run it once on a real Revit** and check the output against the list below.

Time estimate: ~30 minutes, most of it installing the .NET SDK.

## Prerequisites

- Windows 10/11 with **Revit installed and activated** (any version 2022+;
  the bundle auto-detects it — ≤2024 builds net48, 2025+ builds net8)
- **.NET SDK** (`winget install Microsoft.DotNet.SDK.8`) — needed to compile
  the add-in. On Revit ≤2024 the SDK still works: it builds the net48 target
  via reference assemblies (the csproj handles this).
- **Git** and **Python 3.12**
- A Revit **family template**: the default Generic Model template that ships
  with Revit (`ProgramData\Autodesk\RVT <year>\Family Templates\English\`).
  The add-in finds the newest one automatically; `REVITBRIDGE_TEMPLATE`
  overrides.

## Steps

```powershell
# 1. Get the code
git clone https://github.com/zsenarchitect/RevitBridge.git
cd RevitBridge
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. Generate the add-in bundle (dry run = bundle only, no Revit needed)
revit-convert examples\proof_box.obj --to rfa --backend local-revit --dry-run

# 3. Build + install the add-in (auto-detects your Revit version)
cd revit-export-bundle\RevitBridgeExporter
.\build.ps1
cd ..\..

# 4. Stage the env vars and launch Revit
.\revit-export-bundle\RevitBridgeExporter\run-family-import.ps1 examples\proof_box.obj

# 5. In Revit: Add-Ins tab -> External Tools -> "RevitBridge Family Import"
#    The command creates the family, saves proof_box.rfa next to the .obj,
#    and closes the family document.
```

## Verify (this is the proof — all five must hold)

1. `examples\proof_box.rfa` exists and is non-trivial in size (>10 KB).
2. Open it in Revit: it loads as a **Generic Model** family.
3. The geometry is a **closed solid**, not an open mesh: select it and check
   the properties / use a section box — a 1 m cube.
4. Dimensions: bounding box ≈ **3.28084 ft** per side (1 m converted). If it
   reads 1.0 ft or 3.28 m, the unit conversion is wrong — report which.
5. Place it in a project (Load into Project) and confirm it appears.

Bonus check with a real input: convert any IFC with the proven pipeline
(`revit-convert model.ifc --to model.obj`) and import that OBJ the same way.

## Report back

- Revit version used, .NET SDK version
- The five checks above: pass/fail each, with the actual bbox number
- The produced `proof_box.rfa` file itself (attach it)
- Any build errors verbatim (first compile on a new machine is where
  API-surface surprises would show up)

## Known soft spots (stated plainly)

- The exact Revit API calls follow Autodesk's documented patterns, but this
  code has **never been compiled** — there is no dotnet SDK or Revit in the
  dev sandbox. First build errors are expected to be small; send them back
  and they'll be fixed in one round.
- `TessellatedShapeBuilder` is asked for a Solid with Mesh fallback: a
  non-watertight input mesh lands as a DirectShape mesh instead of failing.
  The proof cube is watertight, so check #3 distinguishes the two.
- Headless/journal invocation of the external command is **not** part of
  this proof — clicking the command is. Journal automation comes after.
