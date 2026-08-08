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
