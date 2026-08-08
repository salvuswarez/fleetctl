"""S8: the first non-Android pack, and whether the seams held.

`packs/posix` is the second thing to compose a shared base, and `linux_host`
is the first pack whose transport is not ADB. If either required a change in
`core/`, the transport seam was Android-shaped rather than general.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.core.effects import Capability
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.firetv.pack import FireTvPack
from fleetctl.packs.linux_host.pack import LinuxHostPack
from fleetctl.packs.posix.quirks import PosixQuirks
from fleetctl.packs.posix.transport import CAPABILITIES as SSH_CAPABILITIES
from fleetctl.packs.posix.transport import SshSettings, SshTransport
from fleetctl.packs.shield.pack import ShieldPack

DEBIAN_FACTS = {
    "cat /etc/os-release": 'NAME="Debian GNU/Linux"\nID=debian\nVERSION_ID="12"',
    "uname -n": "workshop",
    "uname -r": "6.1.0-18-amd64",
    "uname -m": "x86_64",
}

# Verbatim from a Steam Deck OLED running SteamOS 3.8.24, read 2026-08-06.
STEAMOS_FACTS = {
    "cat /etc/os-release": 'NAME="SteamOS"\nID=steamos\nID_LIKE=arch\nVARIANT_ID=steamdeck\nVERSION_ID=3.8.24',
    "uname -n": "steamdeck",
    "uname -r": "6.16.12-valve24.5-1-neptune",
    "uname -m": "x86_64",
}

ANDROID_FACTS = {
    "getprop ro.product.model": "AFTKA",
    "getprop ro.product.manufacturer": "Amazon",
}


def test_the_linux_pack_claims_a_linux_host() -> None:
    # Act
    claimed = LinuxHostPack().probe(FakeTransport(responses=DEBIAN_FACTS))

    # Assert
    assert claimed is not None
    assert claimed["type"] == "linux_host"
    assert claimed["model"] == "debian"


def test_the_linux_pack_does_not_claim_an_android_device() -> None:
    """A Fire Stick answers nothing useful to `cat /etc/os-release`."""
    # Act / Assert
    assert LinuxHostPack().probe(FakeTransport(responses=ANDROID_FACTS)) is None


def test_the_android_packs_do_not_claim_a_linux_host() -> None:
    """Claiming is ordered; the wrong pack claiming a host is worse than none."""
    # Act / Assert
    assert FireTvPack().probe(FakeTransport(responses=DEBIAN_FACTS)) is None
    assert ShieldPack().probe(FakeTransport(responses=DEBIAN_FACTS)) is None


def test_the_generic_pack_declines_steamos() -> None:
    """SteamOS has a read-only root. Claiming it as a conventional Linux host
    would hand it a writable-root assumption that is false there, and the
    write would fail late rather than at plan time."""
    # Act / Assert
    assert LinuxHostPack().probe(FakeTransport(responses=STEAMOS_FACTS)) is None


def test_a_host_answering_nothing_is_not_partially_claimed() -> None:
    # Act / Assert
    assert LinuxHostPack().probe(FakeTransport()) is None


def test_the_linux_pack_declares_no_state_verb() -> None:
    """Where an app keeps its data on Linux differs between a native install
    and a Flatpak sandbox. Declaring STATE before that is settled on hardware
    would let `kodi.deploy` plan successfully and write to the wrong place."""
    # Act / Assert
    assert Capability.STATE not in LinuxHostPack.capabilities
    assert Capability.APPS not in LinuxHostPack.capabilities


def test_the_pack_declares_no_more_than_its_transport_provides() -> None:
    """Over-declaring is what fails mid-run on real hardware."""
    # Act / Assert
    assert LinuxHostPack.capabilities <= SSH_CAPABILITIES


def test_the_linux_pack_ships_conventional_defaults_and_no_sudo() -> None:
    """Turning sudo on globally would run every command on every box elevated."""
    # Act
    quirks = LinuxHostPack().quirks

    # Assert
    assert quirks.use_sudo is False
    assert quirks.writable_root is True


def test_the_pack_is_not_a_subclass_of_any_vendor_pack() -> None:
    """Composition, not inheritance — asserted rather than assumed."""
    # Act / Assert
    assert LinuxHostPack.__bases__ == (object,)


@pytest.mark.parametrize("pack", [FireTvPack(), ShieldPack(), LinuxHostPack()])
def test_every_pack_satisfies_the_same_shape(pack: object) -> None:
    # Act / Assert
    for attribute in ("id", "platform", "capabilities", "probe_priority", "probe", "steps", "transport_for"):
        assert hasattr(pack, attribute), attribute


def test_check_reports_what_the_host_answered(device_context: Any) -> None:
    # Arrange
    transport = FakeTransport(
        responses={
            **DEBIAN_FACTS,
            "cat /proc/uptime": "3600.0 7200.0",
            "df -k /tmp": "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/sda1 100000000 40000000 1048576 40% /",
        }
    )
    context = device_context(transport, device_type="linux_host")

    # Act
    result = LinuxHostPack().check(context)

    # Assert
    assert result.facts["model"] == "debian"
    assert result.facts["free_mb"] == "1024"
    assert "linux_host-1" in result.summary


def test_check_says_so_rather_than_inventing_facts(device_context: Any) -> None:
    """A step claiming success for work it did not do is the failure mode this
    project keeps running into."""
    # Arrange
    context = device_context(FakeTransport(), device_type="linux_host")

    # Act
    result = LinuxHostPack().check(context)

    # Assert
    assert result.facts == {}
    assert "no response" in result.summary


def test_ssh_settings_never_reveal_a_password_through_str() -> None:
    """`str()` on a Secret yields its mask. An SMB store once authenticated as
    the mask and silently fell back to guest."""
    # Arrange
    settings = SshSettings.from_mapping({"user": "ops", "password": "hunter2"})

    # Act / Assert
    assert settings.reveal_password() == "hunter2"
    assert "hunter2" not in repr(SshTransport("192.168.1.70", settings))


def test_ssh_settings_expand_a_key_path() -> None:
    # Act
    settings = SshSettings.from_mapping({"user": "ops", "key_path": "~/keys/id_ed25519", "port": 2222})

    # Assert
    assert settings.key_path is not None
    assert "~" not in str(settings.key_path)
    assert settings.port == 2222


def test_a_command_on_an_unopened_session_fails_loudly() -> None:
    """Returning "" here would be indistinguishable from a command that ran
    and printed nothing."""
    # Arrange
    transport = SshTransport("192.168.1.70", SshSettings(user="ops"))

    # Act / Assert
    with pytest.raises(Exception, match="not open"):
        transport.exec("uname -r")


def test_quirks_ignore_keys_they_do_not_know() -> None:
    """A data file from a newer pack must not crash an older one."""
    # Act
    quirks = PosixQuirks.from_mapping({"use_sudo": True, "invented_key": "whatever"})

    # Assert
    assert quirks.use_sudo is True
    assert quirks.staging_dir == "/tmp"


def test_adding_a_linux_pack_required_no_change_to_the_kodi_app_pack() -> None:
    """If the app pack had to learn about a third device type, the capability
    indirection would have failed."""
    # Arrange
    import fleetctl.apps.kodi.steps as kodi_steps

    app = Path(kodi_steps.__file__).resolve().parent

    # Act
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in app.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        # Precise terms only: `posixpath` is stdlib and `linux` appears in
        # ordinary prose, so matching those would flag legitimate code.
        if any(term in line.split("#", 1)[0].lower() for term in ("linux_host", "steamos", "sshtransport", "paramiko", "packs.posix"))
    ]

    # Assert
    assert offenders == []
