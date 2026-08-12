"""What machine code a Kodi profile carries.

A Kodi profile is not portable. Alongside the Python addons it carries
compiled binary addons — `inputstream.adaptive`, `pvr.iptvsimple`, and the
shared objects under `script.module.*` — built for one architecture. A build
shaped from a Fire Stick capture carries 32-bit ARM; a Steam Deck runs x86-64
and a modern Android TV may be 64-bit ARM only.

The failure this exists to prevent is quiet: the wrong binaries install
cleanly, Kodi starts, and playback dies when something first dlopen()s one.
That was the Steam Deck SIGFPE, and the profile-name guard in `deploy` only
catches it when the recipe names differ — two devices sharing the `gold`
recipe defeat it entirely.

Everything here is pure: a directory in, facts out. No transport, no device.
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_ELF_MAGIC = b"\x7fELF"
# `e_machine` lives at offset 18 of an ELF header as a little-endian u16.
_E_MACHINE_OFFSET = 18
_HEADER_BYTES = 20

# Only the machines this fleet can encounter. An unrecognised value is
# reported as-is rather than dropped, so a new architecture shows up in the
# facts as `elf:0x…` instead of silently reading as "no binaries".
_MACHINES = {0x03: "x86", 0x28: "arm", 0x3E: "x86_64", 0xB7: "arm64"}

# Android's ABI names, and the machine each one needs. A device reports these
# through `ro.product.cpu.abilist`; a Linux host reports a machine directly
# via `uname -m`, so both spellings resolve here.
_ABI_MACHINES = {
    "armeabi": "arm",
    "armeabi-v7a": "arm",
    "arm64-v8a": "arm64",
    "x86": "x86",
    "x86_64": "x86_64",
    "aarch64": "arm64",
    "amd64": "x86_64",
    "armv7l": "arm",
    "i686": "x86",
}


def machine_of(path: Path) -> str:
    """Read one file's target architecture from its ELF header.

    **PARAMETERS:**
        `path` (Path): File to inspect. Need not be an ELF file.  <br>

    **RETURNS:**
        `str`: A machine name from `_MACHINES`, ``elf:0x…`` for an ELF file of unknown architecture, or ``""`` when the file is not an ELF binary at all.  <br>
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(_HEADER_BYTES)
    except OSError:
        # A profile is a directory of arbitrary files; an unreadable one is
        # not an error, it just carries no architecture.
        LOGGER.debug("Could not read %s while scanning for binaries", path)
        return ""

    if len(header) < _HEADER_BYTES or not header.startswith(_ELF_MAGIC):
        return ""
    machine = struct.unpack_from("<H", header, _E_MACHINE_OFFSET)[0]
    return _MACHINES.get(machine, f"elf:{machine:#x}")


def profile_machines(profile: Path) -> tuple[str, ...]:
    """Scan an extracted profile for the architectures its binaries target.

    **PARAMETERS:**
        `profile` (Path): An extracted profile directory.  <br>

    **RETURNS:**
        `tuple[str, ...]`: Every distinct machine found, sorted. Empty when the profile carries no compiled addons, which is a legitimate result and not an error.  <br>
    """
    found = {machine for path in profile.rglob("*") if path.is_file() and (machine := machine_of(path))}
    return tuple(sorted(found))


def machines_for(abis: str) -> tuple[str, ...]:
    """Translate a device's reported ABI list into machine names.

    **PARAMETERS:**
        `abis` (str): Comma-separated ABI names as `ro.product.cpu.abilist` reports them, or a single `uname -m` value.  <br>

    **RETURNS:**
        `tuple[str, ...]`: The machines this device can execute, sorted. Empty when nothing in `abis` is recognised.  <br>
    """
    named = {_ABI_MACHINES[token] for raw in abis.split(",") if (token := raw.strip().lower()) in _ABI_MACHINES}
    return tuple(sorted(named))


def unsupported(build_machines: tuple[str, ...], device_machines: tuple[str, ...]) -> tuple[str, ...]:
    """Find architectures in a build that a device cannot execute.

    **PARAMETERS:**
        `build_machines` (tuple[str, ...]): What the build carries, from `profile_machines`.  <br>
        `device_machines` (tuple[str, ...]): What the device can run, from `machines_for`.  <br>

    **RETURNS:**
        `tuple[str, ...]`: Machines the build needs and the device lacks, sorted. Empty means compatible — including when either side is unknown, because an unverifiable claim must not read as a confirmed failure.  <br>
    """
    if not build_machines or not device_machines:
        return ()
    return tuple(sorted(set(build_machines) - set(device_machines)))
