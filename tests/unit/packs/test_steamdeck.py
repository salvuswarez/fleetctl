"""The Steam Deck pack, and the third device type's answer to the S5 question.

Fire Stick, Shield, Steam Deck: three device types, two platforms, two
transports, one Kodi app pack. If adding SteamOS required a branch in
`apps/kodi`, the capability indirection would have failed.

Every canned response here was read off a Steam Deck OLED running SteamOS
3.8.24 on 2026-08-06, not invented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.apps.kodi.spec import state_spec
from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import FleetError, TransportError
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.android.state import AndroidStateManager
from fleetctl.packs.firetv.pack import FireTvPack
from fleetctl.packs.linux_host.pack import LinuxHostPack
from fleetctl.packs.posix.appmgr import FlatpakAppManager
from fleetctl.packs.posix.state import PosixStateManager
from fleetctl.packs.steamdeck.pack import SteamDeckPack

STEAMOS_FACTS = {
    "cat /etc/os-release": 'NAME="SteamOS"\nID=steamos\nID_LIKE=arch\nVARIANT_ID=steamdeck\nVERSION_ID=3.8.24',
    "uname -n": "steamdeck",
    "uname -r": "6.16.12-valve24.5-1-neptune",
    "uname -m": "x86_64",
}

DEBIAN_FACTS = {
    "cat /etc/os-release": 'NAME="Debian GNU/Linux"\nID=debian\nVERSION_ID="12"',
    "uname -n": "workshop",
    "uname -r": "6.1.0-18-amd64",
    "uname -m": "x86_64",
}

HOME = "/home/deck"
# Verified on hardware: the members sit directly in the Flatpak data dir.
# There is no `.kodi` below it.
KODI_ROOT = f"{HOME}/.var/app/tv.kodi.Kodi/data"
STAGING = f"{HOME}/.cache/fleetctl"


def _deck_transport(extra: dict[str, str] | None = None) -> FakeTransport:
    return FakeTransport(responses={**STEAMOS_FACTS, "echo $HOME": HOME, **(extra or {})})


def test_the_deck_pack_claims_a_steamos_host() -> None:
    # Act
    claimed = SteamDeckPack().probe(_deck_transport())

    # Assert
    assert claimed is not None
    assert claimed["type"] == "steamdeck"
    assert claimed["model"] == "steamos"
    assert claimed["name"] == "steamdeck"


def test_the_deck_pack_does_not_claim_a_generic_linux_host() -> None:
    # Act / Assert
    assert SteamDeckPack().probe(_deck_transport(DEBIAN_FACTS)) is None


def test_the_deck_probes_ahead_of_the_generic_linux_pack() -> None:
    """A Deck answers every generic Linux probe, so whichever pack knows its
    quirks must get first refusal or the generic one wins by ordering."""
    # Act / Assert
    assert SteamDeckPack.probe_priority < LinuxHostPack.probe_priority


def test_the_two_linux_packs_never_both_claim_the_same_host() -> None:
    # Arrange
    deck, debian = _deck_transport(), FakeTransport(responses=DEBIAN_FACTS)

    # Act / Assert
    assert SteamDeckPack().probe(deck) is not None
    assert LinuxHostPack().probe(deck) is None
    assert SteamDeckPack().probe(debian) is None
    assert LinuxHostPack().probe(debian) is not None


def test_the_deck_does_not_inherit_conventional_linux_assumptions() -> None:
    """Measured on hardware: `/` is READONLY and `sudo -n` needs a password."""
    # Act
    quirks = SteamDeckPack().quirks

    # Assert
    assert quirks.writable_root is False
    assert quirks.use_sudo is False
    assert quirks.staging_dir.startswith("~")


def test_the_deck_does_not_inherit_the_fire_os_archive_quirk() -> None:
    """GNU tar 1.35 round-trips `tar czf` correctly here. `split_gzip` is
    Amazon's toybox bug and is not even offered by the POSIX base."""
    # Act / Assert
    assert not hasattr(SteamDeckPack().quirks, "split_gzip")


def test_the_pack_is_not_a_subclass_of_any_other_pack() -> None:
    """Composition, not inheritance — asserted rather than assumed."""
    # Act / Assert
    assert SteamDeckPack.__bases__ == (object,)
    assert not issubclass(SteamDeckPack, LinuxHostPack)


def test_the_deck_declares_the_verbs_kodi_deploy_needs() -> None:
    """Without these, `kodi.deploy` is blocked at plan time."""
    # Act / Assert
    assert {Capability.EXEC, Capability.FILES, Capability.STATE, Capability.APPS} <= SteamDeckPack.capabilities


def test_the_kodi_state_root_has_no_dot_kodi_wrapper() -> None:
    """The assumption that cost a wrong guess: under Flatpak the sandboxed
    data directory *is* the profile. Writing to `data/.kodi` would land in a
    directory Kodi never reads."""
    # Act
    root = PosixStateManager(_deck_transport(), SteamDeckPack().quirks).state_root(state_spec())

    # Assert
    assert root == KODI_ROOT
    assert not root.endswith(".kodi")


