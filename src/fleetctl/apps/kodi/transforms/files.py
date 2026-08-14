"""Place whole files into a profile that the capture did not contain."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from fleetctl.core.errors import FleetError

LOGGER = logging.getLogger(__name__)

DATA_PACKAGE = "fleetctl.apps.kodi.data.files"


@dataclass(frozen=True, slots=True)
class ShipFiles:
    """Write files shipped with the app pack into an extracted profile.

    Every other transform edits what a capture already held, so content that
    exists on no device — keymaps, extra sources, player definitions — has no
    way in. A deploy replaces the whole state root, so anything placed by hand
    is lost on the next one.

    **PARAMETERS:**
        `files` (Mapping[str, str]): Profile-relative destination to the name of a file in the pack's `data/files/` directory.  <br>
    """

    files: Mapping[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """RETURNS: str: Short identifier for logs and audit records."""
        return "ship_files"

    def apply(self, profile: Path, config: Mapping[str, Any]) -> list[str]:
        """Copy each configured file into `profile`.

        **PARAMETERS:**
            `profile` (Path): Extracted profile directory.  <br>
            `config` (Mapping[str, Any]): May supply `files`, overriding this instance's mapping.  <br>

        **RETURNS:**
            `list[str]`: One description per file written.  <br>

        **RAISES:**
            `FleetError`: If a destination escapes the profile, or a named source file does not ship with the pack. Both are recipe errors and must fail the build rather than silently skip.  <br>
        """
        wanted = config.get("files", self.files)
        if not wanted:
            return []

        changes: list[str] = []
        for destination, source in dict(wanted).items():
            target = _resolve(profile, str(destination))
            payload = _read(str(source))
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            target.write_bytes(payload)
            changes.append(f"{'replaced' if existed else 'added'} {destination} ({len(payload)} bytes)")
        return changes


def _resolve(profile: Path, destination: str) -> Path:
    """Resolve a profile-relative destination.

    **RETURNS:**
        `Path`: Absolute path inside `profile`.  <br>

    **RAISES:**
        `FleetError`: If `destination` is absolute or climbs out of the profile.  <br>
    """
    candidate = Path(destination)
    if candidate.is_absolute():
        raise FleetError(f"ship_files destination must be profile-relative, got {destination!r}")
    resolved = (profile / candidate).resolve()
    if not resolved.is_relative_to(profile.resolve()):
        raise FleetError(f"ship_files destination escapes the profile: {destination!r}")
    return resolved


def _read(source: str) -> bytes:
    """RETURNS: bytes: A file shipped in the pack's `data/files/` directory.

    **RAISES:**
        `FleetError`: If it is not present.  <br>
    """
    try:
        return resources.files(DATA_PACKAGE).joinpath(source).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise FleetError(f"ship_files source {source!r} does not ship with the Kodi pack") from exc
