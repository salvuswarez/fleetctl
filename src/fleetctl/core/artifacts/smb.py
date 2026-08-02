"""Artifact store backed by an SMB share."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from ..config.secrets import Secret
from ..errors import ArtifactError
from .ref import ArtifactRef
from .store import ArtifactInfo

LOGGER = logging.getLogger(__name__)

_CHUNK = 65536
_RETRIES = 2
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class SmbSettings:
    """Where the share is and how to reach it.

    **PARAMETERS:**
        `host` (str): SMB server hostname or address.  <br>
        `share` (str): Share name.  <br>
        `root` (str): Directory within the share holding artifact kinds.  <br>
        `user` (str): Username; empty means SMB is not configured.  <br>
        `password` (Secret | str): Password, normally a resolved `!ref`.  <br>
    """

    host: str = ""
    share: str = ""
    root: str = "fleetctl"
    user: str = ""
    password: Secret | str = ""

    @property
    def configured(self) -> bool:
        """RETURNS: bool: Whether enough is set to attempt a connection."""
        return bool(self.host and self.share and self.user)

    def reveal_password(self) -> str:
        """RETURNS: str: The password value, unwrapped only here at the edge."""
        return self.password.reveal() if isinstance(self.password, Secret) else str(self.password)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SmbSettings:
        """RETURNS: SmbSettings: Settings read from a `fleet.yml` `artifacts.smb` block."""
        return cls(
            host=str(data.get("host", "")),
            share=str(data.get("share", "")),
            root=str(data.get("root", "fleetctl")),
            user=str(data.get("user", "")),
            password=data.get("password", ""),
        )


class SmbArtifactStore:
    """Artifacts on a network share, so a fleet shares one set.

    Retries once on a dropped connection: SMB sessions go stale between runs
    far more often than they fail outright, and a stale handle is not a
    reason to fail a deploy.

    **PARAMETERS:**
        `settings` (SmbSettings): Where the share is and how to reach it.  <br>
    """

    def __init__(self, settings: SmbSettings) -> None:
        self._settings = settings
        self._configured = False

    def _connect(self) -> None:
        if self._configured:
            return
        if not self._settings.configured:
            raise ArtifactError("SMB is not configured; set artifacts.smb host/share/user in fleet.yml")
        import smbclient

        smbclient.ClientConfig(username=self._settings.user, password=self._settings.reveal_password())
        self._configured = True

    def _retry(self, call: Callable[[], _T]) -> _T:
        """Run `call`, resetting the session once if the connection was stale."""
        self._connect()
        import smbclient

        for attempt in range(_RETRIES):
            try:
                return call()
            except Exception as exc:
                if attempt == _RETRIES - 1 or not _is_transient(exc):
                    raise
                LOGGER.info("SMB session stale, reconnecting: %s", exc)
                smbclient.reset_connection_cache()
                self._configured = False
                self._connect()
        raise ArtifactError("SMB retry loop exhausted")

    def _path(self, *parts: str) -> str:
        return "\\\\" + "\\".join([self._settings.host, self._settings.share, self._settings.root, *parts])

    def put(self, local_path: Path, ref: ArtifactRef, *, meta: Mapping[str, Any] | None = None) -> ArtifactInfo:
        """Upload `local_path` to the share under `ref`.

        **RETURNS:**
            `ArtifactInfo`: Description of what was stored.  <br>

        **RAISES:**
            `ArtifactError`: If `local_path` is missing or the upload failed.  <br>
        """
        if not local_path.is_file():
            raise ArtifactError(f"No such file to store: {local_path}", ref=ref.wire)
        import smbclient

        created_at = datetime.now(timezone.utc).isoformat()
        record = {"created_at": created_at, "size": local_path.stat().st_size, **(meta or {})}

        def _upload() -> None:
            smbclient.makedirs(self._path(ref.kind), exist_ok=True)
            with open(local_path, "rb") as source, smbclient.open_file(self._path(ref.kind, ref.name), mode="wb") as target:
                shutil.copyfileobj(source, target, _CHUNK)
            with smbclient.open_file(self._path(ref.kind, ref.meta_name), mode="w", encoding="utf-8") as sidecar:
                sidecar.write(json.dumps(record, indent=2, default=str))

        try:
            self._retry(_upload)
        except ArtifactError:
            raise
        except Exception as exc:
            raise ArtifactError(f"SMB upload failed for {ref.wire}: {exc}", ref=ref.wire) from exc
        return ArtifactInfo(ref=ref, size=int(record["size"]), created_at=created_at, meta=record)

    def get(self, ref: ArtifactRef, local_path: Path) -> Path:
        """Download `ref` to `local_path`.

        **RETURNS:**
            `Path`: `local_path`.  <br>

        **RAISES:**
            `ArtifactError`: If `ref` is absent or the download failed.  <br>
        """
        import smbclient

        local_path.parent.mkdir(parents=True, exist_ok=True)

        def _download() -> None:
            with smbclient.open_file(self._path(ref.kind, ref.name), mode="rb") as source, open(local_path, "wb") as target:
                shutil.copyfileobj(source, target, _CHUNK)

        try:
            self._retry(_download)
        except ArtifactError:
            raise
        except Exception as exc:
            raise ArtifactError(f"No such artifact on SMB: {ref.wire} ({exc})", ref=ref.wire) from exc
        return local_path

    def list(self, kind: str) -> list[ArtifactInfo]:
        """List everything under `kind`, newest first.

        **RETURNS:**
            `list[ArtifactInfo]`: Descriptions. A missing directory yields an empty list; an unreadable sidecar drops only its own metadata.  <br>
        """
        import smbclient

        try:
            names = self._retry(lambda: list(smbclient.listdir(self._path(kind))))
        except Exception as exc:
            LOGGER.debug("SMB listing failed for %s: %s", kind, exc)
            return []

        found: list[ArtifactInfo] = []
        for name in names:
            if name.endswith(".meta.json"):
                continue
            ref = ArtifactRef(kind=kind, name=name)
            meta = self._meta(ref)
            found.append(ArtifactInfo(ref=ref, size=int(meta.get("size", 0) or 0), created_at=str(meta.get("created_at", "")), meta=meta))
        return sorted(found, key=lambda info: (info.created_at, info.ref.name), reverse=True)

    def exists(self, ref: ArtifactRef) -> bool:
        """RETURNS: bool: Whether `ref` is present on the share."""
        import smbclient

        try:
            return bool(self._retry(lambda: smbclient.path.exists(self._path(ref.kind, ref.name))))
        except Exception:
            return False

    def delete(self, ref: ArtifactRef) -> None:
        """Remove `ref` and its sidecar. Absent artifacts are not an error."""
        import smbclient

        for name in (ref.name, ref.meta_name):
            try:
                self._retry(lambda target=name: smbclient.remove(self._path(ref.kind, target)))  # type: ignore[misc]
            except Exception as exc:
                LOGGER.debug("SMB delete skipped for %s: %s", name, exc)

    def latest(self, kind: str) -> ArtifactRef:
        """RETURNS: ArtifactRef: The newest artifact under `kind`.

        **RAISES:**
            `ArtifactError`: If `kind` holds nothing.  <br>
        """
        found = self.list(kind)
        if not found:
            raise ArtifactError(f"No artifacts of kind {kind!r} on the share", ref=kind)
        return found[0].ref

    def _meta(self, ref: ArtifactRef) -> dict[str, Any]:
        import smbclient

        try:
            with smbclient.open_file(self._path(ref.kind, ref.meta_name), mode="r", encoding="utf-8") as handle:
                loaded = json.loads(handle.read())
        except Exception as exc:
            LOGGER.debug("No readable sidecar for %s: %s", ref.wire, exc)
            return {}
        return loaded if isinstance(loaded, dict) else {}


def _is_transient(exc: BaseException) -> bool:
    """RETURNS: bool: Whether an SMB error looks like a stale session rather than a real fault."""
    name = type(exc).__name__
    return isinstance(exc, (ConnectionError, BrokenPipeError, TimeoutError)) or "ConnectionClosed" in name or "Disconnect" in name
