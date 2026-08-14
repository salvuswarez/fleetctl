"""Capturing what an Android device *is*, so a wiped one can be rebuilt.

Every scripted response here is shaped from output observed on a real SHIELD
Android TV (Android 11) on 2026-08-14 — `settings list` counts, the
`package:` prefix, and above all the split APKs, which 5 of that device's 9
third-party packages had. A double scripted from an assumed CLI would have
kept this suite green while `pm install` put back a base APK with no splits.
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Any, Mapping

import pytest
import yaml

from fleetctl.core.artifacts.ref import ArtifactRef
from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.effects import Effect
from fleetctl.core.errors import TransportError
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.state import AppStateSpec
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.step import DeviceStepContext
from fleetctl.packs.android import devicesteps
from fleetctl.packs.android.devicestate import (
    AndroidDeviceStateManager,
    DeviceStatePolicy,
    InstalledPackage,
    parse_settings,
)
from fleetctl.packs.android.quirks import AndroidQuirks

# A real `settings list secure` dump interleaves a multi-line value; the
# accessibility services list is the one observed doing it.
SECURE_DUMP = """accessibility_display_inversion_enabled=0
enabled_accessibility_services=com.example/.One:
com.example/.Two
android_id=deadbeefdeadbeef
user_setup_complete=1
"""

GLOBAL_DUMP = "device_name=Living Room\nadb_enabled=1\nPhenotype_boot_count=42\nwindow_animation_scale=0.0\n"
SYSTEM_DUMP = "screen_off_timeout=1800000\naccelerometer_rotation=0\n"

# `pm path` on the surveyed device: a base plus config splits for language,
# density and ABI. `pm list packages -f` reports only the first of these.
PLEX_SPLITS = (
    "package:/data/app/~~abc==/com.example.plex-xyz==/base.apk\n"
    "package:/data/app/~~abc==/com.example.plex-xyz==/split_config.en.apk\n"
    "package:/data/app/~~abc==/com.example.plex-xyz==/split_config.arm64_v8a.apk\n"
)

RESPONSES = {
    "settings list global": GLOBAL_DUMP,
    "settings list system": SYSTEM_DUMP,
    "settings list secure": SECURE_DUMP,
    "pm list packages -3": "package:com.example.plex\npackage:com.example.solo\n",
    "pm list packages": "package:com.example.plex\npackage:com.example.solo\npackage:com.android.settings\n",
    "pm list packages -d": "package:com.vendor.telemetry\n",
    "pm path com.example.plex": PLEX_SPLITS,
    "pm path com.example.solo": "package:/data/app/~~def==/com.example.solo-uvw==/base.apk\n",
    "dumpsys package com.example.plex": "    versionName=10.1.0\n",
    "dumpsys package com.example.solo": "    versionName=2.4\n",
}

POLICY = DeviceStatePolicy(
    capture_namespaces=("global", "system", "secure"),
    never_capture=("secure.android_id",),
    never_restore=("*.Phenotype_*", "global.adb_enabled", "secure.user_setup_complete"),
    never_install=("com.android.*",),
)


def _apk_bytes(marker: bytes = b"") -> bytes:
    """RETURNS: bytes: Something that passes the zip-header check `pull_apks` applies."""
    return b"PK\x03\x04" + marker + b"\x00" * 32


def _transport(overrides: Mapping[str, str] | None = None) -> FakeTransport:
    """Build a scripted transport.

    `FakeTransport.responses` is a `Mapping`, so overrides are folded in here
    rather than assigned afterwards — which is the right shape anyway: a double
    whose script changes mid-test is describing two devices.

    **PARAMETERS:**
        `overrides` (Mapping[str, str] | None): Extra or replacement responses, keyed by command or by remote path for a `get`.  <br>

    **RETURNS:**
        `FakeTransport`: Scripted with the Shield's observed output.  <br>
    """
    responses = dict(RESPONSES)
    # Every APK path answers with zip-shaped content, so `get` can serve it.
    for dump in (PLEX_SPLITS, RESPONSES["pm path com.example.solo"]):
        for line in dump.splitlines():
            responses.setdefault(line.partition(":")[2].strip(), _apk_bytes().decode("latin-1"))
    responses.update(overrides or {})
    return FakeTransport(responses=responses)


def _manager(transport: FakeTransport) -> AndroidDeviceStateManager:
    return AndroidDeviceStateManager(transport, AndroidQuirks(), POLICY)


def _logs(registry: OperationRegistry, op_id: str = "op-1") -> list[dict[str, str]]:
    """RETURNS: list[dict[str, str]]: What the step logged, for assertions about what it told the operator."""
    operation = registry.get(op_id)
    return list(operation.logs) if operation else []


# --------------------------------------------------------------- parsing


def test_a_multi_line_setting_value_is_rejoined_onto_its_key() -> None:
    """An accessibility-services list spans lines. Splitting on newline alone
    would store the tail as a key of its own and truncate the real value."""
    # Act
    parsed = parse_settings(SECURE_DUMP)

    # Assert
    assert parsed["enabled_accessibility_services"] == "com.example/.One:\ncom.example/.Two"
    assert parsed["android_id"] == "deadbeefdeadbeef"


def test_a_blank_dump_parses_to_nothing_rather_than_raising() -> None:
    # Act / Assert
    assert parse_settings("") == {}


# --------------------------------------------------------------- reading


def test_reading_settings_withholds_device_identifiers_and_says_which() -> None:
    """A snapshot gets copied between devices and pasted into bug reports, so
    an identifier that survives it is a leak. Named, not just counted."""
    # Arrange
    manager = _manager(_transport())

    # Act
    settings, withheld = manager.read_settings()

    # Assert
    assert "android_id" not in settings["secure"]
    assert withheld == ["secure.android_id"]
    assert settings["global"]["device_name"] == "Living Room"


def test_a_never_restore_setting_is_still_captured() -> None:
    """The two lists answer different questions: a boot counter is harmless to
    record and wrong to replay."""
    # Arrange
    manager = _manager(_transport())

    # Act
    settings, withheld = manager.read_settings()

    # Assert
    assert settings["global"]["Phenotype_boot_count"] == "42"
    assert "global.Phenotype_boot_count" not in withheld


def test_package_paths_come_from_pm_path_so_splits_are_not_lost() -> None:
    """`pm list packages -f` reports only the base APK. Installing that alone
    yields an app missing its density, language and ABI resources."""
    # Arrange
    manager = _manager(_transport())

    # Act
    inventory = manager.read_packages()

    # Assert
    plex = next(package for package in inventory.third_party if package.name == "com.example.plex")
    assert len(plex.apks) == 3
    assert plex.is_split
    assert plex.apks[0].endswith("base.apk")


def test_a_single_apk_package_is_not_marked_split() -> None:
    # Arrange
    manager = _manager(_transport())

    # Act
    inventory = manager.read_packages()

    # Assert
    solo = next(package for package in inventory.third_party if package.name == "com.example.solo")
    assert not solo.is_split


def test_system_packages_are_recorded_but_separated_from_third_party() -> None:
    """Their APKs live under /system and `pm install` cannot put them back."""
    # Arrange
    manager = _manager(_transport())

    # Act
    inventory = manager.read_packages()

    # Assert
    assert [package.name for package in inventory.third_party] == ["com.example.plex", "com.example.solo"]
    assert inventory.system == ("com.android.settings",)
    assert inventory.disabled == ("com.vendor.telemetry",)


def test_skipping_paths_avoids_the_per_package_pm_path_call() -> None:
    """`with_paths=False` is the cheap manifest-only read."""
    # Arrange
    transport = _transport()
    manager = _manager(transport)

    # Act
    manager.read_packages(with_paths=False)

    # Assert
    assert not [command for command in transport.commands() if command.startswith("pm path")]


def test_reading_settings_never_issues_a_mutating_command() -> None:
    """capture_state declares Effect.READ; a mislabelled effect bypasses the
    policy layer silently."""
    # Arrange
    transport = _transport()

    # Act
    _manager(transport).read_settings()

    # Assert
    assert all(call.effect is Effect.READ for call in transport.calls if call.kind == "exec")


# --------------------------------------------------------------- pulling


def test_a_pulled_apk_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    """A zero-byte or truncated read otherwise stores fine and fails years
    later, at a restore."""
    # Arrange
    transport = _transport({"/data/app/~~def==/com.example.solo-uvw==/base.apk": "not an apk"})
    package = InstalledPackage(name="com.example.solo", apks=("/data/app/~~def==/com.example.solo-uvw==/base.apk",))

    # Act / Assert
    with pytest.raises(TransportError):
        _manager(transport).pull_apks(package, tmp_path / "apks")


def test_pulled_apks_are_named_so_the_set_round_trips(tmp_path: Path) -> None:
    """Every base APK on a device is called `base.apk`; the package and the
    index have to be in the filename or the set cannot be reassembled."""
    # Arrange
    manager = _manager(_transport())
    inventory = manager.read_packages()
    plex = next(package for package in inventory.third_party if package.name == "com.example.plex")

    # Act
    written = manager.pull_apks(plex, tmp_path / "apks")

    # Assert
    assert [path.name for path in written] == [
        "com.example.plex-00-base.apk",
        "com.example.plex-01-split_config.en.apk",
        "com.example.plex-02-split_config.arm64_v8a.apk",
    ]


# --------------------------------------------------------------- writing


def test_restoring_settings_skips_what_the_policy_will_not_replay() -> None:
    """`adb_enabled` is the sharpest case: replaying 0 severs the connection
    the restore is running over."""
    # Arrange
    transport = _transport()
    manager = _manager(transport)

    # Act
    applied, skipped = manager.apply_settings({"global": {"adb_enabled": "0", "window_animation_scale": "0.0"}})

    # Assert
    assert applied == ["global.window_animation_scale"]
    assert skipped == ["global.adb_enabled"]
    assert not [command for command in transport.commands() if "adb_enabled" in command]


def test_a_split_package_goes_back_through_install_multiple(tmp_path: Path) -> None:
    """`pm install` takes one APK. A split package installed that way is
    missing resources, and reports success either way."""
    # Arrange
    apks = []
    for index, leaf in enumerate(("base.apk", "split_config.en.apk")):
        path = tmp_path / f"com.example.plex-{index:02d}-{leaf}"
        path.write_bytes(_apk_bytes())
        apks.append(path)
    transport = _transport({f"pm install-multiple -r /data/local/tmp/{apks[0].name} /data/local/tmp/{apks[1].name}": ""})

    # Act
    _manager(transport).install("com.example.plex", apks)

    # Assert
    assert any(command.startswith("pm install-multiple -r ") for command in transport.commands())
    assert not [command for command in transport.commands() if command.startswith("pm install -r")]


def test_an_install_that_reports_nothing_but_left_no_package_is_a_failure(tmp_path: Path) -> None:
    """`pm install` reports failure on stdout and the transport reads no exit
    status, so re-reading the package list is the only honest evidence."""
    # Arrange
    apk = tmp_path / "com.example.ghost-00-base.apk"
    apk.write_bytes(_apk_bytes())
    transport = _transport({f"pm install -r /data/local/tmp/{apk.name}": "", "dumpsys package com.example.ghost": ""})

    # Act / Assert
    with pytest.raises(TransportError):
        _manager(transport).install("com.example.ghost", [apk])


def test_installing_nothing_is_refused_rather_than_reported_as_success(tmp_path: Path) -> None:
    # Act / Assert
    with pytest.raises(TransportError):
        _manager(_transport()).install("com.example.plex", [])


def test_an_apk_is_staged_off_external_storage(tmp_path: Path) -> None:
    """From Android 11 `/sdcard` is a FUSE mount the installer cannot read, so
    an install from there fails after a transfer that plainly succeeded."""
    # Arrange
    apk = tmp_path / "com.example.solo-00-base.apk"
    apk.write_bytes(_apk_bytes())
    transport = _transport({f"pm install -r /data/local/tmp/{apk.name}": ""})

    # Act
    _manager(transport).install("com.example.solo", [apk])

    # Assert
    staged = [call.argument for call in transport.calls if call.kind == "put"]
    assert staged == ["/data/local/tmp/com.example.solo-00-base.apk"]


# --------------------------------------------------------------- the steps


class _UnusedState:
    """Satisfies the `StateManager` protocol and does nothing.

    `capture_state` and `restore_state` read the device itself, so neither
    touches an app's state — but `DeviceStepContext` is typed, and a stub that
    raises is better evidence than a `None` behind an ignore: if a future edit
    reaches for it, the test says so instead of the type checker.
    """

    @property
    def platform(self) -> str:
        """RETURNS: str: Always ``android``."""
        return "android"

    def state_root(self, spec: AppStateSpec) -> str:
        """RAISES: AssertionError: Always — a device-state step has no app profile."""
        raise AssertionError("a device-state step must not resolve an app's state root")

    def snapshot(self, spec: AppStateSpec, destination: Path) -> Path:
        """RAISES: AssertionError: Always."""
        raise AssertionError("a device-state step must not snapshot an app's profile")

    def restore(self, spec: AppStateSpec, archive: Path) -> None:
        """RAISES: AssertionError: Always."""
        raise AssertionError("a device-state step must not restore an app's profile")


class _UnusedApps:
    """Satisfies the `AppManager` protocol and does nothing. See `_UnusedState`."""

    def installed_version(self, identifier: str) -> str:
        """RAISES: AssertionError: Always — package reads go through the device-state manager."""
        raise AssertionError("a device-state step reads packages through its own manager")

    def installed_abi(self, identifier: str) -> str:
        """RAISES: AssertionError: Always."""
        raise AssertionError("a device-state step does not resolve an app's ABI")

    def install(self, package: Path, *, identifier: str = "") -> None:
        """RAISES: AssertionError: Always — a snapshot install needs `pm install-multiple`."""
        raise AssertionError("a device-state step installs through its own manager, which handles splits")

    def launch(self, identifier: str) -> None:
        """RAISES: AssertionError: Always."""
        raise AssertionError("a device-state step does not launch anything")

    def stop(self, identifier: str) -> None:
        """RAISES: AssertionError: Always."""
        raise AssertionError("a device-state step does not stop anything")


def _context(
    tmp_path: Path,
    transport: FakeTransport,
    config: dict[str, Any] | None = None,
    registry: OperationRegistry | None = None,
) -> DeviceStepContext:
    """Build a device-scoped context. Pass a `registry` to read the step's logs
    afterwards -- the handle writes through to it and holds none itself."""
    store = LocalArtifactStore(tmp_path / "artifacts")
    workspace = tmp_path / "work"
    workspace.mkdir(parents=True, exist_ok=True)
    handle = (registry or OperationRegistry()).start("op-1", "shield.capture_state", "shield-1")
    return DeviceStepContext(
        device=Device(id="shield-1", type="shield", address="192.168.1.50", model="SHIELD Android TV", os_version="11"),
        transport=transport,
        # Stubs, not None: these steps read the device rather than an app's
        # profile, so nothing here is called -- but the context is typed and a
        # None would only be hidden behind an ignore.
        state=_UnusedState(),
        apps=_UnusedApps(),
        artifacts=store,
        inventory=DeviceStore(tmp_path / "devices.yml"),
        config=config or {},
        handle=handle,
        workspace=workspace,
    )


def test_capture_publishes_one_archive_carrying_settings_packages_and_apks(tmp_path: Path) -> None:
    # Arrange
    transport = _transport()
    context = _context(tmp_path, transport)

    # Act
    result = devicesteps.capture_state(_manager(transport), context)

    # Assert
    ref = result.artifacts["device_state"]
    assert ref.kind == "device-state"
    local = context.artifacts.get(ref, tmp_path / "out.tar.gz")
    with tarfile.open(local, "r:gz") as archive:
        names = archive.getnames()
    assert "settings.yml" in names
    assert "packages.yml" in names
    assert "apks/com.example.plex-02-split_config.arm64_v8a.apk" in names


def test_the_manifest_records_every_split_file_in_install_order(tmp_path: Path) -> None:
    """The order in the manifest is the order `pm install-multiple` wants."""
    # Arrange
    transport = _transport()
    context = _context(tmp_path, transport)

    # Act
    devicesteps.capture_state(_manager(transport), context)

    # Assert
    local = context.artifacts.get(context.artifacts.latest("device-state"), tmp_path / "out.tar.gz")
    with tarfile.open(local, "r:gz") as archive:
        member = archive.extractfile("packages.yml")
        assert member is not None
        manifest = yaml.safe_load(member.read())
    plex = next(entry for entry in manifest["third_party"] if entry["name"] == "com.example.plex")
    assert plex["split"] is True
    assert plex["files"][0].endswith("-00-base.apk")
    assert len(plex["files"]) == 3


def test_the_archive_never_carries_a_withheld_identifier(tmp_path: Path) -> None:
    """The whole point of `never_capture`: the artifact leaves the device."""
    # Arrange
    transport = _transport()
    context = _context(tmp_path, transport)

    # Act
    devicesteps.capture_state(_manager(transport), context)

    # Assert
    local = context.artifacts.get(context.artifacts.latest("device-state"), tmp_path / "out.tar.gz")
    with tarfile.open(local, "r:gz") as archive:
        member = archive.extractfile("settings.yml")
        assert member is not None
        body = member.read().decode("utf-8")
    assert "deadbeefdeadbeef" not in body
    assert "secure.android_id" in body  # named as withheld, so its absence is visible


def test_capture_without_apks_records_names_and_skips_the_pulls(tmp_path: Path) -> None:
    # Arrange
    transport = _transport()
    context = _context(tmp_path, transport, {"include_apks": False})

    # Act
    result = devicesteps.capture_state(_manager(transport), context)

    # Assert
    assert result.facts["apks"] == 0
    assert result.facts["packages"] == 2
    assert not [call for call in transport.calls if call.kind == "get"]


def test_one_unpullable_package_does_not_cost_the_whole_snapshot(tmp_path: Path) -> None:
    """Settings and the manifest cannot be reconstructed from anywhere else;
    an APK usually can."""
    # Arrange
    transport = _transport({"/data/app/~~def==/com.example.solo-uvw==/base.apk": "not an apk"})
    registry = OperationRegistry()
    context = _context(tmp_path, transport, registry=registry)

    # Act
    result = devicesteps.capture_state(_manager(transport), context)

    # Assert
    assert result.facts["apks"] == 3  # plex's three, not solo's one
    assert any("could not pull" in entry["message"] for entry in _logs(registry))


def test_restore_reinstalls_from_the_snapshot_and_reproduces_the_debloat(tmp_path: Path) -> None:
    # Arrange
    capture_transport = _transport()
    capture_context = _context(tmp_path / "a", capture_transport)
    devicesteps.capture_state(_manager(capture_transport), capture_context)
    ref = capture_context.artifacts.latest("device-state")

    restore_transport = _transport(
        {
            "pm install-multiple -r /data/local/tmp/com.example.plex-00-base.apk "
            "/data/local/tmp/com.example.plex-01-split_config.en.apk "
            "/data/local/tmp/com.example.plex-02-split_config.arm64_v8a.apk": "",
            "pm install -r /data/local/tmp/com.example.solo-00-base.apk": "",
        }
    )
    restore_context = _context(tmp_path / "a", restore_transport, {"state": ref.wire})

    # Act
    result = devicesteps.restore_state(_manager(restore_transport), restore_context)

    # Assert
    assert result.facts["installed"] == 2
    assert any(command.startswith("pm install-multiple") for command in restore_transport.commands())
    assert any("pm disable-user --user 0 com.vendor.telemetry" in command for command in restore_transport.commands())


def test_restore_refuses_an_artifact_of_another_kind(tmp_path: Path) -> None:
    """A Kodi build handed to restore_state would extract and then be replayed
    as if it were settings."""
    # Arrange
    store = LocalArtifactStore(tmp_path / "artifacts")
    stray = tmp_path / "build.tar.gz"
    with tarfile.open(stray, "w:gz"):
        pass
    store.put(stray, ArtifactRef(kind="builds", name="build.tar.gz"))
    context = _context(tmp_path, _transport(), {"state": "builds/build.tar.gz"})

    # Act / Assert
    with pytest.raises(Exception, match="builds"):
        devicesteps.restore_state(_manager(_transport()), context)


def test_restoring_a_snapshot_from_another_device_says_so(tmp_path: Path) -> None:
    """Not refused — rebuilding a replacement box from the dead one's snapshot
    is the likely use — but it is the first thing to suspect afterwards."""
    # Arrange
    capture_transport = _transport()
    capture_context = _context(tmp_path / "a", capture_transport, {"include_apks": False})
    devicesteps.capture_state(_manager(capture_transport), capture_context)

    registry = OperationRegistry()
    other = _context(tmp_path / "a", _transport(), {"packages": False}, registry=registry)
    other.device.id = "shield-2"

    # Act
    devicesteps.restore_state(_manager(other.transport), other)  # type: ignore[arg-type]

    # Assert
    assert any("was taken from shield-1" in entry["message"] for entry in _logs(registry))
