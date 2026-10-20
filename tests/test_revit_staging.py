"""Mesh staging for the local-revit family import + bundle integrity.

The C# parsers cannot execute here (no dotnet, no Revit), so these tests pin
everything around them: staging output shape, bundle contents, manifest
validity, and the proof fixtures' geometry. The in-Revit run itself is
docs/windows-proof.md.
"""

import re
from pathlib import Path

from revit_bridge.backends import REGISTRY, ConversionContext
from revit_bridge.backends.local_revit import stage_mesh_for_revit

REPO = Path(__file__).resolve().parent.parent
PROOF_OBJ = REPO / "examples" / "proof_box.obj"
PROOF_STL = REPO / "examples" / "proof_box.stl"
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def test_proof_fixtures():
    obj = PROOF_OBJ.read_text()
    assert len(re.findall(r"^v ", obj, re.M)) == 8
    assert len(re.findall(r"^f ", obj, re.M)) == 6  # quads -> 12 tris fanned
    stl = PROOF_STL.read_text()
    assert len(re.findall(r"^\s*facet ", stl, re.M)) == 12
    assert len(re.findall(r"^\s*vertex ", stl, re.M)) == 36


def test_stage_passthrough_obj_stl(tmp_path):
    assert stage_mesh_for_revit(str(PROOF_OBJ), "obj", str(tmp_path)) == str(PROOF_OBJ)
    assert stage_mesh_for_revit(str(PROOF_STL), "stl", str(tmp_path)) == str(PROOF_STL)


def test_stage_ifc_to_obj(tmp_path, sample_ifc):
    staged = stage_mesh_for_revit(sample_ifc, "ifc", str(tmp_path))
    text = Path(staged).read_text()
    assert staged.endswith(".obj")
    assert len(re.findall(r"^v ", text, re.M)) >= 8
    assert re.search(r"^f ", text, re.M)


def test_stage_glb_to_obj(tmp_path, sample_ifc):
    be = REGISTRY["ifcopenshell"]
    glb = str(tmp_path / "in.glb")
    be.convert(ConversionContext(src=sample_ifc, dst=glb, src_fmt="ifc",
                                 dst_fmt="glb", workdir=str(tmp_path)))
    staged = stage_mesh_for_revit(glb, "glb", str(tmp_path))
    text = Path(staged).read_text()
    assert staged.endswith(".obj")
    assert len(re.findall(r"^v ", text, re.M)) >= 8


def test_bundle_project_manifest_and_parsers(tmp_path):
    be = REGISTRY["local-revit"]
    bundle = be.generate_bundle(str(tmp_path))

    csproj = Path(bundle["project"]).read_text()
    assert "RevitAPI" in csproj and "RevitTfm" in csproj and "net48" in csproj

    manifest_tpl = Path(bundle["addin_manifest_template"]).read_text()
    assert "RevitBridge.ExportIfcCommand" in manifest_tpl
    assert "RevitBridge.ImportFamilyCommand" in manifest_tpl
    guids = re.findall(r"<AddInId>([^<]+)</AddInId>", manifest_tpl)
    assert len(guids) == 2 and all(GUID_RE.match(g) for g in guids), guids

    fam = Path(bundle["family_import_source"]).read_text()
    assert "NotImplementedException" not in fam  # ReadTriangles is implemented
    assert "ParseObj" in fam and "ParseStl" in fam
    assert "REVITBRIDGE_UNITS" in fam and "3.280839895013123" in fam
    assert "DefaultTemplatePath" in fam

    build = Path(bundle["build_script"]).read_text()
    assert "RevitTfm" in build and "net48" in build

    run_fam = Path(bundle["run_family_script"]).read_text()
    assert "REVITBRIDGE_MESH" in run_fam and "RevitBridge Family Import" in run_fam