def test_the_same_kodi_spec_resolves_on_android_and_on_a_deck() -> None:
    """One app, two platforms, no branch in the app pack."""
    # Arrange
    spec = state_spec()

    # Act
    android_root = AndroidStateManager(FakeTransport(), FireTvPack().quirks).state_root(spec)
    deck_root = PosixStateManager(_deck_transport(), SteamDeckPack().quirks).state_root(spec)

    # Assert
    assert android_root == "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"
    assert deck_root == KODI_ROOT


def test_an_app_with_no_linux_identifier_fails_loudly() -> None:
    """Better than resolving to a plausible-looking wrong directory."""
    # Arrange
    from fleetctl.core.state import AppStateSpec

    spec = AppStateSpec(app_id="nosuch", identifiers={"android": "com.example"})

    # Act / Assert
    with pytest.raises(FleetError, match="no identifier for platform 'linux'"):
        PosixStateManager(_deck_transport(), SteamDeckPack().quirks).state_root(spec)


def test_snapshot_builds_a_flat_archive_of_the_members(tmp_path: Path) -> None:
    """Flat, with no wrapping directory, so a restore extracts straight into
    the state root. That layout is part of the build contract."""
    # Arrange
    destination = tmp_path / "deck.tar.gz"
    spec = state_spec(exclude=())
    transport = _deck_transport(
        {
            f"tar czf {STAGING}/deck.tar.gz -C {KODI_ROOT} addons userdata media": "",
            f"{STAGING}/deck.tar.gz": "archive-bytes",
        }
    )

    # Act
    PosixStateManager(transport, SteamDeckPack().quirks).snapshot(spec, destination)

    # Assert
    assert f"tar czf {STAGING}/deck.tar.gz -C {KODI_ROOT} addons userdata media" in transport.commands()
    assert destination.read_bytes() == b"archive-bytes"


def test_snapshot_never_uses_the_two_step_gzip_dance(tmp_path: Path) -> None:
    # Arrange
    transport = _deck_transport({f"tar czf {STAGING}/d.tar.gz -C {KODI_ROOT} addons userdata media": "", f"{STAGING}/d.tar.gz": "x"})

    # Act
    PosixStateManager(transport, SteamDeckPack().quirks).snapshot(state_spec(exclude=()), tmp_path / "d.tar.gz")

    # Assert
    assert not [command for command in transport.commands() if command.startswith("gzip")]


def test_snapshot_drops_the_excluded_caches(tmp_path: Path) -> None:
    # Arrange
    transport = _deck_transport({f"tar czf {STAGING}/d.tar.gz -C {KODI_ROOT} addons userdata media": "", f"{STAGING}/d.tar.gz": "x"})

    # Act
    PosixStateManager(transport, SteamDeckPack().quirks).snapshot(state_spec(), tmp_path / "d.tar.gz")

    # Assert
    assert f"rm -rf {KODI_ROOT}/userdata/Thumbnails" in transport.commands()
    assert f"rm -rf {KODI_ROOT}/userdata/Database/Textures13.db" in transport.commands()


def test_staging_lands_under_home_not_on_the_read_only_root(tmp_path: Path) -> None:
    """`/` is an immutable image here. A staged upload to a system path would
    fail after the transfer rather than before it."""
    # Arrange
    transport = _deck_transport({f"tar czf {STAGING}/d.tar.gz -C {KODI_ROOT} addons userdata media": "", f"{STAGING}/d.tar.gz": "x"})

    # Act
    PosixStateManager(transport, SteamDeckPack().quirks).snapshot(state_spec(exclude=()), tmp_path / "d.tar.gz")

    # Assert
    staged = [command for command in transport.commands() if "d.tar.gz" in command]
    assert staged and all(HOME in command for command in staged)
    assert f"mkdir -p {STAGING}" in transport.commands()


def _restore_responses() -> dict[str, str]:
    return {
        f"mkdir -p {KODI_ROOT}": "",
        f"tar xzf {STAGING}/build.tar.gz -C {KODI_ROOT}": "",
        f"ls {KODI_ROOT}/addons": "skin.arctic.fuse.3",
        f"ls {KODI_ROOT}/userdata": "guisettings.xml",
        f"ls {KODI_ROOT}/media": "art",
    }


def test_restore_replaces_the_members_and_verifies_them(tmp_path: Path) -> None:
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 4096)
    transport = _deck_transport(_restore_responses())

    # Act
    PosixStateManager(transport, SteamDeckPack().quirks).restore(state_spec(), archive)

    # Assert
    for member in ("addons", "userdata", "media"):
        assert f"rm -rf {KODI_ROOT}/{member}" in transport.commands()
    assert f"tar xzf {STAGING}/build.tar.gz -C {KODI_ROOT}" in transport.commands()


def test_restore_fails_loudly_when_a_member_landed_empty(tmp_path: Path) -> None:
    """A restore that reports success over an unusable profile is the failure
    mode this project keeps running into."""
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 4096)
    transport = _deck_transport({**_restore_responses(), f"ls {KODI_ROOT}/userdata": ""})

    # Act / Assert
    with pytest.raises(TransportError, match="verification failed"):
        PosixStateManager(transport, SteamDeckPack().quirks).restore(state_spec(), archive)


