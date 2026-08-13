"""What the ADB key store writes to the audit trail, and how often.

The audit trail answers "which key touched which device". A polled read
reconnects every interval, and recording each connection turned that record
into 8,214 events in one day against 5 real ones — observed on the live HA
instance once power sensors started polling.
"""

from __future__ import annotations

from pathlib import Path

from fleetctl.core.observability.audit import ChainedAuditWriter, InMemoryAuditSink
from fleetctl.packs.android.keys import AdbKeyStore


def _store(tmp_path: Path) -> tuple[AdbKeyStore, InMemoryAuditSink]:
    sink = InMemoryAuditSink()
    return AdbKeyStore(tmp_path / "keys", ChainedAuditWriter(sink)), sink


def test_the_first_use_against_a_device_is_recorded(tmp_path: Path) -> None:
    # Arrange
    store, sink = _store(tmp_path)

    # Act
    store.signer(target="192.168.1.50")

    # Assert
    assert [event.action for event in sink.read_all()] == ["adb.key.use"]
    assert sink.read_all()[0].target == "192.168.1.50"


def test_repeated_use_against_the_same_device_is_recorded_once(tmp_path: Path) -> None:
    """The load-bearing assertion. A 30-second poll reconnects 2,880 times a
    day per device, and the answer never changes."""
    # Arrange
    store, sink = _store(tmp_path)

    # Act
    for _ in range(50):
        store.signer(target="192.168.1.50")

    # Assert
    assert len(sink.read_all()) == 1


def test_each_device_is_recorded_separately(tmp_path: Path) -> None:
    """Deduplication must not lose the signal: which key reached which device
    is the thing the record exists to answer."""
    # Arrange
    store, sink = _store(tmp_path)

    # Act
    for address in ("192.168.1.50", "192.168.1.60", "192.168.1.50"):
        store.signer(target=address)

    # Assert
    assert sorted(event.target for event in sink.read_all()) == ["192.168.1.50", "192.168.1.60"]


def test_the_fingerprint_is_read_once_not_per_connection(tmp_path: Path) -> None:
    """It hashes a file on disk. Per-connection it is I/O for a constant."""
    # Arrange
    store, _ = _store(tmp_path)
    store.signer(target="192.168.1.50")
    first = store.fingerprint

    # Act: remove the file the fingerprint is derived from.
    (tmp_path / "keys" / "adbkey.pub").unlink()

    # Assert: the cached answer survives, proving it was not re-read.
    assert store.fingerprint == first
    assert first != "unknown"


def test_a_store_with_no_audit_sink_records_nothing(tmp_path: Path) -> None:
    """Acceptable only in tests, and must not raise."""
    # Arrange
    store = AdbKeyStore(tmp_path / "keys")

    # Act / Assert
    store.signer(target="192.168.1.50")
