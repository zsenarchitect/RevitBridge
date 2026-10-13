"""Backend registry."""

from .aps_cloud import ApsCloudBackend
from .base import Backend, ConversionContext
from .ifcopenshell_backend import IfcOpenShellBackend
from .local_revit import LocalRevitBackend
from .mock import MockBackend

REGISTRY: dict[str, Backend] = {
    b.name: b
    for b in (MockBackend(), IfcOpenShellBackend(), LocalRevitBackend(), ApsCloudBackend())
}

__all__ = ["REGISTRY", "Backend", "ConversionContext"]
