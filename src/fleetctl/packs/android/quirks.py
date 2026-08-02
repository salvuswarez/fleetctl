"""Vendor quirks, as data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AndroidQuirks:
    """Which vendor deviations apply to a given device family.

    **PARAMETERS:**
        `split_gzip` (bool): Create archives as ``tar`` then a separate ``gzip``, and extract as ``gzip -d`` then ``tar``. Required where toybox's ``tar -z`` silently truncates: `tar` reports success and the archive is byte-identical on re-pull, so the corruption is baked in at creation.  <br>
        `push_via_netcat` (bool): Stream uploads to an on-device ``nc`` listener rather than using the ADB push protocol, which moves zero bytes beyond a few megabytes on some devices.  <br>
        `verify_disable_user` (bool): Confirm with ``pm list packages -d`` after disabling, because ``pm disable-user`` can fail silently for system packages from a non-root shell.  <br>
        `external_storage` (str): Path used for staging transfers.  <br>
        `app_data_root` (str): Where per-app external data directories live.  <br>
        `disk_headroom` (float): Multiple of an archive's size that must be free before pushing it — at peak the device holds the archive, its decompressed form, and the extracted tree.  <br>
        `min_unpack_bytes_per_s` (float): Floor throughput assumed for on-device unpacking, used to scale timeouts by archive size rather than using a flat one.  <br>
    """

    split_gzip: bool = False
    push_via_netcat: bool = False
    verify_disable_user: bool = False
    external_storage: str = "/sdcard"
    app_data_root: str = "/sdcard/Android/data"
    disk_headroom: float = 3.0
    min_unpack_bytes_per_s: float = 1_000_000.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AndroidQuirks:
        """Build quirks from a pack's ``data/quirks.yml``.

        **PARAMETERS:**
            `data` (Mapping[str, Any]): Parsed quirk declarations.  <br>

        **RETURNS:**
            `AndroidQuirks`: The declared quirks, with stock-Android defaults for anything unset.  <br>
        """
        fields = {
            "split_gzip": bool,
            "push_via_netcat": bool,
            "verify_disable_user": bool,
            "external_storage": str,
            "app_data_root": str,
            "disk_headroom": float,
            "min_unpack_bytes_per_s": float,
        }
        known = {key: caster(data[key]) for key, caster in fields.items() if key in data}
        return cls(**known)
