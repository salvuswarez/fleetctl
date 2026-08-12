"""Flatpak implementation of the `apps` verb.

Flatpak rather than a distribution package manager: it is how a desktop
application is installed on an image-based host, where the root filesystem is
read-only and `pacman`/`apt` cannot write to it at all.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path

from ...core.effects import Effect
from ...core.errors import FleetError
from ...core.transport.base import Transport

LOGGER = logging.getLogger(__name__)


class FlatpakAppManager:
    """Queries and stops Flatpak applications on a POSIX host.

    **PARAMETERS:**
        `transport` (Transport): Connection to the host.  <br>
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def installed_version(self, identifier: str) -> str:
        """Report the installed version of a Flatpak application.

        Parses the ``Version:`` line of ``flatpak info`` rather than using
        ``--show-version``: that option is not accepted by the Flatpak on
        SteamOS 3.8, where it produces no output at all. Combined with
        `exec_ok` swallowing the failure, it reported an installed Kodi as
        absent — verified on hardware 2026-08-06.

        **PARAMETERS:**
            `identifier` (str): Flathub application id, e.g. ``tv.kodi.Kodi``.  <br>

        **RETURNS:**
            `str`: The version string, or ``""`` when the application is absent. Absence is a normal answer, not an error.  <br>
        """
        output = self._transport.exec_ok(f"flatpak info {shlex.quote(identifier)}", effect=Effect.READ)
        for line in output.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip().lower() == "version":
                return value.strip()
        return ""

    def installed_abi(self, identifier: str) -> str:
        """Report the architecture a Flatpak application runs as.

        Reads `flatpak info`'s ``Arch:`` line. Flatpak resolves a runtime to
        the host architecture when it installs, so this rarely differs from the
        host — but it is read rather than assumed, because a manually installed
        32-bit branch on a 64-bit host would otherwise go unnoticed.

        **PARAMETERS:**
            `identifier` (str): Flathub application id.  <br>

        **RETURNS:**
            `str`: The architecture, e.g. ``x86_64``, or ``""`` when the application is absent.  <br>
        """
        output = self._transport.exec_ok(f"flatpak info {shlex.quote(identifier)}", effect=Effect.READ)
        for line in output.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip().lower() == "arch":
                return value.strip()
        return ""

    def launch(self, identifier: str) -> None:
        """Not supported: a graphical Flatpak does not start from a bare SSH session.

        `flatpak run` needs a session bus and a display the SSH session does
        not have, and on this hardware the application is started by the game
        launcher rather than directly. Raising says so; starting a process that
        immediately dies would report success for a black screen.

        **RAISES:**
            `FleetError`: Always.  <br>
        """
        raise FleetError(
            f"Launching {identifier} over SSH is not supported: a Flatpak application needs a session bus and display, "
            "and on this platform it is started by the desktop or game launcher",
        )

    def install(self, package: Path, *, identifier: str = "") -> None:
        """Not supported: a Flatpak is installed from a remote, not a local file.

        **RAISES:**
            `FleetError`: Always. Declaring this unsupported is deliberate — silently doing nothing would let a base-image install step report success having installed nothing.  <br>
        """
        raise FleetError(
            "Installing a Flatpak from a local package file is not supported; " "applications come from a configured remote such as Flathub",
        )

    def stop(self, identifier: str) -> None:
        """Stop a running application so its files can be replaced safely.

        **PARAMETERS:**
            `identifier` (str): Flathub application id.  <br>
        """
        # `flatpak kill` exits non-zero when the app is not running, which is
        # the normal case before a deploy, so failure here is not an error.
        self._transport.exec_ok(f"flatpak kill {shlex.quote(identifier)}", effect=Effect.MUTATING)
