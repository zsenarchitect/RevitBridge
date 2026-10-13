import pytest

from revit_bridge.errors import UnsupportedFormatError
from revit_bridge.formats import canonical, format_from_path, route


def test_canonical():
    assert canonical(".RVT") == "rvt"
    assert canonical(" glb ") == "glb"
    assert canonical("IFC") == "ifc"


def test_format_from_path():
    assert format_from_path("model.rvt") == "rvt"
    assert format_from_path("/tmp/x/model.IFC") == "ifc"
    with pytest.raises(UnsupportedFormatError):
        format_from_path("model.xyz")


def test_route_direct():
    assert route("ifc", "glb") == [("ifc", "glb")]
    assert route("rvt", "ifc") == [("rvt", "ifc")]
    assert route("rfa", "ifc") == [("rvt", "ifc")]  # family files ride the rvt route


def test_route_via_ifc():
    assert route("rvt", "obj") == [("rvt", "ifc"), ("ifc", "obj")]


def test_route_same_format_rejected():
    with pytest.raises(UnsupportedFormatError):
        route("ifc", "ifc")


def test_step_not_feasible():
    with pytest.raises(UnsupportedFormatError, match="[Ss][Tt][Ee][Pp]"):
        route("ifc", "step")


def test_unknown_route():
    with pytest.raises(UnsupportedFormatError):
        route("stl", "ifc")
