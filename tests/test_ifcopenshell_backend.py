import pytest
import trimesh

from revit_bridge.backends import ConversionContext, REGISTRY
from revit_bridge.backends.ifcopenshell_backend import tessellate


def _ctx(src, dst, fmt, tmp_path):
    return ConversionContext(src=src, dst=dst, src_fmt="ifc", dst_fmt=fmt,
                             workdir=str(tmp_path))


def test_tessellate_counts(sample_ifc):
    meshes = tessellate(sample_ifc)
    assert len(meshes) == 5  # 4 walls + 1 slab
    for m in meshes:
        assert m["vertices"].shape[1] == 3
        assert m["faces"].shape[1] == 3


def test_ifc_to_obj(tmp_path, sample_ifc):
    be = REGISTRY["ifcopenshell"]
    dst = str(tmp_path / "out.obj")
    be.convert(_ctx(sample_ifc, dst, "obj", tmp_path))
    text = open(dst).read()
    assert text.count("\nv ") == 40
    assert text.count("\nf ") == 60
    assert text.count("\no ") == 5
    mtl = open(str(tmp_path / "out.mtl")).read()
    assert mtl.count("newmtl") == 5


def test_ifc_to_stl(tmp_path, sample_ifc):
    be = REGISTRY["ifcopenshell"]
    dst = str(tmp_path / "out.stl")
    be.convert(_ctx(sample_ifc, dst, "stl", tmp_path))
    text = open(dst).read()
    assert text.count("facet normal") == 60  # 5 boxes x 12 triangles
    assert text.strip().endswith("endsolid revitbridge")


def test_ifc_to_glb(tmp_path, sample_ifc):
    be = REGISTRY["ifcopenshell"]
    dst = str(tmp_path / "out.glb")
    be.convert(_ctx(sample_ifc, dst, "glb", tmp_path))
    scene = trimesh.load(dst)
    assert len(scene.geometry) == 5
    lo, hi = scene.bounds
    assert hi[2] == pytest.approx(3.0, abs=0.01)  # wall height
    assert hi[0] == pytest.approx(5.1, abs=0.01)   # 5m + wall thickness


def test_gltf_json_points_to_glb(tmp_path, sample_ifc):
    be = REGISTRY["ifcopenshell"]
    with pytest.raises(Exception, match="byte-equivalent"):
        be.convert(_ctx(sample_ifc, str(tmp_path / "out.gltf"), "gltf", tmp_path))
