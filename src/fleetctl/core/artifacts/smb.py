"""Artifact store backed by an SMB share."""

from __future__ import annotations

import errno
import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import ArtifactInfo
from fleetctl.core.config.secrets import Secret
from fleetctl.core.errors import ArtifactError

LOGGER = logging.getLogger(__name__)

_CHUNK = 65536

# Without this, smbprotocol opens a file exclusively and a second reader gets
# STATUS_SHARING_VIOLATION. Listing a kind reads every sidecar, and the panel
# lists concurrently, so the same file is routinely opened more than once at a
# time. Reads declare that they tolerate other readers; writes stay exclusive.
_SHARE_READ = "r"
# Kept low deliberately: the share is served by a small router-hosted SMB
# stack that answers STATUS_INSUFFICIENT_RESOURCES when several clients retry
# at once, so an eager retry loop turns contention into exhaustion.
_RETRIES = 2
# NtStatus.STATUS_SHARING_VIOLATION. Compared numerically so smbprotocol stays
# a lazy import, as everywhere else in this module.
_SHARING_VIOLATION = 0xC0000043

# Statuses that mean "the session you are holding no longer exists" — the
# server has torn it down and every handle under it is void, so the only way
# forward is to reconnect and try once more.
#
# These arrive as `smbprotocol.exceptions.SMBOSError`, which subclasses
# OSError, NOT ConnectionError — so classifying a stale session by exception
# type misses them entirely and reports a router that merely idled out as a
# permanent failure. Observed on this fleet: `kodi.fetch_base` spends a minute
# downloading from the mirror, and the router-hosted stack has dropped the
# session by the time the upload starts.
_SESSION_GONE = frozenset(
    {
        0xC0000203,  # STATUS_USER_SESSION_DELETED
        0xC000035C,  # STATUS_NETWORK_SESSION_EXPIRED
        0xC000020C,  # STATUS_CONNECTION_DISCONNECTED
        0xC000020D,  # STATUS_CONNECTION_RESET
        0xC00000B0,  # STATUS_PIPE_DISCONNECTED
    }
)
_CONTENTION_BACKOFF_S = 0.15
# Payloads land under this suffix and are renamed into place once whole, so a
# transfer cut off mid-flight leaves nothing that reads as a finished artifact.
# `list` skips it; a 350MB build takes long enough that a dropped session
# during one is routine rather than exceptional.
_UPLOADING = ".uploading"
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class SmbSettings:
    """Where the share is and how to reach it.

    **PARAMETERS:**
        `host` (str): SMB server hostname or address.  <br>
        `share` (str): Share name.  <br>
        `root` (str): Directory within the share holding artifact kinds.  <br>
        `user` (Secret | str): Username, which may be a resolved `!ref`; empty means SMB is not configured.  <br>
        `password` (Secret | str): Password, normally a resolved `!ref`.  <br>
    """

    host: str = ""
    share: str = ""
    root: str = "fleetctl"
    user: Secret | str = ""
    password: Secret | str = ""

    @property
    def configured(self) -> bool:
        """RETURNS: bool: Whether enough is set to attempt a connection."""
        return bool(self.host and self.share and self.reveal_user())

    def reveal_user(self) -> str:
        """RETURNS: str: The username, unwrapped only here at the edge."""
        return _reveal(self.user)

    def reveal_password(self) -> str:
        """RETURNS: str: The password value, unwrapped only here at the edge."""
        return _reveal(self.password)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SmbSettings:
        """RETURNS: SmbSettings: Settings read from a `fleet.yml` `artifacts.smb` block."""
        return cls(
            host=str(data.get("host", "")),
            share=str(data.get("share", "")),
            root=str(data.get("root", "fleetctl")),
            user=data.get("user", ""),
            password=data.get("password", ""),
        )


