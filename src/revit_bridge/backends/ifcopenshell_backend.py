"""IFC -> mesh backend (IfcOpenShell). Status: proven.

Tessellates IFC products with IfcOpenShell's geometry kernel and writes
OBJ / STL / GLB / glTF. This is the only backend that runs anywhere;
everything RVT-side funnels through IFC first.
"""

from __future__ import annotations

import numpy as np

from ..errors import BackendUnavailableError, ConversionError
from ..formats import MESH_FORMATS
from .base import Backend, ConversionContext

_CLASS_COLORS = {
    "IfcWall": (0.82, 0.82, 0.80),
    "IfcSlab": (0.62, 0.62, 0.60),
    "IfcColumn": (0.75, 0.72, 0.68),
    "IfcBeam": (0.75, 0.72, 0.68),
    "IfcDoor": (0.55, 0.38, 0.25),
    "IfcWindow": (0.55, 0.75, 0.85),
    "IfcRoof": (0.60, 0.30, 0.25),
}
_DEFAULT_COLOR = (0.70, 0.70, 0.70)


def _require_ifcopenshell():
    try:
        import ifcopenshell
        import ifcopenshell.geom  # noqa: F401
    except ImportError as e:
        raise BackendUnavailableError(
            "The 'ifcopenshell' backend needs the IfcOpenShell Python package: "
            "pip install ifcopenshell"
        ) from e
    return ifcopenshell


def tessellate(ifc_path: str) -> list[dict]:
    """Tessellate every geometric product. Returns mesh dicts.

    Each dict: {name, guid, ifc_class, vertices (Nx3 float64), faces (Mx3 int32),
    color (r,g,b)}. Faces are triangles; vertices are in world coordinates.
    """
    ifcopenshell = _require_ifcopenshell()
    model = ifcopenshell.open(ifc_path)
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    meshes: list[dict] = []
    for el in model.by_type("IfcProduct"):
        if not getattr(el, "Representation", None):
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, el)
        except Exception:
            continue  # some products have no tessellatable representation
        verts = np.asarray(shape.geometry.verts, dtype=np.float64).reshape(-1, 3)
        faces = np.asarray(shape.geometry.faces, dtype=np.int32).reshape(-1, 3)
        if len(faces) == 0:
            continue
        meshes.append(
            {
                "name": f"{el.is_a()}_{getattr(el, 'Name', None) or el.GlobalId}",
                "guid": getattr(el, "GlobalId", ""),
                "ifc_class": el.is_a(),
                "vertices": verts,
                "faces": faces,
                "color": _CLASS_COLORS.get(el.is_a(), _DEFAULT_COLOR),
            }
        )
    if not meshes:
        raise ConversionError(f"No tessellatable geometry found in {ifc_path}")
    return meshes


def write_obj(meshes: list[dict], path: str) -> str:
    lines = ["# RevitBridge OBJ export (IfcOpenShell tessellation)"]
    mtl_name = path.rsplit(".", 1)[0] + ".mtl"
    lines.append(f"mtllib {mtl_name.rsplit('/', 1)[-1]}")
    mtl = []
    v_offset = 1
    for i, m in enumerate(meshes):
        mat = f"mat_{i}"
        lines.append(f"o {m['name']}")
        lines.append(f"usemtl {mat}")
        for v in m["vertices"]:
            lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
        for tri in m["faces"]:
            a, b, c = tri + v_offset
            lines.append(f"f {a} {b} {c}")
        v_offset += len(m["vertices"])
        r, g, b = m["color"]
        mtl.append(f"newmtl {mat}\nKd {r:.3f} {g:.3f} {b:.3f}\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(mtl_name, "w", encoding="utf-8") as fh:
        fh.write("".join(mtl))
    return path


def write_stl(meshes: list[dict], path: str) -> str:
    out = ["solid revitbridge"]
    for m in meshes:
        v = m["vertices"]
        for tri in m["faces"]:
            p0, p1, p2 = v[tri[0]], v[tri[1]], v[tri[2]]
            n = np.cross(p1 - p0, p2 - p0)
            norm = np.linalg.norm(n)
            n = n / norm if norm > 0 else np.array([0.0, 0.0, 1.0])
            out.append(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}")
            out.append("    outer loop")
            for p in (p0, p1, p2):
                out.append(f"      vertex {p[0]:.6e} {p[1]:.6e} {p[2]:.6e}")
            out.append("    endloop")
            out.append("  endfacet")
    out.append("endsolid revitbridge")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return path


def write_glb(meshes: list[dict], path: str) -> str:
    try:
        import trimesh
    except ImportError as e:
        raise BackendUnavailableError(
            "GLB export needs the 'trimesh' package: pip install trimesh"
        ) from e
    scene = trimesh.Scene()
    for m in meshes:
        r, g, b = (int(c * 255) for c in m["color"])
        colors = np.tile([r, g, b, 255], (len(m["vertices"]), 1)).astype(np.uint8)
        mesh = trimesh.Trimesh(
            vertices=m["vertices"], faces=m["faces"], vertex_colors=colors,
            process=False,
        )
        scene.add_geometry(mesh, geom_name=m["name"])
    data = scene.export(file_type="glb")
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, (bytes, bytearray)) else bytes(data))
    return path


