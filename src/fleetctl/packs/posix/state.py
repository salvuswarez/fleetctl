"""POSIX implementation of the `state` verb."""

from __future__ import annotations

import logging
import posixpath
import shlex
from pathlib import Path

from ...core.effects import Effect
from ...core.errors import FleetError, TransportError
from ...core.state import AppStateSpec
from ...core.transport.base import Transport
from . import actions
from .quirks import PosixQuirks

LOGGER = logging.getLogger(__name__)

PLATFORM = "linux"


class PosixStateManager:
    """Snapshots and restores an app's state on a POSIX host.

    Unlike the Android manager this always uses GNU ``tar`` with ``-z``: the
    two-step split is a toybox truncation bug on Fire OS, and a Linux host has
    real GNU tar. Verified against GNU tar 1.35 on SteamOS 3.8.

    **PARAMETERS:**
        `transport` (Transport): Connection to the host.  <br>
        `quirks` (PosixQuirks | None): Host deviations — where to stage, and where application data lives. Defaults to ``None``, meaning conventional-Linux defaults.  <br>
    """

    def __init__(self, transport: Transport, quirks: PosixQuirks | None = None) -> None:
        self._transport = transport
        self._quirks = quirks or PosixQuirks()

    @property
    def platform(self) -> str:
        """RETURNS: str: Always ``linux``."""
        return PLATFORM

    def state_root(self, spec: AppStateSpec) -> str:
        """Resolve where an app's state lives on this host.

        **PARAMETERS:**
            `spec` (AppStateSpec): The app, which supplies its own identifier and per-platform subdirectory.  <br>

        **RETURNS:**
            `str`: Absolute path on the host, with the home directory expanded so nothing downstream has to re-expand ``~``.  <br>
        """
        identifier = spec.identifier_for(PLATFORM)
        # `{identifier}` is how a sandboxed layout is expressed without this
        # base knowing sandboxes exist — the pack's data file supplies the
        # template, e.g. `~/.var/app/{identifier}/data`.
        base = self._quirks.app_data_root.format(identifier=identifier)
        app_root = spec.root_for(PLATFORM)
        return self._expand(posixpath.join(base, *([app_root] if app_root else [])))

    def snapshot(self, spec: AppStateSpec, destination: Path) -> Path:
        """Trim, archive, and retrieve the app's state.

        **RETURNS:**
            `Path`: `destination`.  <br>

        **RAISES:**
            `TransportError`: If the archive could not be built or retrieved.  <br>
        """
        root = self.state_root(spec)
        staged = posixpath.join(self._staging(), destination.name)
        timeout = _TRANSFER_TIMEOUT_S

        for relative in spec.exclude:
            self._transport.exec_ok(f"rm -rf {shlex.quote(posixpath.join(root, relative))}", effect=Effect.DESTRUCTIVE)

        self._transport.exec_ok(f"rm -f {shlex.quote(staged)}", effect=Effect.DESTRUCTIVE)

        # Archive the members by name from inside the root, so the archive is
        # flat — `addons/`, `userdata/`, `media/` at the top with no wrapping
        # directory. That layout is part of the build contract and is what
        # lets a restore extract straight into the state root.
        members = " ".join(shlex.quote(member) for member in spec.members) if spec.members else "."
        # MUTATING, not READ: this writes an archive into the staging
        # directory. Only the app's own state is left untouched.
        self._transport.exec(f"tar czf {shlex.quote(staged)} -C {shlex.quote(root)} {members}", timeout_s=timeout)

        self._transport.get(staged, destination)
        self._transport.exec_ok(f"rm -f {shlex.quote(staged)}", effect=Effect.DESTRUCTIVE)
        return destination

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        """Push `archive` and replace the app's state with its contents.

        **RAISES:**
            `FleetError`: If the host lacks free space to unpack it.  <br>
            `TransportError`: If the transfer, extraction, or verification failed.  <br>
        """
        root = self.state_root(spec)
        size = archive.stat().st_size
        self._require_space(size)

        staged = posixpath.join(self._staging(), archive.name)
        timeout = self._unpack_timeout(size)

        self._transport.exec_ok(f"rm -f {shlex.quote(staged)}", effect=Effect.DESTRUCTIVE)
        self._transport.put(archive, staged, effect=Effect.DESTRUCTIVE)

        for member in spec.members:
            self._transport.exec_ok(f"rm -rf {shlex.quote(posixpath.join(root, member))}", effect=Effect.DESTRUCTIVE)
        self._transport.exec(f"mkdir -p {shlex.quote(root)}")

        self._transport.exec(f"tar xzf {shlex.quote(staged)} -C {shlex.quote(root)}", timeout_s=timeout)
        self._transport.exec_ok(f"rm -f {shlex.quote(staged)}", effect=Effect.DESTRUCTIVE)

        self._verify(root, spec)

    def _verify(self, root: str, spec: AppStateSpec) -> None:
        """Fail loudly if extraction left the state unusable."""
        for member in spec.members:
            listing = self._transport.exec_ok(f"ls {shlex.quote(posixpath.join(root, member))}", effect=Effect.READ)
            if not listing.strip():
                raise TransportError(f"Restore verification failed: {root}/{member} is missing or empty", target=self._transport.target)

    def _require_space(self, archive_size: int) -> None:
        free = self._transport.free_bytes(self._staging())
        needed = int(archive_size * self._quirks.disk_headroom)
        if free and free < needed:
            raise FleetError(f"Not enough free space on {self._transport.target}: need ~{needed // (1024 * 1024)}MB, {free // (1024 * 1024)}MB available")

    def _staging(self) -> str:
        """Resolve the staging directory, creating it if it does not exist.

        On an image-based host this must not be a system path: `/` is mounted
        read-only there, and a staged upload would fail after the transfer
        rather than before it.

        **RETURNS:**
            `str`: Absolute, home-expanded staging directory.  <br>
        """
        staging = self._expand(self._quirks.staging_dir)
        # A `~`-relative staging dir under a cache directory will not exist on
        # a freshly-imaged host, and SFTP does not create parents.
        self._transport.exec_ok(f"mkdir -p {shlex.quote(staging)}", effect=Effect.MUTATING)
        return staging

    def _expand(self, path: str) -> str:
        """RETURNS: str: `path` with a leading ``~`` resolved against the host's home directory."""
        return actions.expand_home(self._transport, path)

    def _unpack_timeout(self, archive_size: int) -> float:
        """Scale the timeout by payload size. A flat timeout is how the
        predecessor silently truncated archives on slower devices."""
        return max(_TRANSFER_TIMEOUT_S, archive_size / self._quirks.min_unpack_bytes_per_s)


_TRANSFER_TIMEOUT_S = 180.0
