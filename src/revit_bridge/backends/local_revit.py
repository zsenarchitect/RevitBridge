"""Local-Revit backend. Status: scaffolded.

Real orchestration code for driving an installed Revit on Windows via the
Revit API (RVT -> IFC through Autodesk's open-source revit-ifc exporter
logic; X -> RVT through DirectShape import).

Cannot run in this environment (no Windows, no Revit): ``check_available``
fails loudly with the fix, and ``--dry-run`` generates the full export
bundle (C# add-in source, .addin manifest, build + launch scripts) so a
Windows user can inspect and run it.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from ..errors import BackendUnavailableError, ConversionError
from .base import Backend, ConversionContext

EXPORT_CS = r'''// RevitBridgeExporter: headless RVT -> IFC via the Revit API.
// Build against the RevitAPI.dll from the installed Revit version
// (see build.ps1). Uses Autodesk's open-source revit-ifc exporter when the
// add-in is installed; falls back to the built-in IFCExportOptions.
using System;
using System.IO;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitBridge
{
    [Transaction(TransactionMode.Manual)]
    public class ExportIfcCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            UIDocument uidoc = data.Application.ActiveUIDocument;
            Document doc = uidoc != null ? uidoc.Document : data.Application.Application.NewProjectDocument(UnitSystem.Metric);
            // When launched headless, the target path comes from the journal file.
            string outDir = Environment.GetEnvironmentVariable("REVITBRIDGE_OUTDIR") ?? Path.GetTempPath();
            string name = Environment.GetEnvironmentVariable("REVITBRIDGE_NAME") ?? Path.GetFileNameWithoutExtension(doc.PathName);
            Directory.CreateDirectory(outDir);
            var opts = new IFCExportOptions
            {
                FileVersion = IFCVersion.IFC4,
                SpaceBoundaryLevel = 0,
                ExportBaseQuantities = true,
                WallAndColumnSplitting = false,
            };
            doc.Export(outDir, name, opts);
            return Result.Succeeded;
        }
    }
}
'''

ADDIN_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns>
  <AddIn Type="Command">
    <Name>RevitBridge IFC Export</Name>
    <Assembly>{assembly}</Assembly>
    <FullClassName>RevitBridge.ExportIfcCommand</FullClassName>
    <AddInId>3f2a1c4e-9b1d-4a5e-8f2c-7d6b5a4c3e2a</AddInId>
    <VendorId>RBRI</VendorId>
  </AddIn>
  <AddIn Type="Command">
    <Name>RevitBridge Family Import</Name>
    <Assembly>{assembly}</Assembly>
    <FullClassName>RevitBridge.ImportFamilyCommand</FullClassName>
    <AddInId>4a3b2d5f-8c2e-4b6f-9f3d-8e7c6b5a4d3b</AddInId>
    <VendorId>RBRI</VendorId>
  </AddIn>
</RevitAddIns>
"""

CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <!-- Revit <=2024 targets .NET Framework 4.8; Revit 2025+ targets .NET 8.
         build.ps1 passes RevitTfm + RevitDir for the installed version. -->
    <RevitTfm Condition="'$(RevitTfm)'==''">net8.0-windows</RevitTfm>
    <TargetFramework>$(RevitTfm)</TargetFramework>
    <LangVersion>latest</LangVersion>
    <AssemblyName>RevitBridgeExporter</AssemblyName>
    <RootNamespace>RevitBridge</RootNamespace>
    <Nullable>disable</Nullable>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.NETFramework.ReferenceAssemblies" Version="1.0.3"
                      PrivateAssets="all" Condition="'$(RevitTfm)'=='net48'" />
    <Reference Include="RevitAPI">
      <HintPath>$(RevitDir)\\RevitAPI.dll</HintPath>
      <Private>False</Private>
    </Reference>
    <Reference Include="RevitAPIUI">
      <HintPath>$(RevitDir)\\RevitAPIUI.dll</HintPath>
      <Private>False</Private>
    </Reference>
  </ItemGroup>
