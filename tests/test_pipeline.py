import json

import pytest

from revit_bridge.errors import UnsupportedFormatError
from revit_bridge.pipeline import convert, plan


def test_plan_direct():
    steps = plan("ifc", "obj")
    assert [(s.src_fmt, s.dst_fmt, s.backend_name) for s in steps] == [("ifc", "obj", "ifcopenshell")]


def test_plan_via_ifc():
    steps = plan("rvt", "glb")
    assert [(s.src_fmt, s.dst_fmt) for s in steps] == [("rvt", "ifc"), ("ifc", "glb")]
    assert steps[0].backend_name == "local-revit"
    assert steps[1].backend_name == "ifcopenshell"


def test_plan_explicit_backend():
    steps = plan("rvt", "glb", backend="mock")
    assert all(s.backend_name == "mock" for s in steps)


def test_plan_family_import():
    steps = plan("obj", "rfa")
    assert [(s.src_fmt, s.dst_fmt, s.backend_name) for s in steps] == [
        ("obj", "rfa", "local-revit")]


def test_plan_unknown_backend():
    with pytest.raises(UnsupportedFormatError, match="Unknown backend"):
        plan("ifc", "obj", backend="nope")


def test_plan_backend_cannot_do_hop():
    with pytest.raises(UnsupportedFormatError, match="cannot do"):
        plan("rvt", "glb", backend="aps-cloud")  # aps-cloud has no ifc->glb hop


def test_convert_mock_end_to_end(tmp_path):
    src = tmp_path / "model.rvt"
    src.write_bytes(b"fake-rvt")
    dst = tmp_path / "model.glb"
    out = convert(str(src), str(dst), backend="mock", workdir=str(tmp_path))
    assert out == str(dst)
    manifest = json.loads(dst.read_text())
    assert manifest["mock"] is True
    # final hop of the rvt->ifc->glb route records ifc->glb ...
    assert manifest["src_fmt"] == "ifc" and manifest["dst_fmt"] == "glb"
    # ... and the intermediate IFC hop left its own manifest behind
    hops = list(tmp_path.glob("_hop0_*.ifc"))
    assert len(hops) == 1
    assert json.loads(hops[0].read_text())["dst_fmt"] == "ifc"


def test_convert_ifc_mock(tmp_path, sample_ifc):
    dst = tmp_path / "out.obj"
    convert(sample_ifc, str(dst), backend="mock")
    assert json.loads(dst.read_text())["dst_fmt"] == "obj"
