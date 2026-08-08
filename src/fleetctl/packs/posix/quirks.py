"""POSIX host deviations, as data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class PosixQuirks:
    """Which deviations apply to a given family of POSIX hosts.

    Defaults describe a conventional mutable-root Linux box. A vendor whose
    host differs — an immutable root, a sandboxed application data area, no
    usable sudo — declares that in its own ``data/quirks.yml`` rather than
    having the base assume it.

    **PARAMETERS:**
        `writable_root` (bool): Whether paths outside the user's home can be written. False on image-based distributions where ``/`` is mounted read-only, which makes any system-path write fail late instead of at plan time.  <br>
        `use_sudo` (bool): Prefix privileged commands with ``sudo -n``. Non-interactive by design: a password prompt on a remote channel hangs until the timeout rather than failing.  <br>
        `staging_dir` (str): Directory used for staging transfers. Must be writable by the login user.  <br>
        `app_data_root` (str): Where per-application data directories live. May contain a ``{identifier}`` placeholder, substituted with the app's platform-native identifier — that is how a sandboxed layout is expressed without the base knowing about sandboxes.  <br>
        `disk_headroom` (float): Multiple of an archive's size that must be free before pushing it — at peak the host holds the archive and its extracted tree.  <br>
        `min_unpack_bytes_per_s` (float): Floor throughput assumed for unpacking, used to scale timeouts by archive size rather than using a flat one.  <br>
    """

    writable_root: bool = True
    use_sudo: bool = False
    staging_dir: str = "/tmp"
    app_data_root: str = "~"
    disk_headroom: float = 3.0
    min_unpack_bytes_per_s: float = 10_000_000.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PosixQuirks:
        """Build quirks from a pack's ``data/quirks.yml``.

        **PARAMETERS:**
            `data` (Mapping[str, Any]): Parsed quirk declarations.  <br>

        **RETURNS:**
            `PosixQuirks`: The declared quirks, with conventional-Linux defaults for anything unset.  <br>
        """
        fields = {
            "writable_root": bool,
            "use_sudo": bool,
            "staging_dir": str,
            "app_data_root": str,
            "disk_headroom": float,
            "min_unpack_bytes_per_s": float,
        }
        known = {key: caster(data[key]) for key, caster in fields.items() if key in data}
        return cls(**known)
