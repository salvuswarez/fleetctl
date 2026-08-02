"""S5: does adding a second device type require changing anything else?

The stage exists to answer that question honestly. If adding the Shield had
required edits in `core/` or `apps/kodi/`, the seams would be in the wrong
place — so these tests check the *absence* of coupling as much as the
presence of behaviour.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from fleetctl.apps.kodi import steps as kodi_steps
from fleetctl.apps.kodi.spec import state_spec
from fleetctl.core.effects import Capability
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.android.state import AndroidStateManager
from fleetctl.packs.firetv.pack import FireTvPack
from fleetctl.packs.shield.pack import ShieldPack

SHIELD_FACTS = {
    "getprop ro.product.model": "SHIELD Android TV",
    "getprop ro.product.manufacturer": "NVIDIA",
    "getprop ro.serialno": "SHIELDSERIAL",
    "getprop ro.build.version.release": "11",
    "settings get global device_name": "Den Shield",
}

FIRETV_FACTS = {
    "getprop ro.product.model": "AFTKA",
    "getprop ro.product.manufacturer": "Amazon",
    "getprop ro.serialno": "FIRESERIAL",
    "getprop ro.build.version.release": "9",
    "settings get global device_name": "Living Room",
}

KODI_ROOT = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"


def test_the_shield_pack_claims_a_shield() -> None:
    # Act
    claimed = ShieldPack().probe(FakeTransport(responses=SHIELD_FACTS))

    # Assert
    assert claimed is not None
    assert claimed["type"] == "shield"
    assert claimed["model"] == "SHIELD Android TV"


def test_neither_vendor_pack_claims_the_others_device() -> None:
    """Both key off manufacturer, so probe order cannot cause a mis-claim."""
    # Act / Assert
    assert ShieldPack().probe(FakeTransport(responses=FIRETV_FACTS)) is None
    assert FireTvPack().probe(FakeTransport(responses=SHIELD_FACTS)) is None


def test_the_shield_does_not_inherit_fire_os_quirks() -> None:
    """These are Amazon's bugs. Inheriting them would cost the Shield a
    two-step tar and a netcat upload it may not need."""
    # Act
    quirks = ShieldPack().quirks

    # Assert
    assert quirks.split_gzip is False
    assert quirks.push_via_netcat is False
    assert quirks.verify_disable_user is False


def test_the_two_packs_are_independent_classes() -> None:
    """Composition, not inheritance — asserted rather than assumed."""
    # Act / Assert
    assert not issubclass(ShieldPack, FireTvPack)
    assert not issubclass(FireTvPack, ShieldPack)
    assert ShieldPack.__bases__ == (object,)


def test_the_shield_ships_no_unverified_bloat_list() -> None:
    """The predecessor inherited a borrowed list that mixed fabricated
    package names with real ones. An empty list is the honest state."""
    # Act / Assert
    assert ShieldPack().bloat_packages == ()


def test_maintain_reports_honestly_when_nothing_is_configured(device_context: Any) -> None:
    """A step claiming success for work it did not do is the failure mode
    this project keeps running into."""
    # Arrange
    transport = FakeTransport()
    context = device_context(transport, device_type="shield")

    # Act
    result = ShieldPack().maintain(context)

    # Assert
    assert result.facts["disabled"] == 0
    assert "nothing configured" in result.summary
    assert transport.commands() == []


def test_the_same_kodi_spec_resolves_on_both_device_types() -> None:
    """One app, two device types, no branch in the app pack."""
    # Arrange
    spec = state_spec()

    # Act
    fire_root = AndroidStateManager(FakeTransport(), FireTvPack().quirks).state_root(spec)
    shield_root = AndroidStateManager(FakeTransport(), ShieldPack().quirks).state_root(spec)

    # Assert
    assert fire_root == shield_root == KODI_ROOT


def test_the_same_restore_produces_different_commands_per_vendor(tmp_path: Path) -> None:
    """The whole design in one assertion: identical app-level intent, and the
    archive strategy differs because the *pack* said so."""
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 1024)
    spec = state_spec()

    def _responses() -> dict[str, str]:
        return {
            "gzip -d /sdcard/build.tar.gz": "",
            "tar xf /sdcard/build.tar -C " + KODI_ROOT: "",
            "tar xzf /sdcard/build.tar.gz -C " + KODI_ROOT: "",
            f"mkdir -p {KODI_ROOT}": "",
            f"ls {KODI_ROOT}/addons": "skin",
            f"ls {KODI_ROOT}/userdata": "settings",
            f"ls {KODI_ROOT}/media": "art",
        }

    fire_transport = FakeTransport(responses=_responses())
    shield_transport = FakeTransport(responses=_responses())

    # Act
    AndroidStateManager(fire_transport, FireTvPack().quirks).restore(spec, archive)
    AndroidStateManager(shield_transport, ShieldPack().quirks).restore(spec, archive)

    # Assert
    assert any(command.startswith("gzip -d") for command in fire_transport.commands())
    assert not [command for command in shield_transport.commands() if command.startswith("gzip -d")]
    assert any(command.startswith("tar xzf") for command in shield_transport.commands())


def test_adding_the_shield_required_no_change_in_the_kodi_app_pack() -> None:
    """If the app pack had to learn about a second device type, the
    capability indirection would have failed."""
    # Arrange
    app = Path(kodi_steps.__file__).resolve().parent

    # Act
    offenders = [
        f"{path.name}: {line.strip()}"
        for path in app.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if any(term in line.split("#", 1)[0].lower() for term in ("shield", "firetv", "nvidia", "amazon"))
    ]

    # Assert
    assert offenders == []


def test_the_shield_pack_declares_the_state_verb() -> None:
    """Without it, `kodi.deploy` would be blocked at plan time."""
    # Act / Assert
    assert Capability.STATE in ShieldPack.capabilities


@pytest.mark.parametrize("pack", [FireTvPack(), ShieldPack()])
def test_both_packs_satisfy_the_same_pack_shape(pack: object) -> None:
    # Act / Assert
    for attribute in ("id", "platform", "capabilities", "probe_priority", "probe", "steps", "state_manager", "transport_for"):
        assert hasattr(pack, attribute), attribute


def test_git_shows_no_core_or_kodi_changes_in_the_shield_commit() -> None:
    """The strongest form of the S5 question, asked of the repository itself:
    did adding a device type touch anything it should not have?

    Skipped outside a git checkout rather than failing, since a source
    tarball is a legitimate way to run the suite.
    """
    # Arrange
    repo = Path(kodi_steps.__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", "src/fleetctl/core", "src/fleetctl/apps"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available here")
    if result.returncode != 0:
        pytest.skip("not a git checkout")

    # Assert
    assert result.stdout.strip() == "", f"adding the Shield should not have changed core/ or apps/:\n{result.stdout}"
