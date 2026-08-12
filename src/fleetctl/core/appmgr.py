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

    def installed_abi(self, identifier: str) -> str:
        """Report the architecture an installed application actually runs as.

        Distinct from the device's own ABI list, and it is this that decides
        whether a compiled plugin loads: a process can only load libraries
        matching its own architecture, so a 64-bit build of an application on
        a device that also supports 32-bit still cannot load a 32-bit plugin.

        **PARAMETERS:**
            `identifier` (str): Platform-native application identifier.  <br>

        **RETURNS:**
            `str`: The architecture, or ``""`` when the application is absent or the platform does not distinguish one. Empty means "no answer", never "no restriction".  <br>
        """

    def install(self, package: Path, *, identifier: str = "") -> None:
        """Install an application package onto the device.

        **PARAMETERS:**
            `package` (Path): Local installable file, e.g. an APK.  <br>
            `identifier` (str): Platform-native identifier, where the pack needs it.  <br>

        **RAISES:**
            `TransportError`: If the transfer or installation failed.  <br>
        """

    def launch(self, identifier: str) -> None:
        """Bring an application to the foreground, starting it if needed.

        **PARAMETERS:**
            `identifier` (str): Platform-native application identifier.  <br>

        **RAISES:**
            `FleetError`: If the platform cannot launch an application this way.  <br>
            `TransportError`: If the launch command ran but the application is not running afterwards.  <br>
        """

    def stop(self, identifier: str) -> None:
        """Stop a running application so its files can be replaced safely.

        **PARAMETERS:**
            `identifier` (str): Platform-native application identifier.  <br>
        """
