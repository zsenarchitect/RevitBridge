"""Mock backend: exercises the pipeline without converting any geometry.

Writes a JSON manifest describing what WOULD have been converted. Used by
CI and by developers wiring the pipeline on machines without Revit/APS.
"""

from __future__ import annotations

import json

from ..formats import INPUT_FORMATS, OUTPUT_FORMATS
from .base import Backend, ConversionContext


class MockBackend(Backend):
    name = "mock"
    title = "Mock (no-op)"
    status = "proven"
    note = "Pipeline test double. Converts nothing; writes a manifest instead."

    def supports(self, src_fmt: str, dst_fmt: str) -> bool:
        return src_fmt in INPUT_FORMATS and dst_fmt in OUTPUT_FORMATS

    def convert(self, ctx: ConversionContext) -> str:
        manifest = {
            "backend": self.name,
            "mock": True,
            "src": ctx.src,
            "dst": ctx.dst,
            "src_fmt": ctx.src_fmt,
            "dst_fmt": ctx.dst_fmt,
            "note": "Mock output: no geometry was converted.",
        }
        with open(ctx.dst, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
        return ctx.dst