class SmbArtifactStore:
    """Artifacts on a network share, so a fleet shares one set.

    Retries once on a dropped connection: SMB sessions go stale between runs
    far more often than they fail outright, and a stale handle is not a
    reason to fail a deploy.

    Uploads publish by rename, never by writing to the final name. Nothing
    else keeps a session dropped 200MB into a 350MB build from leaving a file
    that lists, sizes and deploys exactly like a whole one.

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

        smbclient.ClientConfig(username=self._settings.reveal_user(), password=self._settings.reveal_password())
        self._configured = True

    def _retry(self, call: Callable[[], _T]) -> _T:
        """Run `call`, resetting the session once if the connection was stale."""
        self._connect()
        import smbclient

        for attempt in range(_RETRIES):
            try:
                return call()
            except Exception as exc:
                if attempt == _RETRIES - 1:
                    raise
                if _is_contended(exc):
                    # Resetting the session would not help and costs a
                    # reconnect; the competing handle closes on its own.
                    LOGGER.debug("SMB path contended, retrying: %s", exc)
                    time.sleep(_CONTENTION_BACKOFF_S * (attempt + 1))
                    continue
                if not _is_transient(exc):
                    raise
                LOGGER.info("SMB session stale, reconnecting: %s", exc)
                smbclient.reset_connection_cache()
                self._configured = False
                self._connect()
        raise ArtifactError("SMB retry loop exhausted")

    def _path(self, *parts: str) -> str:
        return "\\\\" + "\\".join([self._settings.host, self._settings.share, self._settings.root, *parts])

    def _remove_quietly(self, path: str) -> None:
        """Delete `path`, treating any failure as "it is not in the way"."""
        import smbclient

        try:
            smbclient.remove(path)
        except Exception as exc:  # noqa: BLE001 - absent is the normal case, and a real problem resurfaces on the write
            LOGGER.debug("Nothing to clear at %s: %s", path, exc)

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
            staged = self._path(ref.kind, ref.name + _UPLOADING)
            # A retry inherits whatever the dead session left behind, and the
            # server can still hold a handle on it — reopening that path for
            # write is refused outright. Clearing it first is what makes the
            # second attempt possible at all.
            self._remove_quietly(staged)
            with open(local_path, "rb") as source, smbclient.open_file(staged, mode="wb") as target:
                shutil.copyfileobj(source, target, _CHUNK)
            with smbclient.open_file(self._path(ref.kind, ref.meta_name), mode="w", encoding="utf-8") as sidecar:
                sidecar.write(json.dumps(record, indent=2, default=str))
            # Last, and the only step that publishes anything: the payload
            # appearing under its real name means it is whole and its sidecar
            # is already beside it.
            smbclient.replace(staged, self._path(ref.kind, ref.name))

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
            with smbclient.open_file(self._path(ref.kind, ref.name), mode="rb", share_access=_SHARE_READ) as source, open(local_path, "wb") as target:
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
            # An absent kind is normal and stays quiet. Anything else means
            # this returned "no artifacts" for a share that may be full — the
            # same shape as a genuinely empty one, so say so loudly.
            if getattr(exc, "errno", None) == errno.ENOENT:
                LOGGER.debug("No %s directory on the share yet", kind)
            else:
                LOGGER.warning("SMB listing failed for %s, reporting it as empty: %s", kind, exc)
            return []

        found: list[ArtifactInfo] = []
        for name in names:
            if name.endswith(".meta.json") or name.endswith(_UPLOADING):
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
            with smbclient.open_file(self._path(ref.kind, ref.meta_name), mode="r", encoding="utf-8", share_access=_SHARE_READ) as handle:
                loaded = json.loads(handle.read())
        except Exception as exc:
            LOGGER.debug("No readable sidecar for %s: %s", ref.wire, exc)
            return {}
        return loaded if isinstance(loaded, dict) else {}


def _reveal(value: Secret | str) -> str:
    """RETURNS: str: The underlying value. `str()` on a Secret yields its mask, never its content."""
    return value.reveal() if isinstance(value, Secret) else str(value)


def _is_contended(exc: BaseException) -> bool:
    """RETURNS: bool: Whether another handle held the file.

    Distinct from a stale session: nothing needs reconnecting, the other
    handle simply has to close. Listing a kind opens its directory and every
    sidecar, and the panel lists concurrently, so this happens routinely.
    """
    return bool(getattr(exc, "ntstatus", None) == _SHARING_VIOLATION)


def _is_transient(exc: BaseException) -> bool:
    """Decide whether an SMB error is a dead session rather than a real fault.

    The NtStatus check is first and is the load-bearing one. An expired
    session surfaces as `SMBOSError`, which subclasses **OSError, not
    ConnectionError**, and whose type name contains neither "ConnectionClosed"
    nor "Disconnect" — so the type-based tests below never saw it, and a
    router that had simply idled the session out was reported as a permanent
    failure with no reconnect attempted. That is what broke `kodi.fetch_base`:
    the mirror download takes long enough that the session is routinely gone
    before the upload begins, and the listing before it reported a full share
    as empty for the same reason.

    The type-based tests are kept underneath because a socket that dies
    mid-transfer raises before any NtStatus is parsed.

    **PARAMETERS:**
        `exc` (BaseException): The failure to classify.  <br>

    **RETURNS:**
        `bool`: Whether reconnecting and retrying is worth a try.  <br>
    """
    if getattr(exc, "ntstatus", None) in _SESSION_GONE:
        return True
    name = type(exc).__name__
    return isinstance(exc, (ConnectionError, BrokenPipeError, TimeoutError)) or "ConnectionClosed" in name or "Disconnect" in name
