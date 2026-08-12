"""Tests for the Android `state` verb.

This is where decision 3 is cashed out: the pack owns paths, archive tooling,
staging and free space. An app pack issues no `tar` command and knows no
on-device path — so a vendor quirk cannot leak into `apps/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.core.errors import FleetError, TransportError
from fleetctl.core.state import AppStateSpec
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.android.quirks import AndroidQuirks
from fleetctl.packs.android.state import AndroidStateManager

SPEC = AppStateSpec(
    app_id="demo",
    identifiers={"android": "com.example.demo"},
    app_roots={"android": ".demo"},
    members=("addons", "userdata"),
    exclude=("userdata/Thumbnails", "temp"),
)

ROOT = "/sdcard/Android/data/com.example.demo/files/.demo"

FIRE_OS = AndroidQuirks(split_gzip=True, verify_disable_user=True)
STOCK = AndroidQuirks()


def _ok_responses(archive: str) -> dict[str, str]:
    plain = archive.removesuffix(".gz")
    return {
        f"tar cf {plain} -C /sdcard/Android/data/com.example.demo/files .demo": "",
        f"gzip {plain}": "",
        f"tar czf {archive} -C /sdcard/Android/data/com.example.demo/files .demo": "",
        archive: "archive-bytes",
        f"gzip -d {archive}": "",
        f"tar xf {plain} -C {ROOT}": "",
        f"tar xzf {archive} -C {ROOT}": "",
        f"mkdir -p {ROOT}": "",
        f"ls -1 {ROOT}/addons 2>/dev/null | wc -l": "1",
        f"ls -1 {ROOT}/userdata 2>/dev/null | wc -l": "1",
    }


def test_state_root_is_resolved_from_the_apps_own_identifier() -> None:
    """The app declares a package name; the pack knows the layout."""
    # Arrange
    manager = AndroidStateManager(FakeTransport(), FIRE_OS)

    # Act / Assert
    assert manager.state_root(SPEC) == ROOT


def test_an_app_with_no_identifier_for_this_platform_is_rejected() -> None:
    # Arrange
    manager = AndroidStateManager(FakeTransport(), FIRE_OS)
    spec = AppStateSpec(app_id="other", identifiers={"linux": "demo"})

    # Act / Assert
    with pytest.raises(FleetError):
        manager.state_root(spec)


def test_snapshot_splits_tar_and_gzip_when_the_quirk_is_declared(tmp_path: Path) -> None:
    """toybox `tar -z` silently truncates on Fire OS; `tar` then `gzip` is
    the verified-clean path."""
    # Arrange
    destination = tmp_path / "capture.tar.gz"
    transport = FakeTransport(responses=_ok_responses("/sdcard/capture.tar.gz"))
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    manager.snapshot(SPEC, destination)

    # Assert
    issued = transport.commands()
    assert "tar cf /sdcard/capture.tar -C /sdcard/Android/data/com.example.demo/files .demo" in issued
    assert "gzip /sdcard/capture.tar" in issued
    assert not [command for command in issued if "tar czf" in command]


def test_snapshot_uses_single_step_tar_on_stock_android(tmp_path: Path) -> None:
    """The quirk is Amazon's, so a device without it must not pay the cost."""
    # Arrange
    destination = tmp_path / "capture.tar.gz"
    transport = FakeTransport(responses=_ok_responses("/sdcard/capture.tar.gz"))
    manager = AndroidStateManager(transport, STOCK)

    # Act
    manager.snapshot(SPEC, destination)

    # Assert
    issued = transport.commands()
    assert any(command.startswith("tar czf") for command in issued)
    assert not [command for command in issued if command.startswith("gzip /sdcard")]


def test_snapshot_trims_excluded_paths_on_device_first(tmp_path: Path) -> None:
    """Trimming before archiving keeps the archive small, rather than
    shipping caches and cleaning up afterwards."""
    # Arrange
    transport = FakeTransport(responses=_ok_responses("/sdcard/capture.tar.gz"))
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    issued = transport.commands()
    assert f"rm -rf {ROOT}/userdata/Thumbnails" in issued
    assert f"rm -rf {ROOT}/temp" in issued


def test_restore_replaces_members_and_extracts_flat(tmp_path: Path) -> None:
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 1024)
    transport = FakeTransport(responses=_ok_responses("/sdcard/build.tar.gz"))
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    manager.restore(SPEC, archive)

    # Assert
    issued = transport.commands()
    assert f"rm -rf {ROOT}/addons" in issued
    assert f"rm -rf {ROOT}/userdata" in issued
    assert "gzip -d /sdcard/build.tar.gz" in issued
    assert f"tar xf /sdcard/build.tar -C {ROOT}" in issued


def test_restore_refuses_when_the_device_lacks_headroom(tmp_path: Path) -> None:
    """At peak the device holds the archive, its decompressed form, and the
    extracted tree at once."""
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 1_000_000)
    transport = FakeTransport(responses=_ok_responses("/sdcard/build.tar.gz"), free_space=1_500_000)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act / Assert
    with pytest.raises(FleetError) as caught:
        manager.restore(SPEC, archive)
    assert "free space" in str(caught.value)


def test_restore_verifies_the_extracted_tree(tmp_path: Path) -> None:
    """`tar` exiting cleanly is not proof the payload arrived: a truncated
    archive extracts into a half-populated tree the app then rebuilds from."""
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 1024)
    responses = _ok_responses("/sdcard/build.tar.gz")
    responses[f"ls -1 {ROOT}/userdata 2>/dev/null | wc -l"] = "0"
    transport = FakeTransport(responses=responses)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act / Assert
    with pytest.raises(TransportError) as caught:
        manager.restore(SPEC, archive)
    assert "userdata" in str(caught.value)


def test_unpack_timeout_scales_with_archive_size(tmp_path: Path) -> None:
    """A flat timeout is how the predecessor silently truncated archives on
    slower devices."""
    # Arrange
    manager = AndroidStateManager(FakeTransport(), FIRE_OS)

    # Act
    small = manager._unpack_timeout(1024)
    large = manager._unpack_timeout(2_000_000_000)

    # Assert
    assert small == 180.0
    assert large > 180.0
