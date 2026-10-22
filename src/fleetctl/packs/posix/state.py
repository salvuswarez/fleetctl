"""POSIX implementation of the `state` verb."""

from __future__ import annotations

import logging
import posixpath
import shlex
from pathlib import Path

from fleetctl.core.effects import Effect
from fleetctl.core.errors import FleetError, TransportError
from fleetctl.core.state import AppStateSpec
from fleetctl.core.transport.base import Transport
from fleetctl.packs.posix import actions
from fleetctl.packs.posix.quirks import PosixQuirks

LOGGER = logging.getLogger(__name__)

PLATFORM = "linux"
# Created under the configured `staging_dir` and owned outright by fleetctl.
# That dir can be shared — `/tmp` on a generic host — so it is never cleared
# itself; this one is. See `_clear_staging`.
_STAGING_SUBDIR = "fleetctl-staging"


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

        The staging archive is removed however this exits.

        **RETURNS:**
            `Path`: `destination`.  <br>

        **RAISES:**
            `TransportError`: If the archive could not be built or retrieved.  <br>
        """
        root = self.state_root(spec)
        staged = posixpath.join(self._clear_staging(), destination.name)
        timeout = _TRANSFER_TIMEOUT_S

        for relative in spec.exclude:
            self._transport.exec_ok(f"rm -rf {shlex.quote(posixpath.join(root, relative))}", effect=Effect.DESTRUCTIVE)

        # Archive the members by name from inside the root, so the archive is
        # flat — `addons/`, `userdata/`, `media/` at the top with no wrapping
        # directory. That layout is part of the build contract and is what
        # lets a restore extract straight into the state root.
        members = " ".join(shlex.quote(member) for member in spec.members) if spec.members else "."
        try:
            # MUTATING, not READ: this writes an archive into the staging
            # directory. Only the app's own state is left untouched.
            self._transport.exec(f"tar czf {shlex.quote(staged)} -C {shlex.quote(root)} {members}", timeout_s=timeout)
            self._transport.get(staged, destination)
        finally:
            self._discard(staged)
        return destination

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        """Push `archive` and replace the app's state with its contents.

        **RAISES:**
            `FleetError`: If the host lacks free space to unpack it.  <br>
            `TransportError`: If the transfer, extraction, or verification failed.  <br>
        """
        root = self.state_root(spec)
        size = archive.stat().st_size
        staging = self._clear_staging()
        staged = posixpath.join(staging, archive.name)
        timeout = self._unpack_timeout(size)

        self._require_space(staging, size)
        try:
            self._transport.put(archive, staged, effect=Effect.DESTRUCTIVE)

            for member in spec.members:
                self._transport.exec_ok(f"rm -rf {shlex.quote(posixpath.join(root, member))}", effect=Effect.DESTRUCTIVE)
            self._transport.exec(f"mkdir -p {shlex.quote(root)}")

            self._transport.exec(f"tar xzf {shlex.quote(staged)} -C {shlex.quote(root)}", timeout_s=timeout)
        finally:
            self._discard(staged)

        self._verify(root, spec)

    def _verify(self, root: str, spec: AppStateSpec) -> None:
        """Fail loudly if extraction left the state unusable."""
        for member in spec.members:
            listing = self._transport.exec_ok(f"ls {shlex.quote(posixpath.join(root, member))}", effect=Effect.READ)
            if not listing.strip():
                raise TransportError(f"Restore verification failed: {root}/{member} is missing or empty", target=self._transport.target)

    def _require_space(self, staging: str, archive_size: int) -> None:
        free = self._transport.free_bytes(staging)
        needed = int(archive_size * self._quirks.disk_headroom)
        if free and free < needed:
            raise FleetError(f"Not enough free space on {self._transport.target}: need ~{needed // (1024 * 1024)}MB, {free // (1024 * 1024)}MB available")

    def _clear_staging(self) -> str:
        """Empty fleetctl's staging directory, creating it if absent, before any space is measured.

        On an image-based host this must not be a system path: `/` is mounted
        read-only there, and a staged upload would fail after the transfer
        rather than before it.

        A `finally` cannot run when the process itself dies. A capture
        interrupted by a Home Assistant restart left a 1.2GB archive on a Fire
        Stick that failed every later deploy's space check, so each run
        reclaims whatever the last one could not.

        **RETURNS:**
            `str`: Absolute, home-expanded staging directory.  <br>
        """
        staging = posixpath.join(self._expand(self._quirks.staging_dir), _STAGING_SUBDIR)
        # `mkdir -p` because a `~`-relative staging dir under a cache directory
        # will not exist on a freshly-imaged host, and SFTP does not create parents.
        quoted = shlex.quote(staging)
        self._transport.exec(f"rm -rf {quoted} && mkdir -p {quoted}", effect=Effect.DESTRUCTIVE)
        return staging

    def _discard(self, staged: str) -> None:
        """Remove a staged archive, best effort. Runs from `finally`, so a failure
        here is logged and must never replace the exception that got it there."""
        try:
            self._transport.exec(f"rm -f {shlex.quote(staged)}", effect=Effect.DESTRUCTIVE)
        except FleetError as exc:
            LOGGER.warning("Could not remove staging file on %s: %s", self._transport.target, exc)

    def _expand(self, path: str) -> str:
        """RETURNS: str: `path` with a leading ``~`` resolved against the host's home directory."""
        return actions.expand_home(self._transport, path)

    def _unpack_timeout(self, archive_size: int) -> float:
        """Scale the timeout by payload size. A flat timeout is how the
        predecessor silently truncated archives on slower devices."""
        return max(_TRANSFER_TIMEOUT_S, archive_size / self._quirks.min_unpack_bytes_per_s)


_TRANSFER_TIMEOUT_S = 180.0
