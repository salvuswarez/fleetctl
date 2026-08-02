"""How an artifact is named and where it lives."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import ArtifactError

# Leading dot allowed so a capture can mirror an on-device dotted directory
# name. `..` is rejected explicitly below rather than by the character class,
# since allowing a leading dot would otherwise let it through.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9.][A-Za-z0-9._-]{0,127}$")
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def is_safe_segment(part: str) -> bool:
    """RETURNS: bool: Whether `part` is safe to use as one path segment."""
    return bool(_SAFE_SEGMENT.match(part)) and ".." not in part and part != "."


def sanitize(name: str) -> str:
    """Reduce an untrusted name to something safe to use as a path segment.

    **PARAMETERS:**
        `name` (str): Raw name, e.g. one reported by a device.  <br>

    **RETURNS:**
        `str`: Lowercase `[a-z0-9._-]`, capped at 48 characters, or ``"unknown"`` if nothing safe remained.  <br>
    """
    cleaned = _UNSAFE_CHARS.sub("_", name.strip().lower()).strip("._")
    return cleaned[:48] or "unknown"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """A reference to one stored artifact: ``kind/name``.

    **PARAMETERS:**
        `kind` (str): Namespace directory, e.g. ``builds`` or ``captures``.  <br>
        `name` (str): Filename within that namespace.  <br>
    """

    kind: str
    name: str

    def __post_init__(self) -> None:
        for part in (self.kind, self.name):
            if not is_safe_segment(part):
                raise ArtifactError(f"Unsafe artifact path segment: {part!r}", ref=f"{self.kind}/{self.name}")

    @classmethod
    def parse(cls, wire: str) -> ArtifactRef:
        """Parse a ``kind/name`` reference.

        **PARAMETERS:**
            `wire` (str): Candidate reference, as returned by `ArtifactStore.list`.  <br>

        **RETURNS:**
            `ArtifactRef`: The validated reference.  <br>

        **RAISES:**
            `ArtifactError`: If `wire` is not exactly two safe segments.  <br>
        """
        parts = wire.split("/")
        if len(parts) != 2:
            raise ArtifactError(f"Artifact reference must be 'kind/name': {wire!r}", ref=wire)
        return cls(kind=parts[0], name=parts[1])

    @property
    def wire(self) -> str:
        """RETURNS: str: The ``kind/name`` form, safe to hand to any consumer."""
        return f"{self.kind}/{self.name}"

    @property
    def meta_name(self) -> str:
        """RETURNS: str: Filename of this artifact's sidecar metadata."""
        stem = self.name
        for suffix in (".tar.gz", ".tgz"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        else:
            stem = stem.rsplit(".", 1)[0] if "." in stem.lstrip(".") else stem
        return f"{stem}.meta.json"

    def remote_path(self, root: str) -> str:
        """RETURNS: str: POSIX path of this artifact under a store `root`."""
        return posixpath.join(root, self.kind, self.name)

    def meta_remote_path(self, root: str) -> str:
        """RETURNS: str: POSIX path of this artifact's sidecar under a store `root`."""
        return posixpath.join(root, self.kind, self.meta_name)

    def local_path(self, staging: Path) -> Path:
        """Where this artifact lands inside a staging directory.

        **PARAMETERS:**
            `staging` (Path): The operation's staging directory.  <br>

        **RETURNS:**
            `Path`: Local destination for this artifact.  <br>
        """
        return staging / self.name
