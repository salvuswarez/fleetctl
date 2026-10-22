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
DONE = "__fleetctl_done__"
CLEAR_STAGING = "rm -rf /sdcard/fleetctl && mkdir -p /sdcard/fleetctl"

FIRE_OS = AndroidQuirks(split_gzip=True, verify_disable_user=True)
STOCK = AndroidQuirks()


def _ok_responses(archive: str) -> dict[str, str]:
    plain = archive.removesuffix(".gz")
    return {
        CLEAR_STAGING: "",
        f"rm -f {archive} {plain}": "",
        f"tar cf {plain} -C /sdcard/Android/data/com.example.demo/files .demo && echo {DONE}": DONE,
        f"gzip {plain} && echo {DONE}": DONE,
        f"tar czf {archive} -C /sdcard/Android/data/com.example.demo/files .demo && echo {DONE}": DONE,
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
    transport = FakeTransport(responses=_ok_responses("/sdcard/fleetctl/capture.tar.gz"))
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    manager.snapshot(SPEC, destination)

    # Assert
    issued = transport.commands()
    assert f"tar cf /sdcard/fleetctl/capture.tar -C /sdcard/Android/data/com.example.demo/files .demo && echo {DONE}" in issued
    assert f"gzip /sdcard/fleetctl/capture.tar && echo {DONE}" in issued
    assert not [command for command in issued if "tar czf" in command]


def test_snapshot_uses_single_step_tar_on_stock_android(tmp_path: Path) -> None:
    """The quirk is Amazon's, so a device without it must not pay the cost."""
    # Arrange
    destination = tmp_path / "capture.tar.gz"
    transport = FakeTransport(responses=_ok_responses("/sdcard/fleetctl/capture.tar.gz"))
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
    transport = FakeTransport(responses=_ok_responses("/sdcard/fleetctl/capture.tar.gz"))
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
    transport = FakeTransport(responses=_ok_responses("/sdcard/fleetctl/build.tar.gz"))
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    manager.restore(SPEC, archive)

    # Assert
    issued = transport.commands()
    assert f"rm -rf {ROOT}/addons" in issued
    assert f"rm -rf {ROOT}/userdata" in issued
    assert "gzip -d /sdcard/fleetctl/build.tar.gz" in issued
    assert f"tar xf /sdcard/fleetctl/build.tar -C {ROOT}" in issued


def test_restore_refuses_when_the_device_lacks_headroom(tmp_path: Path) -> None:
    """At peak the device holds the archive, its decompressed form, and the
    extracted tree at once."""
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 1_000_000)
    transport = FakeTransport(responses=_ok_responses("/sdcard/fleetctl/build.tar.gz"), free_space=1_500_000)
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
    responses = _ok_responses("/sdcard/fleetctl/build.tar.gz")
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


def _execs_after(transport: FakeTransport, kind: str) -> list[str]:
    """RETURNS: list[str]: Commands issued after the last `kind` transfer — what a `finally` ran."""
    kinds = [call.kind for call in transport.calls]
    start = len(kinds) - kinds[::-1].index(kind)
    return [call.argument for call in transport.calls[start:] if call.kind == "exec"]


def test_snapshot_removes_the_staging_archive_when_the_pull_fails(tmp_path: Path) -> None:
    """A pull that died mid-stream left its archive on the device; fourteen of
    those filled a SHIELD's external storage."""
    # Arrange
    responses = _ok_responses("/sdcard/fleetctl/capture.tar.gz")
    del responses["/sdcard/fleetctl/capture.tar.gz"]
    transport = FakeTransport(responses=responses)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(TransportError) as caught:
        manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    assert "no scripted content" in str(caught.value)
    assert transport.commands()[-1] == "rm -f /sdcard/fleetctl/capture.tar.gz /sdcard/fleetctl/capture.tar"


def test_snapshot_raises_and_removes_the_plain_tar_when_gzip_fails(tmp_path: Path) -> None:
    """With the disk full, `gzip` fails and leaves the plain `.tar` — 1.45GB of it."""
    # Arrange
    responses = _ok_responses("/sdcard/fleetctl/capture.tar.gz")
    responses[f"gzip /sdcard/fleetctl/capture.tar && echo {DONE}"] = "gzip: /sdcard/fleetctl/capture.tar.gz: No space left on device"
    transport = FakeTransport(responses=responses)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(TransportError) as caught:
        manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    assert "No space left" in str(caught.value)
    assert not [call for call in transport.calls if call.kind == "get"]
    assert transport.commands()[-1] == "rm -f /sdcard/fleetctl/capture.tar.gz /sdcard/fleetctl/capture.tar"


