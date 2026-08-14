"""The artifact store seam, and a local-filesystem adapter."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.errors import ArtifactError


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    """What is known about a stored artifact without downloading it.

    **PARAMETERS:**
        `ref` (ArtifactRef): The artifact this describes.  <br>
        `size` (int): Size in bytes.  <br>
        `created_at` (str): ISO-8601 creation timestamp.  <br>
        `meta` (Mapping[str, Any]): Sidecar metadata, empty when absent or unreadable.  <br>
    """

    ref: ArtifactRef
    size: int = 0
    created_at: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ArtifactStore(Protocol):
    """Where artifacts live."""

    def put(self, local_path: Path, ref: ArtifactRef, *, meta: Mapping[str, Any] | None = None) -> ArtifactInfo:
        """Store `local_path` under `ref`, optionally with sidecar metadata."""

    def get(self, ref: ArtifactRef, local_path: Path) -> Path:
        """Retrieve `ref` into `local_path` and return it."""

    def list(self, kind: str) -> list[ArtifactInfo]:
        """RETURNS: list[ArtifactInfo]: Everything under `kind`, newest first."""

    def exists(self, ref: ArtifactRef) -> bool:
        """RETURNS: bool: Whether `ref` is present."""

    def delete(self, ref: ArtifactRef) -> None:
        """Remove `ref`. Absent artifacts are not an error."""

    def latest(self, kind: str) -> ArtifactRef:
        """RETURNS: ArtifactRef: The newest artifact under `kind`."""


def require_kind(ref: ArtifactRef, kind: str) -> ArtifactRef:
    """Reject a reference that points outside the expected namespace.

    **PARAMETERS:**
        `ref` (ArtifactRef): Reference to check.  <br>
        `kind` (str): The namespace it must belong to.  <br>

    **RETURNS:**
        `ArtifactRef`: `ref`, unchanged.  <br>

    **RAISES:**
        `ArtifactError`: If `ref` belongs to a different namespace.  <br>
    """
    if ref.kind != kind:
        raise ArtifactError(f"{ref.wire!r} is not a {kind!r} artifact", ref=ref.wire)
    return ref


class LocalArtifactStore:
    """Artifact store backed by a local directory tree.

    **PARAMETERS:**
        `root` (Path): Directory holding one subdirectory per `kind`.  <br>
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, ref: ArtifactRef) -> Path:
        return self._root / ref.kind / ref.name

    def _meta_path(self, ref: ArtifactRef) -> Path:
        return self._root / ref.kind / ref.meta_name

    def put(self, local_path: Path, ref: ArtifactRef, *, meta: Mapping[str, Any] | None = None) -> ArtifactInfo:
        """Copy `local_path` into the store under `ref`.

        **RETURNS:**
            `ArtifactInfo`: Description of what was stored.  <br>

        **RAISES:**
            `ArtifactError`: If `local_path` does not exist.  <br>
        """
        if not local_path.is_file():
            raise ArtifactError(f"No such file to store: {local_path}", ref=ref.wire)
        destination = self._path(ref)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, destination)

        created_at = datetime.now(timezone.utc).isoformat()
        record = {"created_at": created_at, "size": destination.stat().st_size, **(meta or {})}
        self._meta_path(ref).write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return ArtifactInfo(ref=ref, size=record["size"], created_at=created_at, meta=record)

    def get(self, ref: ArtifactRef, local_path: Path) -> Path:
        """Copy `ref` out of the store to `local_path`.

        **RETURNS:**
            `Path`: `local_path`.  <br>

        **RAISES:**
            `ArtifactError`: If `ref` is not present.  <br>
        """
        source = self._path(ref)
        if not source.is_file():
            raise ArtifactError(f"No such artifact: {ref.wire}", ref=ref.wire)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, local_path)
        return local_path

    def list(self, kind: str) -> list[ArtifactInfo]:
        """List everything under `kind`, newest first.

        **RETURNS:**
            `list[ArtifactInfo]`: Descriptions, newest first.  <br>
        """
        directory = self._root / kind
        if not directory.is_dir():
            return []
        found: list[ArtifactInfo] = []
        for path in directory.iterdir():
            if not path.is_file() or path.name.endswith(".meta.json"):
                continue
            ref = ArtifactRef(kind=kind, name=path.name)
            found.append(ArtifactInfo(ref=ref, size=path.stat().st_size, created_at=self._created_at(ref, path), meta=self._meta(ref)))
        return sorted(found, key=lambda info: (info.created_at, info.ref.name), reverse=True)

    def exists(self, ref: ArtifactRef) -> bool:
        """RETURNS: bool: Whether `ref` is present in the store."""
        return self._path(ref).is_file()

    def delete(self, ref: ArtifactRef) -> None:
        """Remove `ref` and its sidecar. Absent artifacts are not an error."""
        self._path(ref).unlink(missing_ok=True)
        self._meta_path(ref).unlink(missing_ok=True)

    def latest(self, kind: str) -> ArtifactRef:
        """Resolve the newest artifact under `kind`.

        **RETURNS:**
            `ArtifactRef`: The newest artifact.  <br>

        **RAISES:**
            `ArtifactError`: If `kind` holds nothing.  <br>
        """
        found = self.list(kind)
        if not found:
            raise ArtifactError(f"No artifacts of kind {kind!r}", ref=kind)
        return found[0].ref

    def _meta(self, ref: ArtifactRef) -> Mapping[str, Any]:
        path = self._meta_path(ref)
        if not path.is_file():
            return {}
        try:
            loaded: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _created_at(self, ref: ArtifactRef, path: Path) -> str:
        recorded = self._meta(ref).get("created_at")
        if isinstance(recorded, str) and recorded:
            return recorded
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
