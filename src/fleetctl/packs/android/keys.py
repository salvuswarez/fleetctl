"""ADB key material."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any

from ...core.observability.audit import AuditEvent, AuditKind, ChainedAuditWriter

LOGGER = logging.getLogger(__name__)

_DIR_MODE = stat.S_IRWXU  # 0o700
_KEY_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0o600


class AdbKeyStore:
    """Holds one cached ADB signer, generating a key pair on first use.

    **PARAMETERS:**
        `key_dir` (Path): Directory holding ``adbkey`` and ``adbkey.pub``. Must live outside any git-tracked tree.  <br>
        `audit` (ChainedAuditWriter | None): Where key usage is recorded. Defaults to ``None``, meaning usage is not audited — acceptable only in tests.  <br>
    """

    # Keyed by key directory, not held per instance: a pack builds a fresh
    # store for every `transport_for`, so anything cached on `self` is thrown
    # away between connections. Per-instance state meant the key was re-read
    # from disk and a fresh `adb.key.use` event written on every single
    # connect — 194 of them in the two minutes after a restart, from a poll
    # that only asks whether a device is awake.
    _shared: dict[str, dict[str, Any]] = {}

    def __init__(self, key_dir: Path, audit: ChainedAuditWriter | None = None) -> None:
        self._key_dir = key_dir
        self._audit = audit
        self._state = self._shared.setdefault(str(key_dir.resolve()), {"signer": None, "fingerprint": "", "recorded": set()})

    @property
    def _signer(self) -> Any:
        return self._state["signer"]

    @_signer.setter
    def _signer(self, value: Any) -> None:
        self._state["signer"] = value

    @property
    def _recorded(self) -> set[str]:
        """RETURNS: set[str]: Targets already recorded for this key directory."""
        recorded: set[str] = self._state["recorded"]
        return recorded

    @property
    def fingerprint(self) -> str:
        """RETURNS: str: Short identifier for the public key, for audit records. Never the private key.

        Cached: the key pair is loaded once per store, so re-reading and
        re-hashing the file per connection is pure I/O for a constant answer.
        """
        cached: str = self._state["fingerprint"]
        if cached:
            return cached

        pub_path = self._key_dir / "adbkey.pub"
        if not pub_path.is_file():
            return "unknown"
        import hashlib

        self._state["fingerprint"] = hashlib.sha256(pub_path.read_bytes()).hexdigest()[:16]
        return str(self._state["fingerprint"])

    def signer(self, *, target: str = "") -> Any:
        """Return the cached signer, generating a key pair if none exists.

        **PARAMETERS:**
            `target` (str): Device this key is about to be used against, recorded on the audit event.  <br>

        **RETURNS:**
            `PythonRSASigner`: Signer used to authenticate ADB connections.  <br>
        """
        if self._signer is None:
            self._signer = self._load()
        self._record_use(target)
        return self._signer

    def _load(self) -> Any:
        from adb_shell.auth.keygen import keygen
        from adb_shell.auth.sign_pythonrsa import PythonRSASigner

        self._key_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._key_dir, _DIR_MODE)

        key_path = self._key_dir / "adbkey"
        pub_path = self._key_dir / "adbkey.pub"
        if not key_path.exists() or not pub_path.exists():
            LOGGER.info("Generating ADB key pair at %s", key_path)
            keygen(str(key_path))
            os.chmod(key_path, _KEY_MODE)

        return PythonRSASigner(pub_path.read_text(encoding="utf-8"), key_path.read_text(encoding="utf-8"))

    def _record_use(self, target: str) -> None:
        """Record the first use of this key against a target, and only the first.

        A polled read reconnects on every interval. Recording each one turned
        the audit trail into 8,214 `adb.key.use` events in a day against 5
        real ones — the record of what touched a device, buried under the act
        of asking whether it was awake. Deduplicating keeps the security
        signal and drops the noise.
        """
        if self._audit is None or target in self._recorded:
            return
        self._recorded.add(target)
        self._audit.write(
            AuditEvent.build(
                AuditKind.AUTH,
                "adb.key.use",
                target=target,
                detail={"fingerprint": self.fingerprint},
            )
        )