def test_restore_refuses_when_the_device_lacks_headroom(tmp_path: Path) -> None:
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * (100 * 1024 * 1024))
    transport = _deck_transport(_restore_responses())
    transport.free_space = 1024 * 1024

    # Act / Assert
    with pytest.raises(FleetError, match="Not enough free space"):
        PosixStateManager(transport, SteamDeckPack().quirks).restore(state_spec(), archive)


def test_the_deploy_upload_is_declared_destructive(tmp_path: Path) -> None:
    """The policy layer keys off this. A restore overwrites a live profile."""
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 4096)
    transport = _deck_transport(_restore_responses())

    # Act
    PosixStateManager(transport, SteamDeckPack().quirks).restore(state_spec(), archive)

    # Assert
    puts = [call for call in transport.calls if call.kind == "put"]
    assert puts and all(call.effect is Effect.DESTRUCTIVE for call in puts)


def test_the_flatpak_manager_reports_an_absent_app_as_empty() -> None:
    """ "Not installed" is a normal answer, not an error."""
    # Act / Assert
    assert FlatpakAppManager(FakeTransport()).installed_version("tv.kodi.Kodi") == ""


def test_the_flatpak_manager_reads_an_installed_version() -> None:
    """`flatpak info` output, verbatim from the Deck. `--show-version` is not
    accepted by the Flatpak on SteamOS 3.8 and silently produced nothing,
    which reported an installed Kodi as absent."""
    # Arrange
    info = "\n".join(
        [
            "Kodi - Ultimate entertainment center",
            "",
            "          ID: tv.kodi.Kodi",
            "         Ref: app/tv.kodi.Kodi/x86_64/stable",
            "      Branch: stable",
            "     Version: 21.3-Omega",
            "      Origin: flathub",
        ]
    )
    transport = FakeTransport(responses={"flatpak info tv.kodi.Kodi": info})

    # Act / Assert
    assert FlatpakAppManager(transport).installed_version("tv.kodi.Kodi") == "21.3-Omega"


def test_a_version_is_not_confused_with_another_colon_field() -> None:
    """`Ref:` and `Branch:` also contain the branch name; only `Version:` counts."""
    # Arrange
    transport = FakeTransport(responses={"flatpak info tv.kodi.Kodi": "         Ref: app/tv.kodi.Kodi/x86_64/stable\n      Branch: stable"})

    # Act / Assert
    assert FlatpakAppManager(transport).installed_version("tv.kodi.Kodi") == ""


def test_stopping_an_app_that_is_not_running_is_not_an_error() -> None:
    """`flatpak kill` exits non-zero when the app is idle, which is the normal
    case before a deploy."""
    # Arrange
    transport = FakeTransport()

    # Act
    FlatpakAppManager(transport).stop("tv.kodi.Kodi")

    # Assert
    assert transport.commands() == ["flatpak kill tv.kodi.Kodi"]


def test_installing_a_flatpak_from_a_local_file_is_refused(tmp_path: Path) -> None:
    """Silently doing nothing would let a base-image install step report
    success having installed nothing."""
    # Act / Assert
    with pytest.raises(FleetError, match="not supported"):
        FlatpakAppManager(FakeTransport()).install(tmp_path / "kodi.flatpak", identifier="tv.kodi.Kodi")


@pytest.mark.parametrize("pack", [FireTvPack(), LinuxHostPack(), SteamDeckPack()])
def test_every_pack_satisfies_the_same_shape(pack: object) -> None:
    # Act / Assert
    for attribute in ("id", "platform", "capabilities", "probe_priority", "probe", "steps", "transport_for"):
        assert hasattr(pack, attribute), attribute


def test_adding_a_third_device_type_required_no_branch_in_the_kodi_app_pack() -> None:
    """The S5 question, asked a third time. `apps/kodi` gained a Flatpak
    identifier and a per-platform state subdirectory — both declarations of
    Kodi's own layout — but no knowledge of SteamOS or of any device type."""
    # Arrange
    import fleetctl.apps.kodi.steps as kodi_steps

    app = Path(kodi_steps.__file__).resolve().parent

    # Act
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in app.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if any(term in line.split("#", 1)[0].lower() for term in ("steamos", "steamdeck", "flatpak", "linux_host", "sshtransport", "packs."))
    ]

    # Assert
    assert offenders == []


def test_check_reports_free_space_from_the_writable_partition(device_context: Any) -> None:
    """Not the staging dir: it is `~`-relative, and `df` would receive it
    quoted so the shell would never expand it."""
    # Arrange
    transport = _deck_transport(
        {
            "cat /proc/uptime": "3600.0 7200.0",
            "df -k /home": "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/nvme0n1p8 984009868 615398940 368594544 63% /home",
        }
    )
    context = device_context(transport, device_type="steamdeck")

    # Act
    result = SteamDeckPack().check(context)

    # Assert
    assert result.facts["model"] == "steamos"
    assert result.facts["free_mb"] == "359955"
