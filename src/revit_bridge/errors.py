"""Exception types for RevitBridge."""


class ConversionError(Exception):
    """A conversion step failed. Carries what was attempted and why."""


class UnsupportedFormatError(ConversionError):
    """The requested format pair has no conversion route."""


class BackendUnavailableError(ConversionError):
    """The chosen backend cannot run in this environment.

    The message always says exactly what is missing and how to fix it,
    e.g. "needs Windows + Revit installed" or "set APS_CLIENT_ID".
    """
