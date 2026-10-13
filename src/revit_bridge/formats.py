"""Format registry: canonical names, supported routes, honesty metadata."""

from .errors import UnsupportedFormatError

#: Formats we can read as conversion inputs.
INPUT_FORMATS = frozenset({"rvt", "rfa", "rte", "rft", "ifc", "glb", "gltf", "obj", "stl"})

#: Formats we can write as conversion outputs.
OUTPUT_FORMATS = frozenset({"ifc", "glb", "gltf", "obj", "stl", "step"})

#: Revit-native family of extensions (all share the OLE/CFB container).
REVIT_FORMATS = frozenset({"rvt", "rfa", "rte", "rft"})

#: Mesh formats produced from IFC tessellation (triangles only, no B-rep).
MESH_FORMATS = frozenset({"glb", "gltf", "obj", "stl"})

#: Every route is a list of (src_fmt, dst_fmt) hops through IFC as the hub.
#: Routes marked via_ifc need a working RVT->IFC step first.
ROUTES = {
    ("rvt", "ifc"): [("rvt", "ifc")],
    ("rfa", "ifc"): [("rvt", "ifc")],
    ("rvt", "glb"): [("rvt", "ifc"), ("ifc", "glb")],
    ("rvt", "gltf"): [("rvt", "ifc"), ("ifc", "gltf")],
    ("rvt", "obj"): [("rvt", "ifc"), ("ifc", "obj")],
    ("rvt", "stl"): [("rvt", "ifc"), ("ifc", "stl")],
    ("ifc", "glb"): [("ifc", "glb")],
    ("ifc", "gltf"): [("ifc", "gltf")],
    ("ifc", "obj"): [("ifc", "obj")],
    ("ifc", "stl"): [("ifc", "stl")],
    # The hard direction: mesh -> RVT via the Revit API (DirectShape).
    # Genuinely limited: dumb geometry, no parametric round-trip. See README.
    ("ifc", "rvt"): [("ifc", "rvt")],
    ("obj", "rvt"): [("obj", "rvt")],
    ("glb", "rvt"): [("glb", "rvt")],
}


def canonical(ext: str) -> str:
    """Normalize a file extension or format name, e.g. '.RVT' -> 'rvt'."""
    return ext.strip().lower().lstrip(".")


def format_from_path(path: str) -> str:
    """Infer the canonical format from a file path's extension."""
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    fmt = canonical(ext)
    if fmt not in INPUT_FORMATS and fmt not in OUTPUT_FORMATS:
        raise UnsupportedFormatError(f"Unknown format for file: {path!r}")
    return fmt


def route(src_fmt: str, dst_fmt: str):
    """Return the hop list for src -> dst, or raise UnsupportedFormatError."""
    src_fmt, dst_fmt = canonical(src_fmt), canonical(dst_fmt)
    if src_fmt == dst_fmt:
        raise UnsupportedFormatError(f"Source and target are both {src_fmt}; nothing to convert.")
    # STEP: tessellated meshes cannot become real STEP B-rep. Not feasible in v1.
    if dst_fmt == "step":
        raise UnsupportedFormatError(
            "STEP output is not feasible in v1: our pipeline tessellates IFC into "
            "triangles, and triangles do not make a valid STEP boundary-rep. "
            "True STEP export needs OpenCASCADE B-rep reconstruction (roadmap)."
        )
    key = (src_fmt, dst_fmt)
    # rfa/rte/rft behave like rvt for every route
    if key not in ROUTES and src_fmt in REVIT_FORMATS:
        key = ("rvt", dst_fmt)
    if key not in ROUTES:
        raise UnsupportedFormatError(
            f"No conversion route {src_fmt} -> {dst_fmt}. "
            f"Supported outputs: {sorted(OUTPUT_FORMATS)}."
        )
    return ROUTES[key]
