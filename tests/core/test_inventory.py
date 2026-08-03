"""Tests for the device model, reconciliation, and the store."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.reconcile import reconcile
from fleetctl.core.inventory.store import DeviceStore


def _device(**overrides: object) -> Device:
    base: dict[str, object] = {"id": "stick-1", "address": "192.168.1.50", "mac": "aa:bb:cc:dd:ee:ff"}
    base.update(overrides)
    return Device.model_validate(base)


def test_app_vars_are_namespaced_and_absent_by_default() -> None:
    """`display` and `settings` were core fields in the predecessor, which
    gave a PC a field meaning "Kodi videoscreen.resolution"."""
    # Arrange
    device = _device(vars={"kodi": {"display": {"resolution_index": 18}}})

    # Act / Assert
    assert device.app_vars("kodi")["display"]["resolution_index"] == 18
    assert device.app_vars("jellyfin") == {}


def test_a_device_moving_address_is_matched_by_mac_not_duplicated() -> None:
    """Addresses drift with DHCP leases."""
    # Arrange
    existing = [_device(address="192.168.1.50")]
    discovered = [_device(id="ignored", address="192.168.1.77")]

    # Act
    result = reconcile(existing, discovered)

    # Assert
    assert len(result.devices) == 1
    assert result.devices[0].address == "192.168.1.77"
    assert (result.added, result.updated) == (0, 1)


def test_matching_falls_back_to_serial_then_address() -> None:
    # Arrange
    existing = [_device(mac="", serial="SER123", address="192.168.1.50")]
    discovered = [_device(id="x", mac="", serial="SER123", address="192.168.1.90")]

    # Act
    result = reconcile(existing, discovered)

    # Assert
    assert len(result.devices) == 1
    assert result.devices[0].address == "192.168.1.90"


def test_a_partial_probe_does_not_blank_stored_fields() -> None:
    """A sleeping or half-probed device keeps what was already known."""
    # Arrange
    existing = [_device(name="Living Room", model="AFTKA", os_version="9")]
    discovered = [_device(id="x", name="", model="", os_version="")]

    # Act
    result = reconcile(existing, discovered)

    # Assert
    assert result.devices[0].name == "Living Room"
    assert result.devices[0].model == "AFTKA"


def test_discovery_never_touches_tags_or_app_vars() -> None:
    """Both are hand-maintained or owned by an app pack."""
    # Arrange
    existing = [_device(tags=["gold", "kodi"], vars={"kodi": {"display": {"resolution_index": 18}}})]
    discovered = [_device(id="x", tags=[], vars={})]

    # Act
    result = reconcile(existing, discovered)

    # Assert
    assert result.devices[0].tags == ["gold", "kodi"]
    assert result.devices[0].app_vars("kodi") != {}


def test_an_unseen_device_is_retained() -> None:
    """Absence from one scan is not evidence a device is gone."""
    # Arrange
    existing = [_device(id="stick-1"), _device(id="stick-2", mac="aa:bb:cc:00:11:22", address="192.168.1.60")]

    # Act
    result = reconcile(existing, [_device(id="x")])

    # Assert
    assert {device.id for device in result.devices} == {"stick-1", "stick-2"}


def test_a_new_device_is_added() -> None:
    # Act
    result = reconcile([], [_device()])

    # Assert
    assert (result.added, result.updated) == (1, 0)


@pytest.mark.parametrize("filename", ["devices.yml", "devices.json"])
def test_store_round_trips_in_both_formats(tmp_path: Path, filename: str) -> None:
    # Arrange
    store = DeviceStore(tmp_path / filename)

    # Act
    store.save([_device(tags=["gold"], vars={"kodi": {"a": 1}})])
    loaded = store.list()

    # Assert
    assert len(loaded) == 1
    assert loaded[0].tags == ["gold"]
    assert loaded[0].app_vars("kodi") == {"a": 1}


def test_reading_a_missing_inventory_is_empty(tmp_path: Path) -> None:
    assert DeviceStore(tmp_path / "absent.yml").list() == []


def test_select_filters_by_tag_and_type(tmp_path: Path) -> None:
    # Arrange
    store = DeviceStore(tmp_path / "devices.yml")
    store.save(
        [
            _device(id="a", type="firetv", tags=["kodi", "gold"]),
            _device(id="b", type="firetv", tags=["kodi"], mac="aa:bb:cc:00:00:02"),
            _device(id="c", type="shield", tags=["kodi"], mac="aa:bb:cc:00:00:03"),
        ]
    )

    # Act / Assert
    assert [device.id for device in store.select(tags=["kodi"])] == ["a", "b", "c"]
    assert [device.id for device in store.select(tags=["kodi"], device_type="firetv")] == ["a", "b"]
    assert [device.id for device in store.select(tags=["gold"])] == ["a"]


def test_lookup_by_id_and_address(tmp_path: Path) -> None:
    # Arrange
    store = DeviceStore(tmp_path / "devices.yml")
    store.save([_device()])

    # Act / Assert
    assert store.get("stick-1") is not None
    assert store.get_by_address("192.168.1.50") is not None
    assert store.get("nope") is None


def test_the_write_is_atomic_leaving_no_temp_files(tmp_path: Path) -> None:
    # Arrange
    store = DeviceStore(tmp_path / "devices.yml")

    # Act
    store.save([_device()])

    # Assert
    assert [path.name for path in tmp_path.iterdir()] == ["devices.yml"]


def test_set_tag_adds_to_the_named_device_only(tmp_path: Path) -> None:
    # Arrange
    store = DeviceStore(tmp_path / "devices.yml")
    store.save([_device(id="a", tags=["kodi"]), _device(id="b", address="192.168.1.51", tags=["kodi"])])

    # Act
    updated = store.set_tag("a", "gold")

    # Assert
    assert updated.tags == ["kodi", "gold"]
    other = store.get("b")
    assert other is not None and other.tags == ["kodi"]


def test_set_tag_is_idempotent(tmp_path: Path) -> None:
    # Arrange
    store = DeviceStore(tmp_path / "devices.yml")
    store.save([_device(tags=["gold"])])

    # Act
    updated = store.set_tag("stick-1", "gold")

    # Assert
    assert updated.tags == ["gold"]


def test_set_tag_exclusive_moves_the_tag_rather_than_duplicating_it(tmp_path: Path) -> None:
    """Which device is "gold" is picked at any time, not fixed in config --
    exactly one device should carry the tag after a retarget."""
    # Arrange
    store = DeviceStore(tmp_path / "devices.yml")
    store.save([_device(id="a", tags=["kodi", "gold"]), _device(id="b", address="192.168.1.51", tags=["kodi"])])

    # Act
    store.set_tag("b", "gold", exclusive=True)

    # Assert
    a, b = store.get("a"), store.get("b")
    assert a is not None and a.tags == ["kodi"]
    assert b is not None and b.tags == ["kodi", "gold"]


def test_set_tag_on_an_unknown_device_is_refused(tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.errors import FleetError

    store = DeviceStore(tmp_path / "devices.yml")
    store.save([_device()])

    # Act / Assert
    with pytest.raises(FleetError):
        store.set_tag("nope", "gold")
