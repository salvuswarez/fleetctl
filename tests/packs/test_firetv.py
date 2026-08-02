"""Tests for the Fire TV pack: probe, maintain, and its data files."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.core.artifacts.store import LocalArtifactStore
from fleetctl.core.effects import Effect
from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore
from fleetctl.core.observability.audit import ChainedAuditWriter, InMemoryAuditSink, Outcome
from fleetctl.core.operations.registry import OperationRegistry
from fleetctl.core.transport.auditing import AuditingTransport
from fleetctl.core.transport.fake import FakeTransport
from fleetctl.core.workflow.step import DeviceStepContext, StepResult
from fleetctl.packs.android.state import AndroidStateManager
from fleetctl.packs.firetv.pack import MAINTAIN, FireTvPack

FACTS = {
    "getprop ro.product.model": "AFTKA",
    "getprop ro.product.manufacturer": "Amazon",
    "getprop ro.serialno": "SERIAL123",
    "getprop ro.build.version.release": "9",
    "settings get global device_name": "Living Room",
}


def _pack() -> FireTvPack:
    return FireTvPack()


def test_the_pack_claims_an_amazon_device() -> None:
    # Arrange
    transport = FakeTransport(responses=FACTS)

    # Act
    claimed = _pack().probe(transport)

    # Assert
    assert claimed is not None
    assert claimed["type"] == "firetv"
    assert claimed["model"] == "AFTKA"
    assert claimed["name"] == "Living Room"


def test_the_pack_declines_a_non_amazon_device() -> None:
    """A Shield answers every probe but is not ours."""
    # Arrange
    transport = FakeTransport(responses={**FACTS, "getprop ro.product.manufacturer": "NVIDIA", "getprop ro.product.model": "SHIELD Android TV"})

    # Act / Assert
    assert _pack().probe(transport) is None


def test_the_pack_declines_a_host_that_is_not_a_device() -> None:
    """A subnet sweep hits mostly non-devices; that is normal, not an error."""
    # Arrange
    transport = FakeTransport(responses={})

    # Act / Assert
    assert _pack().probe(transport) is None


def test_a_null_device_name_is_treated_as_absent() -> None:
    """`settings get` prints the literal string "null" when unset."""
    # Arrange
    transport = FakeTransport(responses={**FACTS, "settings get global device_name": "null"})

    # Act
    claimed = _pack().probe(transport)

    # Assert
    assert claimed is not None
    assert "name" not in claimed


def test_fire_os_quirks_are_declared_in_data() -> None:
    """These are Amazon's bugs, held as data so a sibling pack cannot
    inherit them untested."""
    # Act
    quirks = _pack().quirks

    # Assert
    assert quirks.split_gzip is True
    assert quirks.push_via_netcat is True
    assert quirks.verify_disable_user is True


def test_the_bloat_list_is_loaded_from_data_and_is_non_trivial() -> None:
    # Act
    packages = _pack().bloat_packages

    # Assert
    assert len(packages) > 50
    assert all(package.startswith("com.amazon.") for package in packages)


def test_the_bloat_list_excludes_alexa_and_the_apps_meant_to_survive() -> None:
    """Alexa backs the remote's microphone button, so disabling it is a
    functionality trade rather than pure bloat."""
    # Act
    packages = _pack().bloat_packages

    # Assert
    assert not [package for package in packages if "alexa" in package and "shopping" not in package]
    assert "org.xbmc.kodi" not in packages


def _run_maintain(transport: FakeTransport, tmp_path: Path, sink: InMemoryAuditSink) -> StepResult:
    audited = AuditingTransport(transport, ChainedAuditWriter(sink))
    device = Device(id="stick-1", type="firetv", address="192.168.1.50", name="Living Room")
    inventory = DeviceStore(tmp_path / "devices.yml")
    inventory.save([device])
    registry = OperationRegistry()
    handle = registry.start("op-1", MAINTAIN.id, device.id)
    context = DeviceStepContext(
        device=device,
        transport=audited,
        state=AndroidStateManager(audited, _pack().quirks),
        artifacts=LocalArtifactStore(tmp_path / "store"),
        inventory=inventory,
        config={"bloat_packages": ["com.amazon.a", "com.amazon.b", "com.amazon.blocked"]},
        handle=handle,
        workspace=tmp_path / "ws",
    )
    return _pack().maintain(context)


def test_maintain_verifies_each_package_against_the_device(tmp_path: Path) -> None:
    """The device reports only two of three as disabled, so the third must be
    reported as blocked rather than assumed successful."""
    # Arrange
    sink = InMemoryAuditSink()
    transport = FakeTransport(
        responses={
            "pm disable-user --user 0 com.amazon.a": "",
            "pm disable-user --user 0 com.amazon.b": "",
            "pm disable-user --user 0 com.amazon.blocked": "",
            "pm list packages -d": "package:com.amazon.a\npackage:com.amazon.b",
            "pm trim-caches 16G": "",
            "settings put global window_animation_scale 0.0": "",
        }
    )

    # Act
    result = _run_maintain(transport, tmp_path, sink)

    # Assert
    assert result.facts["disabled"] == 2
    assert result.facts["blocked"] == ["com.amazon.blocked"]
    assert result.facts["verified"] is True


def test_every_package_disable_is_individually_audited(tmp_path: Path) -> None:
    """The predecessor logged one line for ~90 disables and verified none."""
    # Arrange
    sink = InMemoryAuditSink()
    transport = FakeTransport(responses={"pm list packages -d": ""})

    # Act
    _run_maintain(transport, tmp_path, sink)

    # Assert
    disables = [event for event in sink.read_all() if event.action.startswith("pm disable-user")]
    assert len(disables) == 3
    assert all(event.effect is Effect.DESTRUCTIVE for event in disables)


def test_reading_the_disabled_list_is_not_written_to_the_audit_trail(tmp_path: Path) -> None:
    # Arrange
    sink = InMemoryAuditSink()
    transport = FakeTransport(responses={"pm list packages -d": ""})

    # Act
    _run_maintain(transport, tmp_path, sink)

    # Assert
    assert not [event for event in sink.read_all() if event.action == "pm list packages -d"]


def test_maintain_applies_settings_from_data(tmp_path: Path) -> None:
    # Arrange
    sink = InMemoryAuditSink()
    transport = FakeTransport(responses={"pm list packages -d": ""})

    # Act
    _run_maintain(transport, tmp_path, sink)

    # Assert
    issued = transport.commands()
    assert "settings put global window_animation_scale 0.0" in issued
    assert "settings put secure limit_ad_tracking 1" in issued


def test_a_silently_blocked_disable_still_reaches_the_audit_trail(tmp_path: Path) -> None:
    # Arrange
    sink = InMemoryAuditSink()
    transport = FakeTransport(
        responses={"pm list packages -d": ""},
        failures={"pm disable-user --user 0 com.amazon.blocked": "SecurityException"},
    )

    # Act
    _run_maintain(transport, tmp_path, sink)

    # Assert
    outcomes = {event.action: event.outcome for event in sink.read_all()}
    assert outcomes["pm disable-user --user 0 com.amazon.blocked"] is Outcome.SKIPPED


def test_pack_data_can_be_overridden_without_touching_the_shipped_files() -> None:
    # Arrange
    pack = FireTvPack(data={"bloat": {"custom": ["com.example.one"]}, "quirks": {"split_gzip": False}})

    # Act / Assert
    assert pack.bloat_packages == ("com.example.one",)
    assert pack.quirks.split_gzip is False
