"""Conversion orchestration: plan multi-hop routes, pick backends, run them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .backends import REGISTRY, ConversionContext
from .errors import ConversionError, UnsupportedFormatError
from .formats import canonical, format_from_path, route

#: Default backend per hop when the user does not choose one.
AUTO_BACKEND = {
    ("rvt", "ifc"): "local-revit",
    ("ifc", "glb"): "ifcopenshell",
    ("ifc", "gltf"): "ifcopenshell",
    ("ifc", "obj"): "ifcopenshell",
    ("ifc", "stl"): "ifcopenshell",
    ("ifc", "rvt"): "local-revit",
    ("obj", "rvt"): "local-revit",
    ("glb", "rvt"): "local-revit",
    ("gltf", "rvt"): "local-revit",
    # family-first: the primary X->Revit target
    ("ifc", "rfa"): "local-revit",
    ("obj", "rfa"): "local-revit",
    ("glb", "rfa"): "local-revit",
    ("gltf", "rfa"): "local-revit",
}


@dataclass
class Step:
    src_fmt: str
    dst_fmt: str
    backend_name: str


def plan(src_fmt: str, dst_fmt: str, backend: str | None = None) -> list[Step]:
    """Plan the hop list for src_fmt -> dst_fmt.

    With backend=None each hop gets its AUTO_BACKEND default; otherwise the
    named backend must support every hop or UnsupportedFormatError is raised.
    """
    hops = route(src_fmt, dst_fmt)
    steps: list[Step] = []
    for src, dst in hops:
        name = backend or AUTO_BACKEND.get((src, dst))
        if name is None:
            raise UnsupportedFormatError(f"No default backend for {src} -> {dst}")
        be = REGISTRY.get(name)
        if be is None:
            raise UnsupportedFormatError(f"Unknown backend: {name!r}")
        if not be.supports(src, dst):
            raise UnsupportedFormatError(
                f"Backend {name!r} cannot do {src} -> {dst}."
            )
        steps.append(Step(src, dst, name))
    return steps


def convert(
    src: str,
    dst: str,
    to: str | None = None,
    backend: str | None = None,
    dry_run: bool = False,
    workdir: str = "",
    options: dict | None = None,
) -> str:
    """Convert src to dst. Returns the output path.

    to: target format (default: inferred from dst's extension).
    Intermediate IFC files for multi-hop routes land in workdir.
    """
    src_fmt = format_from_path(src)
    dst_fmt = canonical(to) if to else format_from_path(dst)
    steps = plan(src_fmt, dst_fmt, backend=backend)

    current = src
    for i, step in enumerate(steps):
        last = i == len(steps) - 1
        hop_dst = dst if last else str(Path(workdir or ".") / f"_hop{i}_{Path(src).stem}.ifc")
        be = REGISTRY[step.backend_name]
        ctx = ConversionContext(
            src=current, dst=hop_dst,
            src_fmt=step.src_fmt, dst_fmt=step.dst_fmt,
            dry_run=dry_run, workdir=workdir, options=options or {},
        )
        try:
            current = be.convert(ctx)
        except ConversionError:
            raise
        except Exception as e:  # never leak a raw traceback without context
            raise ConversionError(f"{step.backend_name}: {src_fmt}->{dst_fmt} failed: {e}") from e
    return current
