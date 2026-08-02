"""Android implementation of the `state` verb.

Everything an app pack would otherwise have had to know lives here: where an
app's data directory is, how to build an archive that survives this device's
tooling, how much headroom an unpack needs, and how long to wait for it.

`apps/kodi` issues no `tar` command and knows no on-device path.
"""

from __future__ import annotations

import logging
import posixpath
import shlex
from pathlib import Path

from ...core.effects import Effect
from ...core.errors import FleetError, TransportError
from ...core.state import AppStateSpec
from ...core.transport.base import Transport
from .quirks import AndroidQuirks

LOGGER = logging.getLogger(__name__)

PLATFORM = "android"


class AndroidStateManager:
    """Snapshots and restores an app's state on an Android device.

    **PARAMETERS:**
        `transport` (Transport): Connection to the device.  <br>
        `quirks` (AndroidQuirks): Vendor deviations that apply to this device.  <br>
    """

    def __init__(self, transport: Transport, quirks: AndroidQuirks | None = None) -> None:
        self._transport = transport
        self._quirks = quirks or AndroidQuirks()

    @property
    def platform(self) -> str:
        """RETURNS: str: Always ``android``."""
        return PLATFORM

    def state_root(self, spec: AppStateSpec) -> str:
        """Resolve where an app's state lives on this device.

        **PARAMETERS:**
            `spec` (AppStateSpec): The app, which supplies its own package identifier.  <br>

        **RETURNS:**
            `str`: Absolute on-device path.  <br>
        """
        package = spec.identifier_for(PLATFORM)
        return posixpath.join(self._quirks.app_data_root, package, "files", *([spec.app_root] if spec.app_root else []))

    def snapshot(self, spec: AppStateSpec, destination: Path) -> Path:
        """Trim, archive, and retrieve the app's state.

        **RETURNS:**
            `Path`: `destination`.  <br>

        **RAISES:**
            `TransportError`: If the archive could not be built or retrieved.  <br>
        """
        root = self.state_root(spec)
        staged = posixpath.join(self._quirks.external_storage, destination.name)
        plain = _plain(staged)

        for relative in spec.exclude:
            self._transport.exec_ok(f"rm -rf {shlex.quote(posixpath.join(root, relative))}", effect=Effect.DESTRUCTIVE)

        parent, leaf = posixpath.split(root.rstrip("/"))
        timeout = self._transfer_timeout()
        self._transport.exec_ok(f"rm -f {shlex.quote(staged)} {shlex.quote(plain)}", effect=Effect.DESTRUCTIVE)

        if self._quirks.split_gzip:
            self._transport.exec(f"tar cf {shlex.quote(plain)} -C {shlex.quote(parent)} {shlex.quote(leaf)}", timeout_s=timeout)
            self._transport.exec(f"gzip {shlex.quote(plain)}", timeout_s=timeout)
        else:
            self._transport.exec(f"tar czf {shlex.quote(staged)} -C {shlex.quote(parent)} {shlex.quote(leaf)}", timeout_s=timeout)

        self._transport.get(staged, destination)
        self._transport.exec_ok(f"rm -f {shlex.quote(staged)}", effect=Effect.DESTRUCTIVE)
        return destination

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        """Push `archive` and replace the app's state with its contents.

        The archive must be flat — the app's `members` at its root — so it
        extracts straight into the state root with no path rewriting.

        **RAISES:**
            `FleetError`: If the device lacks free space to unpack it.  <br>
            `TransportError`: If the transfer or extraction failed.  <br>
        """
        root = self.state_root(spec)
        size = archive.stat().st_size
        self._require_space(size)

        staged = posixpath.join(self._quirks.external_storage, archive.name)
        plain = _plain(staged)
        timeout = self._unpack_timeout(size)

        self._transport.exec_ok(f"rm -f {shlex.quote(staged)} {shlex.quote(plain)}", effect=Effect.DESTRUCTIVE)
        self._transport.put(archive, staged, effect=Effect.DESTRUCTIVE)

        if self._quirks.split_gzip:
            self._transport.exec(f"gzip -d {shlex.quote(staged)}", timeout_s=timeout)
            unpack_from = plain
        else:
            unpack_from = staged

        for member in spec.members:
            self._transport.exec_ok(f"rm -rf {shlex.quote(posixpath.join(root, member))}", effect=Effect.DESTRUCTIVE)
        self._transport.exec(f"mkdir -p {shlex.quote(root)}")

        extract = "tar xf" if self._quirks.split_gzip else "tar xzf"
        self._transport.exec(f"{extract} {shlex.quote(unpack_from)} -C {shlex.quote(root)}", timeout_s=timeout)
        self._transport.exec_ok(f"rm -f {shlex.quote(unpack_from)}", effect=Effect.DESTRUCTIVE)

        self._verify(root, spec)

    def _verify(self, root: str, spec: AppStateSpec) -> None:
        """Fail loudly if extraction left the state unusable.

        `tar` exiting cleanly is not proof the payload arrived: a truncated
        archive extracts "successfully" into a half-populated tree, which the
        app then starts against and rebuilds from scratch.
        """
        for member in spec.members:
            listing = self._transport.exec_ok(f"ls {shlex.quote(posixpath.join(root, member))}", effect=Effect.READ)
            if not listing.strip():
                raise TransportError(f"Restore verification failed: {root}/{member} is missing or empty", target=self._transport.target)

    def _require_space(self, archive_size: int) -> None:
        free = self._transport.free_bytes(self._quirks.external_storage)
        needed = int(archive_size * self._quirks.disk_headroom)
        if free and free < needed:
            raise FleetError(f"Not enough free space on {self._transport.target}: need ~{needed // (1024 * 1024)}MB, {free // (1024 * 1024)}MB available")

    def _unpack_timeout(self, archive_size: int) -> float:
        """Scale the timeout by payload size. A flat timeout is how the
        predecessor silently truncated archives on slower devices."""
        return max(self._transfer_timeout(), archive_size / self._quirks.min_unpack_bytes_per_s)

    def _transfer_timeout(self) -> float:
        return 180.0


def _plain(archive_path: str) -> str:
    """RETURNS: str: The path with a trailing ``.gz`` removed."""
    return archive_path.removesuffix(".gz")
