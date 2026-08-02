"""Tests for the shared Kodi base image."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.apps.kodi import base_image
from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.errors import FleetError
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.workflow.step import FleetStepContext

INDEX = """
<a href="kodi-21.3-Omega-armeabi-v7a.apk">kodi-21.3</a>
<a href="kodi-21.2-Omega-armeabi-v7a.apk">kodi-21.2</a>
<a href="kodi-22.0-Piers_beta1-armeabi-v7a.apk">beta</a>
<a href="kodi-21.3-Omega-arm64-v8a.apk">other arch</a>
<a href="kodi-20.5-Nexus-armeabi-v7a.apk">kodi-20.5</a>
"""


def _fleet_context(tmp_path: Path, config: dict[str, Any] | None = None) -> FleetStepContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    return FleetStepContext(
        artifacts=LocalArtifactStore(tmp_path / "store"),
        inventory=DeviceStore(tmp_path / "devices.yml"),
        config=config or {},
        handle=OperationRegistry().start("op", "kodi.fetch_base"),
        workspace=workspace,
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [("kodi-21.3-Omega-armeabi-v7a.apk", (21, 3, 0)), ("kodi-20.5.1-x.apk", (20, 5, 1)), ("not-a-kodi-build.apk", (0, 0, 0))],
)
def test_versions_sort_numerically_not_lexically(name: str, expected: tuple[int, ...]) -> None:
    """String sorting puts 21.10 below 21.3, which is how a fleet ends up
    pinned to an older release."""
    assert base_image.version_key(name) == expected


@pytest.mark.parametrize(
    ("name", "stable"),
    [
        ("kodi-21.3-Omega-armeabi-v7a.apk", True),
        ("kodi-22.0-Piers_beta1-armeabi-v7a.apk", False),
        ("kodi-22.0-rc1-armeabi-v7a.apk", False),
        ("kodi-22.0-nightly-armeabi-v7a.apk", False),
    ],
)
def test_pre_releases_are_excluded(name: str, stable: bool) -> None:
    """A fleet should not drift onto a nightly because it sorted highest."""
    assert base_image.is_stable(name) is stable


def test_the_index_yields_only_this_architectures_stable_builds() -> None:
    # Act
    names = base_image.parse_index(INDEX, "armeabi-v7a")

    # Assert
    assert names == ["kodi-21.3-Omega-armeabi-v7a.apk", "kodi-21.2-Omega-armeabi-v7a.apk", "kodi-20.5-Nexus-armeabi-v7a.apk"]


def test_a_different_architecture_selects_a_different_build() -> None:
    assert base_image.parse_index(INDEX, "arm64-v8a") == ["kodi-21.3-Omega-arm64-v8a.apk"]


def test_an_index_with_nothing_usable_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(base_image, "parse_index", lambda html, arch: [])
    monkeypatch.setattr(base_image, "_read_index", lambda url: INDEX, raising=False)

    # Act / Assert
    with pytest.raises(FleetError):
        base_image.latest_release("mips", url="https://example.invalid/")


def test_fetch_base_publishes_the_newest_stable_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(base_image, "latest_release", lambda arch, url=None: ("kodi-21.3-Omega-armeabi-v7a.apk", "21.3"))
    monkeypatch.setattr(base_image, "_download", lambda url, dest: dest.write_bytes(b"apk" * 100))
    context = _fleet_context(tmp_path)

    # Act
    result = base_image.fetch_base(context)

    # Assert
    assert result.facts == {"version": "21.3", "downloaded": True}
    assert context.artifacts.exists(result.artifacts["base"])


def test_fetching_again_does_not_re_download_the_same_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Roughly 100MB per pointless fetch, and the common case is that the
    fleet is already current."""
    # Arrange
    monkeypatch.setattr(base_image, "latest_release", lambda arch, url=None: ("kodi-21.3-Omega-armeabi-v7a.apk", "21.3"))
    downloads: list[str] = []

    def _record(url: str, dest: Path) -> None:
        downloads.append(url)
        dest.write_bytes(b"apk")

    monkeypatch.setattr(base_image, "_download", _record)
    context = _fleet_context(tmp_path)
    base_image.fetch_base(context)

    # Act
    result = base_image.fetch_base(_fleet_context(tmp_path))

    # Assert
    assert len(downloads) == 1
    assert result.facts["downloaded"] is False


def test_force_re_downloads_even_when_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(base_image, "latest_release", lambda arch, url=None: ("kodi-21.3-Omega-armeabi-v7a.apk", "21.3"))
    monkeypatch.setattr(base_image, "_download", lambda url, dest: dest.write_bytes(b"apk"))
    base_image.fetch_base(_fleet_context(tmp_path))

    # Act
    result = base_image.fetch_base(_fleet_context(tmp_path, {"force": True}))

    # Assert
    assert result.facts["downloaded"] is True


def test_check_update_reports_a_newer_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(base_image, "latest_release", lambda arch, url=None: ("kodi-21.3-x.apk", "21.3"))
    context = _fleet_context(tmp_path)
    store = context.artifacts
    payload = tmp_path / "old.apk"
    payload.write_bytes(b"x")
    store.put(payload, ArtifactRef(kind=base_image.BASE, name="kodi-20.5-x.apk"), meta={"kodi_version": "20.5"})

    # Act
    result = base_image.check_update(context)

    # Assert
    assert result.facts == {"current": "20.5", "latest": "21.3", "update_available": True}


def test_check_update_is_quiet_when_current(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(base_image, "latest_release", lambda arch, url=None: ("kodi-21.3-x.apk", "21.3"))
    context = _fleet_context(tmp_path)
    payload = tmp_path / "cur.apk"
    payload.write_bytes(b"x")
    context.artifacts.put(payload, ArtifactRef(kind=base_image.BASE, name="kodi-21.3-x.apk"), meta={"kodi_version": "21.3"})

    # Act
    result = base_image.check_update(context)

    # Assert
    assert result.facts["update_available"] is False


def test_check_update_handles_having_nothing_published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(base_image, "latest_release", lambda arch, url=None: ("kodi-21.3-x.apk", "21.3"))

    # Act
    result = base_image.check_update(_fleet_context(tmp_path))

    # Assert
    assert result.facts["current"] is None
    assert result.facts["update_available"] is True


def test_installing_without_a_published_base_says_what_to_run(tmp_path: Path, device_context: Any) -> None:
    # Arrange
    from fleetctl.core.transport.fake import FakeTransport

    context = device_context(FakeTransport())

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        base_image.install_base(context)
    assert "fetch_base" in str(caught.value)