def test_snapshot_does_not_compress_a_tar_that_failed(tmp_path: Path) -> None:
    """ADB reports no exit status, so a failed `tar` used to be noticed only at the pull."""
    # Arrange
    responses = _ok_responses("/sdcard/fleetctl/capture.tar.gz")
    responses[f"tar cf /sdcard/fleetctl/capture.tar -C /sdcard/Android/data/com.example.demo/files .demo && echo {DONE}"] = "tar: write error"
    transport = FakeTransport(responses=responses)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(TransportError) as caught:
        manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    assert "tar failed" in str(caught.value)
    assert not [command for command in transport.commands() if command.startswith("gzip")]


def test_snapshot_refuses_before_archiving_when_the_device_lacks_space(tmp_path: Path) -> None:
    """Split gzip holds the plain tar and its compressed copy at once: 2x the tree."""
    # Arrange
    responses = _ok_responses("/sdcard/fleetctl/capture.tar.gz")
    responses[f"du -sk {ROOT}"] = f"1000000\t{ROOT}"
    transport = FakeTransport(responses=responses, free_space=1_500_000 * 1024)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(FleetError) as caught:
        manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    assert "free space" in str(caught.value)
    assert not [command for command in transport.commands() if command.startswith(("tar", "gzip"))]


def test_snapshot_proceeds_when_the_tree_fits(tmp_path: Path) -> None:
    # Arrange
    responses = _ok_responses("/sdcard/fleetctl/capture.tar.gz")
    responses[f"du -sk {ROOT}"] = f"1000000\t{ROOT}"
    transport = FakeTransport(responses=responses, free_space=2_500_000 * 1024)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    result = manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    assert result.read_text() == "archive-bytes"


def test_snapshot_removes_the_staging_archive_exactly_once_on_success(tmp_path: Path) -> None:
    # Arrange
    transport = FakeTransport(responses=_ok_responses("/sdcard/fleetctl/capture.tar.gz"))
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    assert _execs_after(transport, "get") == ["rm -f /sdcard/fleetctl/capture.tar.gz /sdcard/fleetctl/capture.tar"]


def test_a_failed_cleanup_does_not_mask_the_original_error(tmp_path: Path) -> None:
    # Arrange
    responses = _ok_responses("/sdcard/fleetctl/capture.tar.gz")
    del responses["/sdcard/fleetctl/capture.tar.gz"]
    del responses["rm -f /sdcard/fleetctl/capture.tar.gz /sdcard/fleetctl/capture.tar"]
    transport = FakeTransport(responses=responses, failures={"rm -f /sdcard/fleetctl/capture.tar.gz /sdcard/fleetctl/capture.tar": "device offline"})
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(TransportError) as caught:
        manager.snapshot(SPEC, tmp_path / "capture.tar.gz")

    # Assert
    assert "no scripted content" in str(caught.value)


def test_restore_removes_the_staged_archive_when_the_push_fails(tmp_path: Path) -> None:
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 1024)
    transport = FakeTransport(responses=_ok_responses("/sdcard/fleetctl/build.tar.gz"), failures={"/sdcard/fleetctl/build.tar.gz": "connection reset"})
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(TransportError):
        manager.restore(SPEC, archive)

    # Assert
    assert _execs_after(transport, "put") == ["rm -f /sdcard/fleetctl/build.tar.gz /sdcard/fleetctl/build.tar"]


def test_restore_removes_the_unpacked_tar_when_extraction_fails(tmp_path: Path) -> None:
    # Arrange
    archive = tmp_path / "build.tar.gz"
    archive.write_bytes(b"x" * 1024)
    responses = _ok_responses("/sdcard/fleetctl/build.tar.gz")
    del responses[f"tar xf /sdcard/fleetctl/build.tar -C {ROOT}"]
    transport = FakeTransport(responses=responses)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(TransportError):
        manager.restore(SPEC, archive)

    # Assert
    assert transport.commands()[-1] == "rm -f /sdcard/fleetctl/build.tar.gz /sdcard/fleetctl/build.tar"


@pytest.mark.parametrize("archive_name", ["capture.tar.gz", "build.tar.gz"])
def test_staging_is_cleared_before_free_space_is_measured(tmp_path: Path, archive_name: str) -> None:
    """A capture killed by a restart never reaches its `finally`. Its 1.2GB `.tar`
    stayed on a Fire Stick and failed every later deploy's space check by 30MB,
    so the leftover has to be gone before space is measured, not after."""
    # Arrange
    archive = tmp_path / archive_name
    archive.write_bytes(b"x" * 1_000_000)
    responses = _ok_responses(f"/sdcard/fleetctl/{archive_name}")
    responses[f"du -sk {ROOT}"] = f"1000000\t{ROOT}"
    transport = FakeTransport(responses=responses, free_space=1)
    manager = AndroidStateManager(transport, FIRE_OS)

    # Act
    with pytest.raises(FleetError) as caught:
        if archive_name.startswith("build"):
            manager.restore(SPEC, archive)
        else:
            manager.snapshot(SPEC, archive)

    # Assert
    assert "free space" in str(caught.value)
    assert CLEAR_STAGING in transport.commands()
