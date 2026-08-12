"""Which identifier `kodi.check` asks a device about.

Kodi's package name differs per platform -- `org.xbmc.kodi` on Android,
`tv.kodi.Kodi` under Flatpak. Asking for the wrong one does not fail; it
reports the app as absent, which is how a Steam Deck running Kodi perfectly
well showed no version in the panel while its skin version resolved fine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.apps.kodi import health
from fleetctl.apps.kodi.spec import IDENTIFIERS, state_spec
from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.state import AppStateSpec
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.step import DeviceStepContext

SKIN_XML = '<addon id="skin.arctic.fuse.3" version="3.2.15">'


class _StubState:
    """A state manager for one platform, with a fixed profile root."""

    def __init__(self, platform: str, root: str) -> None:
        self._platform, self._root = platform, root

    @property
    def platform(self) -> str:
        return self._platform

    def state_root(self, spec: AppStateSpec) -> str:
        return self._root

    def snapshot(self, spec: AppStateSpec, destination: Path) -> Path:
        raise AssertionError("check must not move state")

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        raise AssertionError("check must not move state")


class _RecordingApps:
    """Answers a version only for the identifier it was built with."""

    def __init__(self, installed: str, version: str = "21.3") -> None:
        self.installed, self.version = installed, version
        self.asked: list[str] = []

    def installed_version(self, identifier: str) -> str:
        self.asked.append(identifier)
        return self.version if identifier == self.installed else ""

    def installed_abi(self, identifier: str) -> str:
        return "armeabi-v7a" if identifier == self.installed else ""

    def launch(self, identifier: str) -> None:
        raise AssertionError("check launches nothing")

    def install(self, package: Path, *, identifier: str = "") -> None:
        raise AssertionError("check installs nothing")

    def stop(self, identifier: str) -> None:
        raise AssertionError("check stops nothing")


def _context(tmp_path: Path, platform: str, apps: _RecordingApps) -> DeviceStepContext:
    root = "/home/deck/.var/app/tv.kodi.Kodi/data" if platform == "linux" else "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"
    transport = FakeTransport(responses={f"cat {root}/addons/skin.arctic.fuse.3/addon.xml": SKIN_XML})
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    inventory = DeviceStore(tmp_path / "devices.yml")
    device = Device(id="device-1", type=platform, address="192.168.1.50")
    inventory.save([device])
    return DeviceStepContext(
        device=device,
        transport=transport,
        state=_StubState(platform, root),
        apps=apps,
        artifacts=LocalArtifactStore(tmp_path / "store"),
        inventory=inventory,
        config={},
        handle=OperationRegistry().start(f"op-{platform}", health.CHECK.id, device.id),
        workspace=workspace,
    )


@pytest.mark.parametrize("platform", ["android", "linux"])
def test_check_asks_for_the_platforms_own_identifier(tmp_path: Path, platform: str) -> None:
    # Arrange
    expected = IDENTIFIERS[platform]
    apps = _RecordingApps(installed=expected)

    # Act
    result = health.check(_context(tmp_path, platform, apps))

    # Assert
    assert apps.asked == [expected]
    assert result.facts["kodi_version"] == "21.3"


def test_a_flatpak_install_is_not_reported_as_absent(tmp_path: Path) -> None:
    """The Steam Deck symptom exactly: the skin version resolves because it is
    read from a path the pack supplies, while the Kodi version comes back empty
    because the identifier was hardcoded to Android's."""
    # Arrange
    apps = _RecordingApps(installed=IDENTIFIERS["linux"])

    # Act
    result = health.check(_context(tmp_path, "linux", apps))

    # Assert
    assert result.facts["kodi_version"] == "21.3"
    assert result.facts["arctic_fuse"] == "3.2.15"
    assert IDENTIFIERS["android"] not in apps.asked


def test_an_app_absent_on_its_own_platform_still_reports_the_skin(tmp_path: Path) -> None:
    """Kodi uninstalled but its profile left behind: report what is true."""
    # Arrange
    apps = _RecordingApps(installed="something.else")

    # Act
    result = health.check(_context(tmp_path, "linux", apps))

    # Assert
    assert "kodi_version" not in result.facts
    assert result.facts["arctic_fuse"] == "3.2.15"


def test_the_spec_agrees_with_the_identifier_table() -> None:
    """`identifier_for` is what check now calls; it must resolve both."""
    # Act / Assert
    assert state_spec().identifier_for("linux") == IDENTIFIERS["linux"]
    assert state_spec().identifier_for("android") == IDENTIFIERS["android"]
