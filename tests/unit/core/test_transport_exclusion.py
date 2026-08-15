"""Per-device exclusion: one transport per device, released on close.

The failure this prevents is not hypothetical. A power poll opened its own ADB
connection every 30s while a capture streamed a multi-hundred-MB archive off
the same box, and the device reset the transfer — twice, reproducibly.
"""

from __future__ import annotations

import pytest

from fleetctl.core.errors import TransportError
from fleetctl.core.transport.exclusion import DeviceBusyError, DeviceLocks, ExclusiveTransport
from fleetctl.core.transport.fake import FakeTransport


def test_one_lock_per_target() -> None:
    # Arrange
    locks = DeviceLocks()

    # Act / Assert
    assert locks.for_target("192.168.1.50") is locks.for_target("192.168.1.50")
    assert locks.for_target("192.168.1.50") is not locks.for_target("192.168.1.51")


def test_closing_releases_the_lock() -> None:
    # Arrange
    locks = DeviceLocks()
    lock = locks.for_target("192.168.1.50")
    lock.acquire()
    transport = ExclusiveTransport(FakeTransport(target="192.168.1.50"), lock.release)

    # Act
    transport.close()

    # Assert — a later caller can take it.
    assert lock.acquire(blocking=False)


def test_the_lock_is_released_even_when_the_inner_close_fails() -> None:
    """A leaked lock strands the device: every later caller sees it as busy
    forever, with nothing actually holding it."""

    # Arrange
    class _BadClose(FakeTransport):
        def close(self) -> None:
            raise TransportError("channel already gone", target="192.168.1.50")

    locks = DeviceLocks()
    lock = locks.for_target("192.168.1.50")
    lock.acquire()
    transport = ExclusiveTransport(_BadClose(target="192.168.1.50"), lock.release)

    # Act
    with pytest.raises(TransportError):
        transport.close()

    # Assert
    assert lock.acquire(blocking=False)


def test_closing_twice_releases_once() -> None:
    """A second release would hand the device to two callers at once."""
    # Arrange
    locks = DeviceLocks()
    lock = locks.for_target("192.168.1.50")
    lock.acquire()
    transport = ExclusiveTransport(FakeTransport(target="192.168.1.50"), lock.release)

    # Act
    transport.close()
    transport.close()

    # Assert — still exactly one holder's worth of lock.
    assert lock.acquire(blocking=False)
    assert not lock.acquire(blocking=False)


def test_a_busy_device_reports_as_a_transport_error() -> None:
    """Deliberately a `TransportError` subclass: `claim_host` and the power
    read already degrade on that, so a busy device skips rather than raising
    an exception type no caller expects."""
    # Act / Assert
    assert isinstance(DeviceBusyError("192.168.1.50"), TransportError)
    assert DeviceBusyError("192.168.1.50").target == "192.168.1.50"


def test_calls_pass_through_untouched() -> None:
    # Arrange
    locks = DeviceLocks()
    lock = locks.for_target("192.168.1.50")
    lock.acquire()
    inner = FakeTransport(target="192.168.1.50", responses={"echo hi": "hi"})
    transport = ExclusiveTransport(inner, lock.release)

    # Act / Assert
    assert transport.target == "192.168.1.50"
    assert transport.exec("echo hi") == "hi"
    assert transport.capabilities() == inner.capabilities()
