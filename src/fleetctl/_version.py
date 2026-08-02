"""Distribution version lookup."""

from __future__ import annotations

from importlib import metadata

_FALLBACK_VERSION = "0.0.0+unknown"


def get_version() -> str:
    """Return the installed distribution version.

    **RETURNS:**
        `str`: The version recorded in the installed distribution metadata, or ``"0.0.0+unknown"`` when `fleetctl` is imported from a source tree with no distribution installed.  <br>
    """
    try:
        return metadata.version("fleetctl")
    except metadata.PackageNotFoundError:
        return _FALLBACK_VERSION