def write_gltf(meshes: list[dict], path: str) -> str:
    """Write glTF 2.0 JSON (.gltf) with an embedded base64 buffer.

    Hand-rolled minimal writer: one buffer, per-mesh POSITION (float32 VEC3)
    + indices (uint32 SCALAR) bufferViews, one pbrMetallicRoughness material
    per mesh carrying the IFC-class color. No external glTF dependency.
    """
    import base64
    import json

    from .. import __version__

    buf = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes_json: list[dict] = []
    materials: list[dict] = []

    ARRAY_BUFFER = 34962
    ELEMENT_ARRAY_BUFFER = 34963
    FLOAT = 5126
    UNSIGNED_INT = 5125

    for mi, m in enumerate(meshes):
        verts = np.asarray(m["vertices"], dtype=np.float32)
        faces = np.asarray(m["faces"], dtype=np.uint32).reshape(-1)

        pos_off = len(buf)
        buf += verts.tobytes()
        pos_view = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": pos_off,
                             "byteLength": verts.nbytes, "target": ARRAY_BUFFER})
        pos_acc = len(accessors)
        accessors.append({"bufferView": pos_view, "componentType": FLOAT,
                          "count": int(len(verts)), "type": "VEC3",
                          "min": [float(x) for x in verts.min(axis=0)],
                          "max": [float(x) for x in verts.max(axis=0)]})

        idx_off = len(buf)
        buf += faces.tobytes()
        idx_view = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": idx_off,
                             "byteLength": faces.nbytes, "target": ELEMENT_ARRAY_BUFFER})
        idx_acc = len(accessors)
        accessors.append({"bufferView": idx_view, "componentType": UNSIGNED_INT,
                          "count": int(faces.size), "type": "SCALAR"})

        r, g, b = (float(c) for c in m["color"])
        materials.append({"name": f"mat_{mi}", "pbrMetallicRoughness": {
            "baseColorFactor": [r, g, b, 1.0],
            "metallicFactor": 0.0, "roughnessFactor": 0.9}})

        meshes_json.append({"name": m["name"], "primitives": [{
            "attributes": {"POSITION": pos_acc}, "indices": idx_acc,
            "material": mi}]})

    doc = {
        "asset": {"version": "2.0", "generator": f"RevitBridge {__version__}"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(meshes_json)))}],
        "nodes": [{"mesh": i, "name": meshes[i]["name"]} for i in range(len(meshes_json))],
        "meshes": meshes_json,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(buf),
                     "uri": "data:application/octet-stream;base64,"
                            + base64.b64encode(bytes(buf)).decode("ascii")}],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


class IfcOpenShellBackend(Backend):
    name = "ifcopenshell"
    title = "IfcOpenShell (local)"
    status = "proven"
    note = "IFC -> OBJ/STL/GLB/glTF via IfcOpenShell tessellation. Tested in CI."

    def supports(self, src_fmt: str, dst_fmt: str) -> bool:
        return src_fmt == "ifc" and dst_fmt in MESH_FORMATS

    def check_available(self) -> None:
        _require_ifcopenshell()

    def convert(self, ctx: ConversionContext) -> str:
        self.check_available()
        meshes = tessellate(ctx.src)
        if ctx.dst_fmt == "obj":
            return write_obj(meshes, ctx.dst)
        if ctx.dst_fmt == "stl":
            return write_stl(meshes, ctx.dst)
        if ctx.dst_fmt == "glb":
            return write_glb(meshes, ctx.dst)
        if ctx.dst_fmt == "gltf":
            return write_gltf(meshes, ctx.dst)
        raise ConversionError(f"ifcopenshell backend cannot write {ctx.dst_fmt}")
