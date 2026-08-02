"""Distribution version lookup.

Kept out of ``__init__.py`` so importing the package never executes code,
and guarded so that importing from a source tree without an installed
distribution degrades instead of raising. `fleetctl` is consumed as a
library as well as a CLI, and a metadata lookup failure must not take down
an embedding host.
"""

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
