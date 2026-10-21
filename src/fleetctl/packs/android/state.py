"""Android implementation of the `state` verb."""

from __future__ import annotations

import logging
import posixpath
import shlex
from pathlib import Path

from fleetctl.core.effects import Effect
from fleetctl.core.errors import CommandFailedError, FleetError, TransportError
from fleetctl.core.state import AppStateSpec
from fleetctl.core.transport.base import Transport
from fleetctl.packs.android.quirks import AndroidQuirks

LOGGER = logging.getLogger(__name__)

PLATFORM = "android"
_DONE = "__fleetctl_done__"


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
        app_root = spec.root_for(PLATFORM)
        return posixpath.join(self._quirks.app_data_root, package, "files", *([app_root] if app_root else []))

    def snapshot(self, spec: AppStateSpec, destination: Path) -> Path:
        """Trim, archive, and retrieve the app's state.

        The staging archive is removed however this exits. Failed captures that
        left theirs behind filled a SHIELD's 12GB of external storage with
        fourteen of them, and a full disk is what made the next one fail.

        **RETURNS:**
            `Path`: `destination`.  <br>

        **RAISES:**
            `FleetError`: If the device lacks free space to build the archive.  <br>
            `TransportError`: If the archive could not be built or retrieved.  <br>
        """
        root = self.state_root(spec)
        staged = posixpath.join(self._quirks.external_storage, destination.name)
        plain = _plain(staged)

        for relative in spec.exclude:
            self._transport.exec_ok(f"rm -rf {shlex.quote(posixpath.join(root, relative))}", effect=Effect.DESTRUCTIVE)

        parent, leaf = posixpath.split(root.rstrip("/"))
        timeout = self._transfer_timeout()
        self._discard(staged, plain)
        # Split gzip holds the plain tar and its compressed copy at once.
        self._require_free(self._footprint(root) * (2 if self._quirks.split_gzip else 1))

        try:
            if self._quirks.split_gzip:
                self._run_checked(f"tar cf {shlex.quote(plain)} -C {shlex.quote(parent)} {shlex.quote(leaf)}", timeout)
                self._run_checked(f"gzip {shlex.quote(plain)}", timeout)
            else:
                self._run_checked(f"tar czf {shlex.quote(staged)} -C {shlex.quote(parent)} {shlex.quote(leaf)}", timeout)
            self._transport.get(staged, destination)
        finally:
            self._discard(staged, plain)
        return destination

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        """Push `archive` and replace the app's state with its contents.

        **RAISES:**
            `FleetError`: If the device lacks free space to unpack it.  <br>
            `TransportError`: If the transfer or extraction failed.  <br>
        """
        root = self.state_root(spec)
        size = archive.stat().st_size
        self._require_free(int(size * self._quirks.disk_headroom))

        staged = posixpath.join(self._quirks.external_storage, archive.name)
        plain = _plain(staged)
        timeout = self._unpack_timeout(size)

        self._discard(staged, plain)
        try:
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
        finally:
            self._discard(staged, plain)

        self._verify(root, spec)

    def _verify(self, root: str, spec: AppStateSpec) -> None:
        """Fail loudly if extraction left the state unusable.

        Counts entries rather than reading `ls` output directly: a failed `ls`
        writes "No such file or directory" to the merged stream, which is
        *non-empty*, so testing for empty output treats a missing directory as
        proof it exists. Stderr is discarded and the count is parsed, so the
        only thing that can satisfy this is a directory with contents.
        """
        for member in spec.members:
            path = shlex.quote(posixpath.join(root, member))
            counted = self._transport.exec_ok(f"ls -1 {path} 2>/dev/null | wc -l", effect=Effect.READ).strip()
            entries = int(counted) if counted.isdigit() else 0
            if not entries:
                raise TransportError(f"Restore verification failed: {root}/{member} is missing or empty", target=self._transport.target)

    def _require_free(self, needed: int) -> None:
        free = self._transport.free_bytes(self._quirks.external_storage)
        if free and free < needed:
            raise FleetError(f"Not enough free space on {self._transport.target}: need ~{needed // (1024 * 1024)}MB, {free // (1024 * 1024)}MB available")

    def _footprint(self, root: str) -> int:
        """RETURNS: int: Bytes the tree at `root` occupies, or 0 when `du` cannot say — which skips the check rather than refusing."""
        fields = self._transport.exec_ok(f"du -sk {shlex.quote(root)}", effect=Effect.READ, timeout_s=self._transfer_timeout()).split()
        return int(fields[0]) * 1024 if fields and fields[0].isdigit() else 0

    def _run_checked(self, command: str, timeout: float) -> None:
        """Run an archive command and raise unless it exited 0.

        ADB's shell reports no exit status, so a `tar` that ran out of space
        returns its complaint as ordinary output. That left a truncated 1.45GB
        `.tar` on a full SHIELD and surfaced only at the pull, as "No such file
        or directory". A marker chained on `&&` makes the exit status visible.
        """
        output = self._transport.exec(f"{command} && echo {_DONE}", timeout_s=timeout)
        if not output.endswith(_DONE):
            raise CommandFailedError(
                f"{command.split()[0]} failed on {self._transport.target}: {output or 'no output'}", target=self._transport.target, command=command
            )

    def _discard(self, *paths: str) -> None:
        """Remove staging files, best effort. Runs from `finally`, so a failure here
        is logged and must never replace the exception that got it there."""
        command = "rm -f " + " ".join(shlex.quote(path) for path in paths)
        try:
            self._transport.exec(command, effect=Effect.DESTRUCTIVE)
        except FleetError as exc:
            LOGGER.warning("Could not remove staging files on %s: %s", self._transport.target, exc)

    def _unpack_timeout(self, archive_size: int) -> float:
        """Scale the timeout by payload size. A flat timeout is how the
        predecessor silently truncated archives on slower devices."""
        return max(self._transfer_timeout(), archive_size / self._quirks.min_unpack_bytes_per_s)

    def _transfer_timeout(self) -> float:
        return 180.0


def _plain(archive_path: str) -> str:
    """RETURNS: str: The path with a trailing ``.gz`` removed."""
    return archive_path.removesuffix(".gz")
