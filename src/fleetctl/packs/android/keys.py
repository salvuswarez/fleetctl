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

    def __init__(self, key_dir: Path, audit: ChainedAuditWriter | None = None) -> None:
        self._key_dir = key_dir
        self._audit = audit
        self._signer: Any = None

    @property
    def fingerprint(self) -> str:
        """RETURNS: str: Short identifier for the public key, for audit records. Never the private key."""
        pub_path = self._key_dir / "adbkey.pub"
        if not pub_path.is_file():
            return "unknown"
        import hashlib

        return hashlib.sha256(pub_path.read_bytes()).hexdigest()[:16]

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
        if self._audit is None:
            return
        self._audit.write(
            AuditEvent.build(
                AuditKind.AUTH,
                "adb.key.use",
                target=target,
                detail={"fingerprint": self.fingerprint},
            )
        )
