"""RevitBridge: open-source toolkit for converting between Revit (RVT) and open 3D formats.

Honest scope: RVT geometry is only readable through Autodesk tooling
(local Revit + Revit API, or APS Design Automation in the cloud).
Everything this package claims is tagged proven / scaffolded / not-feasible
in the README capability matrix, and the test suite only covers what can run
without Revit or APS credentials.
"""

__version__ = "0.1.0"

from .errors import BackendUnavailableError, ConversionError, UnsupportedFormatError

__all__ = [
    "__version__",
    "BackendUnavailableError",
    "ConversionError",
    "UnsupportedFormatError",
]
