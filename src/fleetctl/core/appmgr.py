"""The `apps` verb: what is installed on a device, and putting things there."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AppManager(Protocol):
    """Queries and installs applications on a device."""

    def installed_version(self, identifier: str) -> str:
        """Report the installed version of an application.

        **PARAMETERS:**
            `identifier` (str): Platform-native application identifier.  <br>

        **RETURNS:**
            `str`: The version string, or ``""`` when the application is absent. Absence is not an error — "not installed" is a normal answer.  <br>
        """

    def install(self, package: Path, *, identifier: str = "") -> None:
        """Install an application package onto the device.

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