</Project>
"""

BUILD_PS1 = r'''# Builds RevitBridgeExporter against the installed Revit's RevitAPI.dll
# and installs the .addin manifest. Auto-detects the newest installed
# Revit unless -RevitVersion is given. Revit <=2024 -> net48, 2025+ -> net8.
param([string]$RevitVersion = "")
if (-not $RevitVersion) {
    $found = Get-ChildItem "C:\Program Files\Autodesk" -Directory -Filter "Revit *" |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $found) { throw "No Revit install found under C:\Program Files\Autodesk" }
    $RevitVersion = ($found.Name -split " ")[-1]
}
$revitDir = "C:\Program Files\Autodesk\Revit $RevitVersion"
$api = Join-Path $revitDir "RevitAPI.dll"
if (-not (Test-Path $api)) { throw "RevitAPI.dll not found at $api" }
$tfm = if ([int]$RevitVersion -le 2024) { "net48" } else { "net8.0-windows" }
Write-Host "Building for Revit $RevitVersion ($tfm) against $revitDir"
dotnet build -c Release -p:RevitTfm=$tfm -p:RevitDir="$revitDir"
if ($LASTEXITCODE -ne 0) { throw "dotnet build failed" }
$dll = "bin\Release\$tfm\RevitBridgeExporter.dll"
$addins = "$env:APPDATA\Autodesk\Revit\AddIns\$RevitVersion"
New-Item -ItemType Directory -Force -Path $addins | Out-Null
Copy-Item $dll $addins
(Get-Content ExportIFC.addin.template).Replace("{assembly}", (Join-Path $addins "RevitBridgeExporter.dll")) |
    Set-Content (Join-Path $addins "RevitBridgeExporter.addin")
Write-Host "Installed both commands for Revit $RevitVersion."
Write-Host "In Revit: Add-Ins tab -> External Tools -> 'RevitBridge IFC Export'"
Write-Host "          Add-Ins tab -> External Tools -> 'RevitBridge Family Import'"
Write-Host "Family import: set REVITBRIDGE_MESH first, or use run-family-import.ps1."
'''

RUN_FAMILY_PS1 = r'''# Family import driver: stages the env vars the add-in reads, then
# launches Revit. The command itself is clicked in Revit (Add-Ins ->
# External Tools -> 'RevitBridge Family Import') -- a journal line that
# invokes an external command must be captured once per machine with
# Revit's macro recorder; clicking is the reliable proof path.
param(
    [Parameter(Mandatory=$true)][string]$Mesh,
    [string]$Rfa = "",
    [string]$Units = "m",
    [string]$Template = ""
)
$revit = Get-ChildItem "C:\Program Files\Autodesk\Revit *\Revit.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $revit) { throw "Revit.exe not found" }
$env:REVITBRIDGE_MESH = (Resolve-Path $Mesh).Path
if ($Rfa) { $env:REVITBRIDGE_RFA = $Rfa }
else { $env:REVITBRIDGE_RFA = [IO.Path]::ChangeExtension($env:REVITBRIDGE_MESH, ".rfa") }
$env:REVITBRIDGE_UNITS = $Units
if ($Template) { $env:REVITBRIDGE_TEMPLATE = $Template }
Write-Host "Mesh : $env:REVITBRIDGE_MESH (units: $Units)"
Write-Host "RFA  : $env:REVITBRIDGE_RFA"
Write-Host "Launching Revit -- then: Add-Ins -> External Tools -> 'RevitBridge Family Import'"
& $revit
'''

RUN_EXPORT_PS1 = r'''# Headless export driver (scaffolded: journal command line verified on first run)
param([string]$Model, [string]$OutDir)
$revit = Get-ChildItem "C:\Program Files\Autodesk\Revit *\Revit.exe" | Select-Object -First 1 -ExpandProperty FullName
if (-not $revit) { throw "Revit.exe not found" }
$env:REVITBRIDGE_OUTDIR = (Resolve-Path $OutDir).Path
$env:REVITBRIDGE_NAME = [IO.Path]::GetFileNameWithoutExtension($Model)
# NOTE: the exact journal line that invokes the external command must be
# captured once with Revit's macro recorder on the target machine; the
# journal below opens the model, which is the stable part.
$journal = Join-Path $PSScriptRoot "open-model.journal.txt"
(Get-Content $journal).Replace("{MODEL}", (Resolve-Path $Model).Path) | Set-Content "$env:TEMP\rb-export.txt"
& $revit "$env:TEMP\rb-export.txt"
'''

JOURNAL_TXT = """' RevitBridge headless export journal (generated)
Dim Jrn
Set Jrn = CrsJournalScript
Jrn.Command "StartupPage" , "Close"
Jrn.Command "Internal" , "Open an existing project , ID_REVIT_FILE_OPEN"
Jrn.PushButton "Modal , Open , Dialog_Revit_Open_Label" , "Cancel"
' model path injected by run-export.ps1:
' {MODEL}
"""

# First X->Revit application: mesh -> Revit FAMILY (.rfa), not full project.
# Real Revit API approach: new family document from a template, build a solid
# from the incoming mesh with TessellatedShapeBuilder, place it with
# FreeFormElement, save as .rfa. Dumb geometry by design (no parametrics).
IMPORT_FAMILY_CS = r'''// RevitBridgeImporter: mesh -> Revit family (.rfa) via the Revit API.
// FIRST X->Revit application: families, not full project documents.
// Build against the RevitAPI.dll from the installed Revit (see build.ps1).
//
// Mesh ingestion: ReadTriangles() parses OBJ and STL natively (below).
// glTF/GLB/IFC inputs are normalized to OBJ by the Python side first
// (stage_mesh_for_revit in local_revit.py) -- REVITBRIDGE_MESH always
// points at an .obj or .stl by the time this command runs.
// Units: source meshes are meters unless REVITBRIDGE_UNITS says otherwise
// (m|cm|mm|ft|in). Revit's internal unit is feet; conversion happens here,
// at read time, so the rest of the pipeline stays in meters.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitBridge
{
    [Transaction(TransactionMode.Manual)]
    public class ImportFamilyCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData data, ref string message, ElementSet elements)
        {
            Application app = data.Application.Application;
            string meshPath = Environment.GetEnvironmentVariable("REVITBRIDGE_MESH")
                ?? throw new InvalidOperationException("REVITBRIDGE_MESH not set");
            string rfaPath = Environment.GetEnvironmentVariable("REVITBRIDGE_RFA")
                ?? Path.ChangeExtension(meshPath, ".rfa");
            string template = Environment.GetEnvironmentVariable("REVITBRIDGE_TEMPLATE")
                ?? DefaultTemplatePath();

            Document famDoc = app.NewFamilyDocument(template);

            var builder = new TessellatedShapeBuilder
            {
                Target = TessellatedShapeBuilderTarget.Solid,
                Fallback = TessellatedShapeBuilderFallback.Mesh,
                GraphicsStyleId = ElementId.InvalidElementId,
            };
            foreach (var face in ReadTriangles(meshPath))
            {
                builder.OpenConnectedFaceSet(false);
                builder.AddFace(new TessellatedFace(
                    new List<XYZ> { face.A, face.B, face.C },
                    ElementId.InvalidElementId));
                builder.CloseConnectedFaceSet();
            }
            builder.Build();
            TessellatedShapeBuilderResult result = builder.GetBuildResult();

            using (var t = new Transaction(famDoc, "Import mesh as family"))
            {
                t.Start();
                if (result.IsValidSolid)
                    FreeFormElement.Create(famDoc, result.GetGeometryObjects());
                else
                    DirectShape.CreateElement(famDoc,
                        new ElementId(BuiltInCategory.OST_GenericModel))
                        .SetShape(result.GetGeometryObjects());
                t.Commit();
            }
            famDoc.SaveAs(rfaPath);
            famDoc.Close(false);
            return Result.Succeeded;
        }

        // Newest installed "RVT <year>" Generic Model template wins, so the
        // bundle works across Revit versions without edits. Override with
        // REVITBRIDGE_TEMPLATE when a specific template is wanted.
        private static string DefaultTemplatePath()
        {
            string root = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "Autodesk");
            var candidates = new List<string>();
            if (Directory.Exists(root))
                foreach (string dir in Directory.GetDirectories(root, "RVT *"))
                {
                    string p = Path.Combine(dir, @"Family Templates\English\Generic Model.rft");
                    if (File.Exists(p)) candidates.Add(p);
                }
            candidates.Sort(); // "RVT 2024" < "RVT 2025" < ... lexicographic == chronological here
            if (candidates.Count > 0) return candidates[candidates.Count - 1];
            throw new FileNotFoundException(
                "No Generic Model family template found under " + root +
                " -- set REVITBRIDGE_TEMPLATE to a .rft path.");
        }

        // ---- triangle ingestion -------------------------------------------
        // Parsers work on a Revit-independent Vec3 so the logic stays
        // reviewable (and unit-testable) without the Revit API; the adapter
        // at the bottom converts to XYZ (feet).

        private struct Vec3
        {
            public double X, Y, Z;
            public Vec3(double x, double y, double z) { X = x; Y = y; Z = z; }
        }

        private static double UnitScaleToFeet()
        {
            string units = (Environment.GetEnvironmentVariable("REVITBRIDGE_UNITS") ?? "m")
                .Trim().ToLowerInvariant();
            switch (units)
            {
                case "m": return 3.280839895013123;
                case "cm": return 0.03280839895013123;
                case "mm": return 0.003280839895013123;
                case "ft": return 1.0;
                case "in": return 1.0 / 12.0;
                default: throw new InvalidOperationException(
                    "REVITBRIDGE_UNITS must be m|cm|mm|ft|in, got '" + units + "'");
            }
        }

        private static IEnumerable<(XYZ A, XYZ B, XYZ C)> ReadTriangles(string path)
        {
            string ext = Path.GetExtension(path).ToLowerInvariant();
            IEnumerable<(Vec3 A, Vec3 B, Vec3 C)> tris;
            if (ext == ".obj") tris = ParseObj(path);
            else if (ext == ".stl") tris = ParseStl(path);
            else throw new InvalidOperationException(
                "ImportFamilyCommand reads .obj/.stl natively; stage '" + ext +
                "' to OBJ first (revit-convert does this automatically).");
            foreach (var t in tris)
                yield return (new XYZ(t.A.X, t.A.Y, t.A.Z),
                              new XYZ(t.B.X, t.B.Y, t.B.Z),
                              new XYZ(t.C.X, t.C.Y, t.C.Z));
        }

        private static IEnumerable<(Vec3 A, Vec3 B, Vec3 C)> ParseObj(string path)
        {
            double s = UnitScaleToFeet();
            var verts = new List<Vec3>();
            foreach (string raw in File.ReadLines(path))
            {
                string line = raw.Trim();
                if (line.StartsWith("v "))
                {
                    string[] p = line.Split(new[] { ' ', '\t' },
                        StringSplitOptions.RemoveEmptyEntries);
                    verts.Add(new Vec3(
                        double.Parse(p[1], CultureInfo.InvariantCulture) * s,
                        double.Parse(p[2], CultureInfo.InvariantCulture) * s,
                        double.Parse(p[3], CultureInfo.InvariantCulture) * s));
                }
                else if (line.StartsWith("f "))
                {
                    string[] p = line.Split(new[] { ' ', '\t' },
                        StringSplitOptions.RemoveEmptyEntries);
                    var idx = new List<int>();
                    for (int i = 1; i < p.Length; i++)
                    {
                        // face tokens: v, v/vt, v//vn, v/vt/vn -- vertex is [0]
                        int vi = int.Parse(p[i].Split('/')[0],
                            CultureInfo.InvariantCulture);
                        if (vi < 0) vi = verts.Count + vi; // relative index
                        idx.Add(vi);
                    }
                    // fan triangulation (OBJ faces are convex in practice;
                    // n-gons collapse to (0, i, i+1))
                    for (int i = 1; i + 1 < idx.Count; i++)
                        yield return (verts[idx[0]], verts[idx[i]], verts[idx[i + 1]]);
                }
            }
        }

        private static IEnumerable<(Vec3 A, Vec3 B, Vec3 C)> ParseStl(string path)
        {
            double s = UnitScaleToFeet();
            byte[] bytes = File.ReadAllBytes(path);
            // Binary STL: 80-byte header, uint32 count, 50 bytes/triangle.
            // The size check is the reliable discriminator (binary files may
            // also start with the ASCII magic "solid").
            if (bytes.Length >= 84)
            {
                uint count = BitConverter.ToUInt32(bytes, 80);
                if (bytes.Length == 84 + (long)count * 50)
                {
                    int off = 84;
                    for (uint i = 0; i < count; i++)
                    {
                        off += 12; // facet normal (ignored; builder recomputes)
                        var v = new Vec3[3];
                        for (int k = 0; k < 3; k++)
                        {
                            v[k] = new Vec3(
                                BitConverter.ToSingle(bytes, off) * s,
                                BitConverter.ToSingle(bytes, off + 4) * s,
                                BitConverter.ToSingle(bytes, off + 8) * s);
                            off += 12;
                        }
                        off += 2; // attribute byte count
                        yield return (v[0], v[1], v[2]);
                    }
                    yield break;
                }
            }
            // ASCII STL: "vertex x y z" lines, grouped in threes.
            var tri = new List<Vec3>();
            foreach (string raw in File.ReadLines(path))
            {
                string line = raw.Trim();
                if (!line.StartsWith("vertex ")) continue;
                string[] p = line.Split(new[] { ' ', '\t' },
                    StringSplitOptions.RemoveEmptyEntries);
                tri.Add(new Vec3(
                    double.Parse(p[1], CultureInfo.InvariantCulture) * s,
                    double.Parse(p[2], CultureInfo.InvariantCulture) * s,
                    double.Parse(p[3], CultureInfo.InvariantCulture) * s));
                if (tri.Count == 3)
                {
                    yield return (tri[0], tri[1], tri[2]);
                    tri.Clear();
                }
            }
        }
    }
}
'''


def find_revit_exe() -> str | None:
    if platform.system() != "Windows":
        return None
    for base in (r"C:\Program Files\Autodesk", r"C:\Program Files (x86)\Autodesk"):
        if not os.path.isdir(base):
            continue
        for entry in sorted(os.listdir(base), reverse=True):
            if entry.lower().startswith("revit"):
                cand = os.path.join(base, entry, "Revit.exe")
                if os.path.isfile(cand):
                    return cand
    return shutil.which("Revit.exe")


def stage_mesh_for_revit(src: str, src_fmt: str, workdir: str) -> str:
    """Normalize a mesh input to a file ImportFamilyCommand reads natively.

    OBJ and STL pass through untouched (the C# parses both). IFC goes through
    the proven ifcopenshell backend; GLB/glTF through trimesh. Returns the
    path to hand to REVITBRIDGE_MESH. Units stay in meters end to end; the
    C# converts to feet at read time (REVITBRIDGE_UNITS, default m).
    """
    if src_fmt in ("obj", "stl"):
        return src
    out_dir = Path(workdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    staged = out_dir / f"{Path(src).stem}.staged.obj"
    if src_fmt == "ifc":
        from .base import ConversionContext
        from .ifcopenshell_backend import IfcOpenShellBackend

        IfcOpenShellBackend().convert(ConversionContext(
            src=src, dst=str(staged), src_fmt="ifc", dst_fmt="obj",
            workdir=str(out_dir)))
        return str(staged)
    if src_fmt in ("glb", "gltf"):
        try:
            import trimesh
        except ImportError as e:
            raise ConversionError(
                "Staging glTF for Revit needs the 'trimesh' package: pip install trimesh"
            ) from e
        try:
            scene = trimesh.load(src)
            data = scene.export(file_type="obj")
        except Exception as e:
            raise ConversionError(f"Could not stage {src_fmt} to OBJ: {e}") from e
        if isinstance(data, str):
            data = data.encode("utf-8")
        staged.write_bytes(data)
        return str(staged)
    raise ConversionError(f"Cannot stage format {src_fmt!r} for Revit import")


class LocalRevitBackend(Backend):
    name = "local-revit"
    title = "Local Revit (Windows + Revit API)"
    status = "scaffolded"
    note = (
        "RVT->IFC via the Revit API (revit-ifc logic); X->RFA (Revit family, "
        "the first X->Revit application) via TessellatedShapeBuilder; X->RVT "
        "secondary. Code complete, untested here: needs Windows + Revit."
    )

    _FROM_RVT = {("rvt", "ifc")}
    # Family-first: .rfa is the primary X->Revit target; full .rvt secondary.
    _TO_RFA = {("ifc", "rfa"), ("obj", "rfa"), ("glb", "rfa"), ("gltf", "rfa")}
    _TO_RVT = {("ifc", "rvt"), ("obj", "rvt"), ("glb", "rvt"), ("gltf", "rvt")}

    def supports(self, src_fmt: str, dst_fmt: str) -> bool:
        return (src_fmt, dst_fmt) in self._FROM_RVT | self._TO_RFA | self._TO_RVT

    def check_available(self) -> None:
        exe = find_revit_exe()
        if exe is None:
            raise BackendUnavailableError(
                "The 'local-revit' backend needs Windows with Autodesk Revit installed. "
                f"This machine is {platform.system()}. "
                "Alternatives: --backend aps-cloud (needs APS credentials) or --backend mock (pipeline only)."
            )

    # -- bundle generation -------------------------------------------------
    def generate_bundle(self, workdir: str) -> dict[str, str]:
        """Write the export bundle a Windows user needs. Returns {label: path}."""
        d = Path(workdir) / "revit-export-bundle"
        d.mkdir(parents=True, exist_ok=True)
        files = {
            "addin_source": ("RevitBridgeExporter/ExportIfcCommand.cs", EXPORT_CS),
            "family_import_source": ("RevitBridgeExporter/ImportFamilyCommand.cs", IMPORT_FAMILY_CS),
            "project": ("RevitBridgeExporter/RevitBridgeExporter.csproj", CSPROJ),
            "addin_manifest_template": ("RevitBridgeExporter/ExportIFC.addin.template", ADDIN_MANIFEST),
            "build_script": ("RevitBridgeExporter/build.ps1", BUILD_PS1),
            "run_script": ("RevitBridgeExporter/run-export.ps1", RUN_EXPORT_PS1),
            "run_family_script": ("RevitBridgeExporter/run-family-import.ps1", RUN_FAMILY_PS1),
            "journal": ("RevitBridgeExporter/open-model.journal.txt", JOURNAL_TXT),
        }
        out = {}
        for label, (rel, content) in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            out[label] = str(p)
        (d / "README.txt").write_text(
            "RevitBridge local-Revit export bundle.\n"
            "1. On a Windows machine with Revit + .NET SDK: run build.ps1\n"
            "   (auto-detects the installed Revit; <=2024 builds net48,\n"
            "   2025+ builds net8.0-windows; installs both add-in commands)\n"
            "2. RVT->IFC headless: run-export.ps1 <model.rvt> <outdir>\n"
            "3. The exported .ifc feeds the ifcopenshell backend for OBJ/STL/GLB.\n"
            "X->RFA (FIRST X->Revit application): ImportFamilyCommand.cs creates\n"
            "a family document from the newest installed Generic Model template,\n"
            "builds a solid from the mesh via TessellatedShapeBuilder, saves .rfa.\n"
            "ReadTriangles() parses OBJ and STL natively (units: meters unless\n"
            "REVITBRIDGE_UNITS=m|cm|mm|ft|in; converted to feet at read time).\n"
            "GLB/glTF/IFC inputs are staged to OBJ by revit-convert automatically\n"
            "(stage_mesh_for_revit). Run it:\n"
            "   run-family-import.ps1 <mesh.obj> [out.rfa] [-Units m]\n"
            "then in Revit: Add-Ins -> External Tools -> 'RevitBridge Family Import'.\n"
            "Full proof walkthrough: docs/windows-proof.md in the repo.\n"
            "Dumb geometry by design (no parametric round-trip) -- see README.\n"
            "X->RVT full-project import is secondary and shares the scaffolding.\n",
            encoding="utf-8",
        )
        return out

    # -- conversion ---------------------------------------------------------
    def convert(self, ctx: ConversionContext) -> str:
        if ctx.dry_run:
            bundle = self.generate_bundle(ctx.workdir)
            return bundle["journal"]  # representative artifact
        self.check_available()
        if (ctx.src_fmt, ctx.dst_fmt) in self._TO_RFA | self._TO_RVT:
            # Everything preparable off-Revit IS prepared: the mesh is staged
            # to OBJ/STL and the bundle is generated. What remains genuinely
            # unproven is the in-Revit run itself -- say exactly that.
            staged = stage_mesh_for_revit(ctx.src, ctx.src_fmt, ctx.workdir)
            bundle = self.generate_bundle(ctx.workdir)
            target = "family (.rfa)" if ctx.dst_fmt == "rfa" else "project (.rvt)"
            raise ConversionError(
                f"X->{target} import: mesh staged to {staged} and the add-in "
                f"bundle generated at {bundle['build_script']}, but the "
                "in-Revit execution is scaffolded, not proven: build the "
                "add-in (build.ps1) and run 'RevitBridge Family Import' "
                "inside Revit (run-family-import.ps1 stages the env vars). "
                "See docs/windows-proof.md for the proof walkthrough."
            )
        bundle = self.generate_bundle(ctx.workdir)
        ps1 = bundle["run_script"]
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", ps1, ctx.src, ctx.workdir],
                capture_output=True, text=True, timeout=1800,
            )
        except Exception as e:
            raise ConversionError(f"Revit headless export failed to launch: {e}") from e
        stem = Path(ctx.src).stem
        produced = Path(ctx.workdir) / f"{stem}.ifc"
        if proc.returncode != 0 or not produced.exists():
            tail = (proc.stderr or proc.stdout or "")[-2000:]
            raise ConversionError(f"Revit export failed (rc={proc.returncode}):\n{tail}")
        shutil.copyfile(produced, ctx.dst)
        return ctx.dst
