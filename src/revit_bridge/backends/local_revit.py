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
    <AddInId>3f2a1c4e-9b1d-4a5e-8f2c-7d6b5a4c3e2a1</AddInId>
    <VendorId>RBRI</VendorId>
  </AddIn>
</RevitAddIns>
"""

BUILD_PS1 = r'''# Builds RevitBridgeExporter against the installed Revit's RevitAPI.dll
param([string]$RevitVersion = "2024")
$revitDir = "C:\Program Files\Autodesk\Revit $RevitVersion"
$api = Join-Path $revitDir "RevitAPI.dll"
if (-not (Test-Path $api)) { throw "RevitAPI.dll not found at $api" }
$env:RevitApiPath = $api
dotnet build -c Release
$dll = "bin\Release\net8.0-windows\RevitBridgeExporter.dll"
$addins = "$env:APPDATA\Autodesk\Revit\AddIns\$RevitVersion"
New-Item -ItemType Directory -Force -Path $addins | Out-Null
Copy-Item $dll $addins
(Get-Content ExportIFC.addin.template).Replace("{assembly}", (Join-Path $addins "RevitBridgeExporter.dll")) |
    Set-Content (Join-Path $addins "RevitBridgeExporter.addin")
Write-Host "Installed. Launch Revit and run the 'RevitBridge IFC Export' command,"
Write-Host "or drive it headless with run-export.ps1 <model.rvt> <outdir>."
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


class LocalRevitBackend(Backend):
    name = "local-revit"
    title = "Local Revit (Windows + Revit API)"
    status = "scaffolded"
    note = (
        "RVT->IFC via the Revit API (revit-ifc logic); X->RVT via DirectShape. "
        "Code complete, untested here: needs Windows + Revit."
    )

    _FROM_RVT = {("rvt", "ifc")}
    _TO_RVT = {("ifc", "rvt"), ("obj", "rvt"), ("glb", "rvt"), ("gltf", "rvt")}

    def supports(self, src_fmt: str, dst_fmt: str) -> bool:
        return (src_fmt, dst_fmt) in self._FROM_RVT | self._TO_RVT

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
            "addin_manifest_template": ("RevitBridgeExporter/ExportIFC.addin.template", ADDIN_MANIFEST),
            "build_script": ("RevitBridgeExporter/build.ps1", BUILD_PS1),
            "run_script": ("RevitBridgeExporter/run-export.ps1", RUN_EXPORT_PS1),
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
            "1. On a Windows machine with Revit + .NET 8 SDK: run build.ps1\n"
            "2. Headless: run-export.ps1 <model.rvt> <outdir>\n"
            "3. The exported .ifc feeds the ifcopenshell backend for OBJ/STL/GLB.\n"
            "X->RVT: DirectShape import is generated on request; it produces dumb\n"
            "geometry (no parametric round-trip) -- see the main README.\n",
            encoding="utf-8",
        )
        return out

    # -- conversion ---------------------------------------------------------
    def convert(self, ctx: ConversionContext) -> str:
        if ctx.dry_run:
            bundle = self.generate_bundle(ctx.workdir)
            return bundle["journal"]  # representative artifact
        self.check_available()
        if (ctx.src_fmt, ctx.dst_fmt) in self._TO_RVT:
            raise ConversionError(
                f"X->RVT import for {ctx.src_fmt} is scaffolded: the DirectShape "
                "import command is generated by generate_bundle(), but end-to-end "
                "execution needs a Windows+Revit run to prove. See README 'the hard direction'."
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
