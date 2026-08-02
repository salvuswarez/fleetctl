"""Android implementation of the `apps` verb."""

from __future__ import annotations

import logging
import posixpath
import shlex
from pathlib import Path

from ...core.effects import Effect
from ...core.transport.base import Transport
from . import actions
from .quirks import AndroidQuirks

LOGGER = logging.getLogger(__name__)


class AndroidAppManager:
    """Queries and installs Android packages.

    **PARAMETERS:**
        `transport` (Transport): Connection to the device.  <br>
        `quirks` (AndroidQuirks): Vendor deviations, notably where to stage a transfer.  <br>
    """

    def __init__(self, transport: Transport, quirks: AndroidQuirks | None = None) -> None:
        self._transport = transport
        self._quirks = quirks or AndroidQuirks()

    def installed_version(self, identifier: str) -> str:
        """RETURNS: str: The package's `versionName`, or ``""`` when it is not installed."""
        return actions.installed_version(self._transport, identifier)

    def install(self, package: Path, *, identifier: str = "") -> None:
        """Stage an APK on the device, install it, and clean up.

        Staging through external storage rather than installing in place:
        `pm install` reads a path on the device, so the file has to get there
        first, and leaving it behind would waste space a stick does not have.

        **RAISES:**
            `TransportError`: If the transfer or the install failed.  <br>
        """
        remote = posixpath.join(self._quirks.external_storage, package.name)
        self._transport.exec_ok(f"rm -f {shlex.quote(remote)}", effect=Effect.DESTRUCTIVE)
        self._transport.put(package, remote, effect=Effect.DESTRUCTIVE)
        try:
            actions.install_package(self._transport, remote)
        finally:
            self._transport.exec_ok(f"rm -f {shlex.quote(remote)}", effect=Effect.DESTRUCTIVE)

    def stop(self, identifier: str) -> None:
        """Force-stop a package so its files can be replaced safely."""
        actions.stop_app(self._transport, identifier)
