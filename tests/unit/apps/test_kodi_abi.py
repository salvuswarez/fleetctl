"""Architecture detection for Kodi's compiled addons.

The failure being prevented is a build whose binary addons the target cannot
execute — installs cleanly, dies on playback. The profile-name guard misses
it whenever two device types share one recipe, which is exactly the Shield's
situation today.
"""

from __future__ import annotations

import struct
import tarfile
from pathlib import Path

import pytest

from fleetctl.apps.kodi import abi, steps

# e_machine values as they appear at offset 18 of an ELF header.
ARM = 0x28
ARM64 = 0xB7
X86_64 = 0x3E


def _elf(machine: int) -> bytes:
    """RETURNS: bytes: A 20-byte ELF header stub declaring `machine`."""
    header = bytearray(b"\x7fELF" + b"\x00" * 16)
    struct.pack_into("<H", header, 18, machine)
    return bytes(header)


def _addon(profile: Path, addon_id: str, machine: int) -> None:
    """Write one binary addon into `profile`."""
    library = profile / "addons" / addon_id
    library.mkdir(parents=True, exist_ok=True)
    (library / f"{addon_id}.so").write_bytes(_elf(machine))


@pytest.mark.parametrize(
    ("machine", "expected"),
    [(ARM, "arm"), (ARM64, "arm64"), (X86_64, "x86_64")],
)
def test_machine_of_reads_the_architecture_from_the_elf_header(tmp_path: Path, machine: int, expected: str) -> None:
    # Arrange
    binary = tmp_path / "library.so"
    binary.write_bytes(_elf(machine))

    # Act
    found = abi.machine_of(binary)

    # Assert
    assert found == expected


def test_machine_of_reports_an_unknown_architecture_rather_than_dropping_it(tmp_path: Path) -> None:
    """Silently reading as "no binaries" would turn a new architecture into a
    confident all-clear."""
    # Arrange
    binary = tmp_path / "exotic.so"
    binary.write_bytes(_elf(0x1234))

    # Act / Assert
    assert abi.machine_of(binary) == "elf:0x1234"


def test_machine_of_ignores_a_file_that_is_not_an_elf_binary(tmp_path: Path) -> None:
    # Arrange
    text = tmp_path / "addon.xml"
    text.write_text("<addon id='plugin.video.umbrella'/>", encoding="utf-8")

    # Act / Assert
    assert abi.machine_of(text) == ""


def test_machine_of_ignores_a_file_too_short_to_hold_a_header(tmp_path: Path) -> None:
    # Arrange
    stub = tmp_path / "truncated.so"
    stub.write_bytes(b"\x7fELF")

    # Act / Assert
    assert abi.machine_of(stub) == ""


def test_a_build_archive_uses_gnu_long_names_not_pax(tmp_path: Path) -> None:
    """A Kodi profile routinely exceeds tar's 100-character name field. The
    `tar` on a set-top device reads GNU long-name entries but not PAX extended
    headers — given PAX it truncates mid-path, reports `bad header`, and
    aborts partway through the first member, leaving a half-restored profile
    that the device then reports as present."""
    # Arrange
    deep = tmp_path / "profile" / "addons" / "plugin.video.example" / "resources" / "lib" / "items" / "database" / "factories" / "__pycache__"
    deep.mkdir(parents=True)
    (deep / "listitem.cpython-312.pyc").write_bytes(b"x" * 32)
    (tmp_path / "profile" / "userdata").mkdir()
    (tmp_path / "profile" / "userdata" / "guisettings.xml").write_text("<settings/>", encoding="utf-8")
    output = tmp_path / "build.tar.gz"

    # Act
    steps._pack_flat(tmp_path / "profile", output)

    # Assert
    with tarfile.open(output) as archive:
        longest = max(archive.getnames(), key=len)
        members = archive.getmembers()
    assert len(longest) > 100, "fixture no longer exercises the long-name path"
    assert all(member.pax_headers == {} for member in members), "PAX headers present; a device tar cannot read these"


def test_machine_of_treats_an_unreadable_path_as_carrying_no_architecture(tmp_path: Path) -> None:
    """A profile is a directory of arbitrary files. One that cannot be opened
    is not an error — it just has no architecture to report."""
    # Arrange
    directory = tmp_path / "addons"
    directory.mkdir()

    # Act / Assert
    assert abi.machine_of(directory) == ""


def test_profile_machines_reports_every_architecture_present(tmp_path: Path) -> None:
    # Arrange
    profile = tmp_path / "profile"
    _addon(profile, "inputstream.adaptive", ARM)
    _addon(profile, "pvr.iptvsimple", ARM)
    _addon(profile, "script.module.pycryptodome", ARM64)
    (profile / "userdata").mkdir(parents=True)
    (profile / "userdata" / "guisettings.xml").write_text("<settings/>", encoding="utf-8")

    # Act
    machines = abi.profile_machines(profile)

    # Assert
    assert machines == ("arm", "arm64")


def test_profile_machines_is_empty_for_a_profile_with_no_compiled_addons(tmp_path: Path) -> None:
    """A legitimate result, not an error — such a build runs anywhere."""
    # Arrange
    profile = tmp_path / "profile"
    (profile / "addons" / "plugin.video.umbrella").mkdir(parents=True)
    (profile / "addons" / "plugin.video.umbrella" / "addon.xml").write_text("<addon/>", encoding="utf-8")

    # Act / Assert
    assert abi.profile_machines(profile) == ()


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("arm64-v8a,armeabi-v7a,armeabi", ("arm", "arm64")),
        ("armeabi-v7a,armeabi", ("arm",)),
        ("arm64-v8a", ("arm64",)),
        ("x86_64,x86", ("x86", "x86_64")),
        # A Linux host answers `uname -m` instead of an Android ABI list.
        ("aarch64", ("arm64",)),
        ("", ()),
        ("something-unheard-of", ()),
    ],
)
def test_machines_for_translates_reported_abis(reported: str, expected: tuple[str, ...]) -> None:
    # Act / Assert
    assert abi.machines_for(reported) == expected


def test_unsupported_names_what_the_device_cannot_run() -> None:
    """The Fire Stick build meeting a 64-bit-only device."""
    # Act
    missing = abi.unsupported(("arm",), ("arm64",))

    # Assert
    assert missing == ("arm",)


def test_unsupported_is_empty_when_the_device_covers_every_architecture() -> None:
    """A 64-bit ARM device that still runs 32-bit takes a Fire Stick build."""
    # Act / Assert
    assert abi.unsupported(("arm",), ("arm", "arm64")) == ()


@pytest.mark.parametrize(
    ("build", "device"),
    [((), ("arm64",)), (("arm",), ()), ((), ())],
)
def test_unsupported_gives_no_verdict_when_either_side_is_unknown(build: tuple[str, ...], device: tuple[str, ...]) -> None:
    """An unverifiable claim must not read as a confirmed failure — that is
    how a working deploy gets blocked for no reason."""
    # Act / Assert
    assert abi.unsupported(build, device) == ()
