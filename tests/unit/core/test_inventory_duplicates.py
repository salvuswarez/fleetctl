"""Collapsing two records for one physical device.

An inventory that has grown a second record for hardware it already knows
cannot be repaired by scanning: every sweep matched the first record, updated
it, and wrote both back. These tests pin the self-healing pass that runs
before discovery is merged, and the identity evidence it demands first.
"""

from __future__ import annotations

from pathlib import Path

from fleetctl.core.inventory.device import Device, DeviceStatus
from fleetctl.core.inventory.reconcile import reconcile
from fleetctl.core.inventory.store import DeviceStore


def _device(**overrides: object) -> Device:
    base: dict[str, object] = {"id": "den-shield", "type": "shield", "address": "192.168.1.50", "mac": "aa:bb:cc:dd:ee:ff"}
    base.update(overrides)
    return Device.model_validate(base)


def test_two_identical_records_collapse_without_any_discovery() -> None:
    """The state found live: the same block twice, and no scan could clear it."""
    # Arrange
    existing = [_device(), _device()]

    # Act
    result = reconcile(existing, [])

    # Assert
    assert [device.id for device in result.devices] == ["den-shield"]
    assert result.collapsed == 1
    assert (result.added, result.updated) == (0, 0)


def test_collapsing_keeps_the_first_record_and_its_id() -> None:
    """Operations, tags and the panel all reference the id already in use."""
    # Arrange
    existing = [_device(id="den-shield"), _device(id="den-shield-2")]

    # Act
    result = reconcile(existing, [])

    # Assert
    assert [device.id for device in result.devices] == ["den-shield"]


def test_collapsing_unions_tags_from_both_records() -> None:
    """A tag on the duplicate is hand-maintained; dropping it loses work."""
    # Arrange
    existing = [_device(tags=["kodi"]), _device(id="den-shield-2", tags=["gold", "kodi"])]

    # Act
    result = reconcile(existing, [])

    # Assert
    assert result.devices[0].tags == ["kodi", "gold"]


def test_collapsing_fills_fields_the_survivor_is_missing() -> None:
    """Each record may have been probed at a different time."""
    # Arrange
    existing = [_device(serial="", name="Den Shield"), _device(id="den-shield-2", serial="SER123", name="")]

    # Act
    result = reconcile(existing, [])

    # Assert
    assert result.devices[0].serial == "SER123"
    assert result.devices[0].name == "Den Shield"


def test_collapsing_prefers_the_survivors_app_vars() -> None:
    """Two values for one app key: the record everything else references wins."""
    # Arrange
    keeper = _device(vars={"kodi": {"display": {"resolution_index": 18}}})
    duplicate = _device(id="den-shield-2", vars={"kodi": {"display": {"resolution_index": 3}}, "jellyfin": {"port": 8096}})

    # Act
    result = reconcile([keeper, duplicate], [])

    # Assert
    assert result.devices[0].app_vars("kodi")["display"]["resolution_index"] == 18
    assert result.devices[0].app_vars("jellyfin") == {"port": 8096}


def test_a_scan_updates_the_survivor_rather_than_one_of_two_records() -> None:
    """The bug: discovery matched the first record and left the rest behind."""
    # Arrange
    existing = [_device(address="192.168.1.50"), _device(id="den-shield-2", address="192.168.1.50")]
    discovered = [_device(id="ignored", address="192.168.1.58")]

    # Act
    result = reconcile(existing, discovered)

    # Assert
    assert len(result.devices) == 1
    assert result.devices[0].address == "192.168.1.58"
    assert (result.added, result.updated, result.collapsed) == (0, 1, 1)


def test_devices_with_the_same_id_collapse_even_without_identity_evidence() -> None:
    """An id is unique within the inventory by definition."""
    # Arrange
    existing = [Device(id="pc-den", tags=["kodi"]), Device(id="pc-den", type="linux_host")]

    # Act
    result = reconcile(existing, [])

    # Assert
    assert len(result.devices) == 1
    assert result.devices[0].type == "linux_host"
    assert result.devices[0].tags == ["kodi"]


def test_distinct_devices_are_never_collapsed() -> None:
    # Arrange
    existing = [_device(id="den-shield", mac="aa:bb:cc:dd:ee:ff"), _device(id="stick-1", mac="aa:bb:cc:dd:ee:01", address="192.168.1.60")]

    # Act
    result = reconcile(existing, [])

    # Assert
    assert [device.id for device in result.devices] == ["den-shield", "stick-1"]
    assert result.collapsed == 0


def test_records_with_no_identity_evidence_are_left_alone() -> None:
    """No MAC, no serial, no address is not a claim of sameness — it is an
    absence of evidence, and collapsing on it would merge unrelated hardware."""
    # Arrange
    existing = [Device(id="placeholder-a"), Device(id="placeholder-b")]

    # Act
    result = reconcile(existing, [])

    # Assert
    assert len(result.devices) == 2
    assert result.collapsed == 0


def test_a_record_whose_identity_fills_in_later_still_collapses() -> None:
    """How a duplicate is born: a record known only by address, and a second
    known by MAC. Merging discovery gives the survivor both, and the pass runs
    again so the two do not persist for another sweep."""
    # Arrange
    existing = [_device(id="den-shield", mac="", serial="", address="192.168.1.50"), _device(id="den-shield-2", mac="aa:bb:cc:dd:ee:ff", address="")]
    discovered = [_device(id="ignored", mac="aa:bb:cc:dd:ee:ff", address="192.168.1.50")]

    # Act
    result = reconcile(existing, discovered)

    # Assert
    assert [device.id for device in result.devices] == ["den-shield"]
    assert result.collapsed == 1


def test_collapsing_survives_the_store(tmp_path: Path) -> None:
    """The live file must actually shrink, not just the in-memory list."""
    # Arrange
    path = tmp_path / "devices.yml"
    block = "  - id: den-shield\n    type: shield\n    address: 192.168.1.50\n    mac: aa:bb:cc:dd:ee:ff\n"
    path.write_text(f"devices:\n{block}{block}", encoding="utf-8")
    store = DeviceStore(path)

    # Act
    store.reconcile([Device(id="ignored", type="shield", address="192.168.1.50", mac="aa:bb:cc:dd:ee:ff", status=DeviceStatus.OK)])

    # Assert
    assert [device.id for device in DeviceStore(path).list()] == ["den-shield"]
