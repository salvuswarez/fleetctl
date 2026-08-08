"""Tests for the Android `apps` verb, and the check step both packs provide."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fleetctl.apps.kodi.spec import state_spec
from fleetctl.core.appmgr import AppManager
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.packs.android.appmgr import AndroidAppManager
from fleetctl.packs.android.quirks import AndroidQuirks
from fleetctl.packs.firetv.pack import FireTvPack
from fleetctl.packs.shield.pack import ShieldPack

DUMPSYS = "dumpsys package org.xbmc.kodi"


def test_the_android_manager_satisfies_the_protocol() -> None:
    assert isinstance(AndroidAppManager(FakeTransport()), AppManager)


def test_it_reads_the_installed_version() -> None:
    # Arrange
    transport = FakeTransport(responses={DUMPSYS: "  versionCode=213\n  versionName=21.3\n"})

    # Act / Assert
    assert AndroidAppManager(transport).installed_version("org.xbmc.kodi") == "21.3"


def test_an_absent_package_reports_no_version_rather_than_failing() -> None:
    """ "Not installed" is a normal answer, not an error."""
    # Arrange
    transport = FakeTransport(responses={DUMPSYS: ""})

    # Act / Assert
    assert AndroidAppManager(transport).installed_version("org.xbmc.kodi") == ""


def test_installing_stages_the_apk_and_cleans_up(tmp_path: Path) -> None:
    """`pm install` reads a path on the device, so the file has to get there
    first -- and leaving it behind wastes space a stick does not have."""
    # Arrange
    apk = tmp_path / "kodi.apk"
    apk.write_bytes(b"apk" * 100)
    transport = FakeTransport(responses={"pm install -r /sdcard/kodi.apk": "Success"})

    # Act
    AndroidAppManager(transport).install(apk, identifier="org.xbmc.kodi")

    # Assert
    issued = transport.commands()
    assert "pm install -r /sdcard/kodi.apk" in issued
    assert issued.count("rm -f /sdcard/kodi.apk") == 2  # before and after
    assert any(call.kind == "put" for call in transport.calls)


def test_the_staged_apk_is_removed_even_when_the_install_fails(tmp_path: Path) -> None:
    # Arrange
    apk = tmp_path / "kodi.apk"
    apk.write_bytes(b"apk")
    transport = FakeTransport(failures={"pm install -r /sdcard/kodi.apk": "INSTALL_FAILED"})

    # Act
    with pytest.raises(Exception):
        AndroidAppManager(transport).install(apk)

    # Assert
    assert transport.commands().count("rm -f /sdcard/kodi.apk") == 2


def test_staging_follows_the_packs_own_quirks(tmp_path: Path) -> None:
    # Arrange
    apk = tmp_path / "kodi.apk"
    apk.write_bytes(b"apk")
    quirks = AndroidQuirks(external_storage="/storage/emulated/0")
    transport = FakeTransport(responses={"pm install -r /storage/emulated/0/kodi.apk": "Success"})

    # Act
    AndroidAppManager(transport, quirks).install(apk)

    # Assert
    assert "pm install -r /storage/emulated/0/kodi.apk" in transport.commands()


def test_stopping_an_app_force_stops_it() -> None:
    # Arrange
    transport = FakeTransport(responses={"am force-stop org.xbmc.kodi": ""})

    # Act
    AndroidAppManager(transport).stop("org.xbmc.kodi")

    # Assert
    assert "am force-stop org.xbmc.kodi" in transport.commands()


HEALTH = {
    "getprop ro.product.model": "AFTKA",
    "getprop ro.product.manufacturer": "Amazon",
    "getprop ro.serialno": "SER1",
    "getprop ro.build.version.release": "9",
    "settings get global device_name": "Living Room",
    "cat /proc/uptime": "77040.5 300000.0",
    "df -k /sdcard": "Filesystem 1K-blocks Used Available\n/dev/fuse 8000000 5000000 3000000",
}


@pytest.mark.parametrize("pack", [FireTvPack(), ShieldPack()])
def test_check_reports_identity_uptime_and_space(pack: Any, device_context: Any) -> None:
    """Read-only throughout, so it stays runnable fleet-wide without approval."""
    # Arrange
    context = device_context(FakeTransport(responses=HEALTH))

    # Act
    result = pack.check(context)

    # Assert
    assert result.facts["model"] == "AFTKA"
    assert result.facts["uptime_hours"] == "21.4"
    assert result.facts["free_mb"] == "2929"


@pytest.mark.parametrize("pack", [FireTvPack(), ShieldPack()])
def test_check_survives_a_device_that_answers_nothing(pack: Any, device_context: Any) -> None:
    # Arrange
    context = device_context(FakeTransport())

    # Act
    result = pack.check(context)

    # Assert
    assert "no response" in result.summary


def test_the_shield_maintains_when_packages_are_configured(device_context: Any) -> None:
    # Arrange
    transport = FakeTransport(responses={"pm disable-user --user 0 com.example.one": "", "pm list packages -d": "", "pm trim-caches 16G": ""})
    context = device_context(transport, config={"bloat_packages": ["com.example.one"]})

    # Act
    result = ShieldPack().maintain(context)

    # Assert
    assert result.facts["disabled"] == 1
    assert "pm trim-caches 16G" in transport.commands()


def test_the_shield_pack_exposes_its_transport_and_managers(tmp_path: Path) -> None:
    # Arrange
    pack = ShieldPack()
    transport = FakeTransport()

    # Act / Assert
    assert pack.state_manager(transport).platform == "android"
    assert isinstance(pack.app_manager(transport), AppManager)
    assert pack.state_root(transport, state_spec()).endswith(".kodi")
