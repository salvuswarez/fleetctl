"""Forgetting a device: explicit, never automatic.

`reconcile` keeps a device a scan did not see, because absence from one sweep
is not evidence a device is gone. Removal is therefore a decision someone
makes, and these tests pin that boundary.
"""

from __future__ import annotations

from pathlib import Path

from fleetctl.core.inventory.device import Device
from fleetctl.core.inventory.store import DeviceStore

DEVICES = (
    "devices:\n"
    "  - id: den-shield\n    type: shield\n    address: 192.168.1.50\n    tags: [kodi]\n"
    "  - id: stick-1\n    type: firetv\n    address: 192.168.1.60\n    tags: [kodi, gold]\n"
)


def _store(tmp_path: Path) -> DeviceStore:
    path = tmp_path / "devices.yml"
    path.write_text(DEVICES, encoding="utf-8")
    return DeviceStore(path)


def test_forgetting_removes_only_the_named_device(tmp_path: Path) -> None:
    # Arrange
    store = _store(tmp_path)

    # Act
    removed = store.forget("den-shield")

    # Assert
    assert removed is True
    assert [device.id for device in store.list()] == ["stick-1"]


def test_forgetting_an_unknown_device_is_not_an_error(tmp_path: Path) -> None:
    """The caller wanted it gone and it is."""
    # Arrange
    store = _store(tmp_path)

    # Act / Assert
    assert store.forget("never-existed") is False
    assert len(store.list()) == 2


def test_a_forgotten_device_returns_on_the_next_scan(tmp_path: Path) -> None:
    """The identity survives in the hardware; the annotations do not."""
    # Arrange
    store = _store(tmp_path)
    store.forget("den-shield")

    # Act
    store.reconcile([Device(id="den-shield", type="shield", address="192.168.1.50")])

    # Assert
    found = store.get("den-shield")
    assert found is not None
    assert found.tags == [], "a rediscovered device comes back clean, not with its old tags"


def test_a_scan_that_misses_a_device_still_keeps_it(tmp_path: Path) -> None:
    """The behaviour `forget` exists to complement: only an explicit decision
    removes a device, never a failed sweep."""
    # Arrange
    store = _store(tmp_path)

    # Act: a scan that found only the other device.
    store.reconcile([Device(id="stick-1", type="firetv", address="192.168.1.60")])

    # Assert
    assert store.get("den-shield") is not None


def test_forgetting_persists_across_readers(tmp_path: Path) -> None:
    """The panel and the CLI read the same file from different processes."""
    # Arrange
    store = _store(tmp_path)
    store.forget("den-shield")

    # Act
    reopened = DeviceStore(tmp_path / "devices.yml")

    # Assert
    assert reopened.get("den-shield") is None
