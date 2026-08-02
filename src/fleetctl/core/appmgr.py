"""The `apps` verb: what is installed on a device, and putting things there.

The same shape as `state`, and for the same reason. An app pack knows *which*
package it cares about and *which* artifact should be installed; a device
pack knows how packages are queried and installed on that platform.

Without this, an app pack reaching for `pm install` would have to import a
device pack — which is the ring violation this seam exists to prevent, and
which slipped in once before being caught.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AppManager(Protocol):
    """Queries and installs applications on a device.

    Implemented by device packs, handed to steps on their context.
    """

    def installed_version(self, identifier: str) -> str:
        """Report the installed version of an application.

        **PARAMETERS:**
            `identifier` (str): Platform-native application identifier.  <br>

        **RETURNS:**
            `str`: The version string, or ``""`` when the application is absent. Absence is not an error — "not installed" is a normal answer.  <br>
        """

    def install(self, package: Path, *, identifier: str = "") -> None:
        """Install an application package onto the device.

        Staging, transfer and cleanup are the device pack's business; the
        caller supplies a local file and nothing else.

        **PARAMETERS:**
            `package` (Path): Local installable file, e.g. an APK.  <br>
            `identifier` (str): Platform-native identifier, where the pack needs it.  <br>

        **RAISES:**
            `TransportError`: If the transfer or installation failed.  <br>
        """

    def stop(self, identifier: str) -> None:
        """Stop a running application so its files can be replaced safely.

        **PARAMETERS:**
            `identifier` (str): Platform-native application identifier.  <br>
        """
