"""CLI: revit-convert INPUT --to FORMAT [--backend NAME] [--out PATH] ..."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .backends import REGISTRY
from .errors import ConversionError
from .formats import OUTPUT_FORMATS, canonical, format_from_path
from .pipeline import convert, plan


def _list_backends() -> int:
    print(f"{'backend':<14}{'status':<11}supports")
    for name, be in REGISTRY.items():
        hops = []
        for s in ("rvt", "rfa", "ifc", "obj", "glb", "gltf", "stl"):
            for d in sorted(OUTPUT_FORMATS):
                if be.supports(s, d):
                    hops.append(f"{s}->{d}")
        print(f"{name:<14}{be.status:<11}{', '.join(hops)}")
        print(f"{'':<14}  {be.note}")
    return 0


def _probe(path: str) -> int:
    from .rvt_probe import probe

    try:
        res = probe(path)
    except Exception as e:
        print(f"probe failed: {e}", file=sys.stderr)
        return 2
    print(json.dumps({
        "path": res.path,
        "is_revit_container": res.is_revit_container,
        "version": res.version,
        "build": res.build,
        "original_path": res.original_path,
        "streams": res.streams,
        "part_atom": res.part_atom,
        "schema_classes": res.schema_classes,
        "schema_sample": res.schema_sample,
        "preview_png_bytes": len(res.preview_png) if res.preview_png else 0,
        "notes": res.notes,
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="revit-convert",
        description="Open-source Revit <-> 3D format converter (honest edition).",
    )
    p.add_argument("input", nargs="?", help="Input file (.rvt/.rfa/.ifc/.obj/...)")
    p.add_argument("--to", dest="to", help=f"Target format: {sorted(OUTPUT_FORMATS)}")
    p.add_argument("--backend", help="Backend: " + ", ".join(REGISTRY))
    p.add_argument("--out", help="Output path (default: <input-stem>.<to>)")
    p.add_argument("--dry-run", action="store_true",
                   help="Generate artifacts without executing (local-revit bundle)")
    p.add_argument("--workdir", default="", help="Scratch dir for intermediate files")
    p.add_argument("--opt", action="append", default=[],
                   help="Backend option key=value (repeatable)")
    p.add_argument("--probe", action="store_true",
                   help="Static RVT probe: version/streams/preview/schema, no conversion")
    p.add_argument("--list-backends", action="store_true", help="Show backends and status")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_backends:
        return _list_backends()
    if not args.input:
        print("error: INPUT is required (or use --list-backends)", file=sys.stderr)
        return 2
    if args.probe:
        return _probe(args.input)
    if not args.to:
        print("error: --to FORMAT is required", file=sys.stderr)
        return 2
    dst_fmt = canonical(args.to)
    out = args.out or f"{args.input.rsplit('.', 1)[0]}.{dst_fmt}"
    options = dict(o.split("=", 1) for o in args.opt if "=" in o)
    try:
        if not args.backend:
            # show the plan first so users see which hop needs what
            steps = plan(format_from_path(args.input), dst_fmt)
            print("plan: " + " -> ".join(f"{s.src_fmt}>{s.dst_fmt}[{s.backend_name}]" for s in steps))
        result = convert(args.input, out, to=dst_fmt, backend=args.backend,
                         dry_run=args.dry_run, workdir=args.workdir, options=options)
    except ConversionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"wrote {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
