"""The `state` verb: snapshotting and restoring an application's on-device state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol

from .errors import FleetError


@dataclass(frozen=True, slots=True)
class AppStateSpec:
    """How an app describes its own state to whichever pack holds it.

    **PARAMETERS:**
        `app_id` (str): The app pack's id, e.g. ``kodi``.  <br>
        `identifiers` (Mapping[str, str]): Platform to platform-native identifier, e.g. ``{"android": "org.xbmc.example"}``. The pack looks up its own platform.  <br>
        `app_roots` (Mapping[str, str]): Platform to the subdirectory holding the state, relative to whatever data directory the pack resolves. Absent or empty means the state *is* that directory. Per-platform because an app's own layout can differ between them — the same application keeps its profile in a dotted subdirectory on one platform and directly in a sandboxed data directory on another.  <br>
        `members` (tuple[str, ...]): Top-level entries that constitute the state, relative to its root. These are what a restore replaces.  <br>
        `exclude` (tuple[str, ...]): Paths to drop before snapshotting, relative to the state root — caches and other regenerable data.  <br>
    """

    app_id: str
    identifiers: Mapping[str, str] = field(default_factory=dict)
    app_roots: Mapping[str, str] = field(default_factory=dict)
    members: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def identifier_for(self, platform: str) -> str:
        """Look up the platform-native identifier for this app.

        **PARAMETERS:**
            `platform` (str): The device pack's platform, e.g. ``android``.  <br>

        **RETURNS:**
            `str`: The identifier the pack should use to locate this app.  <br>

        **RAISES:**
            `FleetError`: If the app declares no identifier for that platform, which means it cannot be managed on that device.  <br>
        """
        identifier = self.identifiers.get(platform)
        if not identifier:
            raise FleetError(f"App {self.app_id!r} declares no identifier for platform {platform!r}")
        return identifier

    def root_for(self, platform: str) -> str:
        """Look up the state subdirectory this app uses on a platform.

        **PARAMETERS:**
            `platform` (str): The device pack's platform, e.g. ``android``.  <br>

        **RETURNS:**
            `str`: The subdirectory, or ``""`` when the state is the resolved data directory itself. Unlike `identifier_for`, an absent entry is a legitimate answer rather than an error — "no subdirectory" is a real layout.  <br>
        """
        return self.app_roots.get(platform, "")


class StateManager(Protocol):
    """Moves an application's state on and off a device."""

    @property
    def platform(self) -> str:
        """RETURNS: str: Platform key used to resolve an app's native identifier."""

    def state_root(self, spec: AppStateSpec) -> str:
        """RETURNS: str: Absolute on-device path holding this app's state."""

    def snapshot(self, spec: AppStateSpec, destination: Path) -> Path:
        """Archive the app's state and retrieve it.

        **PARAMETERS:**
            `spec` (AppStateSpec): What state to capture.  <br>
            `destination` (Path): Local path to write the archive to.  <br>

        **RETURNS:**
            `Path`: `destination`.  <br>

        **RAISES:**
            `TransportError`: If the device could not produce or hand over the archive.  <br>
        """

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        """Replace the app's state with the contents of `archive`.

        **PARAMETERS:**
            `spec` (AppStateSpec): Whose state is being replaced.  <br>
            `archive` (Path): Local archive to push and unpack.  <br>

        **RAISES:**
            `TransportError`: If the transfer, extraction, or verification failed.  <br>
            `FleetError`: If the device lacks the free space to unpack it.  <br>
        """
