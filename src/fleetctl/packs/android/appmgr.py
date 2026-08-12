"""Android implementation of the `apps` verb."""

from __future__ import annotations

import logging
import posixpath
import shlex
from pathlib import Path

from ...core.effects import Effect
from ...core.errors import TransportError
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

    def installed_abi(self, identifier: str) -> str:
        """RETURNS: str: The package's `primaryCpuAbi`, or ``""`` when it is absent or carries no native code."""
        return actions.installed_abi(self._transport, identifier)

    def install(self, package: Path, *, identifier: str = "") -> None:
        """Stage an APK on the device, install it, verify it, and clean up.

        **PARAMETERS:**
            `package` (Path): Local APK.  <br>
            `identifier` (str): Package name to confirm afterwards. Empty skips the confirmation, which is the caller declining the only evidence available.  <br>

        **RAISES:**
            `TransportError`: If the transfer failed, or the package is absent afterwards.  <br>
        """
        remote = posixpath.join(self._quirks.apk_staging_dir, package.name)
        self._transport.exec_ok(f"rm -f {shlex.quote(remote)}", effect=Effect.DESTRUCTIVE)
        self._transport.put(package, remote, effect=Effect.DESTRUCTIVE)
        try:
            actions.install_package(self._transport, remote)
        finally:
            self._transport.exec_ok(f"rm -f {shlex.quote(remote)}", effect=Effect.DESTRUCTIVE)

        # `pm install` reports failure on stdout and the transport cannot read
        # an exit status, so a failed install is indistinguishable from a
        # successful one at the command layer. Re-reading the package list is
        # the only honest evidence that anything happened.
        if identifier and not self.installed_version(identifier):
            raise TransportError(f"Install reported no error but {identifier} is not present afterwards", target=self._transport.target)

    def launch(self, identifier: str) -> None:
        """Bring a package to the foreground, starting it if needed.

        **PARAMETERS:**
            `identifier` (str): Package name.  <br>

        **RAISES:**
            `TransportError`: If the package exposes no launchable activity, or has no process afterwards. `am start` reports failure on stdout and the transport cannot read an exit status, so re-reading is the only evidence available.  <br>
        """
        component = actions.launch_activity(self._transport, identifier)
        if not component:
            raise TransportError(f"{identifier} exposes no launchable activity", target=self._transport.target)

        actions.start_app(self._transport, component)
        if not actions.is_running(self._transport, identifier):
            raise TransportError(f"Started {component} but {identifier} has no process afterwards", target=self._transport.target)

    def stop(self, identifier: str) -> None:
        """Force-stop a package so its files can be replaced safely."""
        actions.stop_app(self._transport, identifier)
