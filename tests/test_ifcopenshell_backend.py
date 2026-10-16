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


def test_ifc_to_gltf(tmp_path, sample_ifc):
    import base64
    import json

    be = REGISTRY["ifcopenshell"]
    dst = str(tmp_path / "out.gltf")
    be.convert(_ctx(sample_ifc, dst, "gltf", tmp_path))
    doc = json.loads(open(dst).read())

    assert doc["asset"]["version"] == "2.0"
    assert len(doc["meshes"]) == 5 and len(doc["nodes"]) == 5
    assert len(doc["materials"]) == 5
    assert doc["scenes"][0]["nodes"] == [0, 1, 2, 3, 4]

    # buffer integrity: decoded base64 length matches byteLength, and every
    # accessor's byte range lies inside the buffer
    raw = base64.b64decode(doc["buffers"][0]["uri"].split(",", 1)[1])
    assert len(raw) == doc["buffers"][0]["byteLength"]
    for acc in doc["accessors"]:
        bv = doc["bufferViews"][acc["bufferView"]]
        assert bv["byteOffset"] + bv["byteLength"] <= len(raw)

    # geometry content: 8 verts + 36 indices per box, positions sane
    pos = [a for a in doc["accessors"] if a["type"] == "VEC3"]
    idx = [a for a in doc["accessors"] if a["type"] == "SCALAR"]
    assert len(pos) == 5 and all(a["count"] == 8 for a in pos)
    assert len(idx) == 5 and all(a["count"] == 36 for a in idx)
    assert pos[0]["componentType"] == 5126 and idx[0]["componentType"] == 5125
    assert doc["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][3] == 1.0

    # cross-witness: trimesh reads our glTF back with the same 5 geometries
    scene = trimesh.load(dst)
    assert len(scene.geometry) == 5
