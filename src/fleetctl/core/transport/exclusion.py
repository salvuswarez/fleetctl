"""Per-device mutual exclusion, so one caller cannot interrupt another's transfer."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import TransportError
from fleetctl.core.transport.base import Transport

LOGGER = logging.getLogger(__name__)


class DeviceBusyError(TransportError):
    """A transport to this device is already open and the caller would not wait.

    Deliberately a `TransportError`: every existing caller already treats that
    as "no transport to this device right now" and degrades rather than
    failing, so a busy device skips a probe instead of ending a sweep.

    **PARAMETERS:**
        `target` (str): Address or id of the device already in use.  <br>
    """

    def __init__(self, target: str) -> None:
        super().__init__(f"{target} is already in use by another operation", target=target)


class DeviceLocks:
    """Hands out one lock per device, created on first use.

    Held for a transport's whole lifetime rather than per call. The damage
    being prevented is a *second connection opening mid-transfer*: a fleet's
    power poll opened its own ADB connection every 30s while a capture was
    streaming a multi-hundred-MB archive off the same box, and the device's
    `adbd` reset the transfer. A per-call lock would still allow that, because
    the poll would simply land between two of the transfer's calls.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def for_target(self, target: str) -> threading.Lock:
        """RETURNS: threading.Lock: The lock guarding `target`, created on first use."""
        with self._guard:
            return self._locks.setdefault(target, threading.Lock())


class ExclusiveTransport:
    """Wraps a `Transport`, releasing a held device lock when it closes.

    Every method delegates untouched; the only behaviour this adds is at
    `close`, which is why the lock must be acquired *before* the wrapped
    transport is built — opening the connection is itself the contended act.

    **PARAMETERS:**
        `inner` (Transport): The transport actually doing the work.  <br>
        `release` (Callable[[], None]): Releases the device lock. Called once, on the first `close`.  <br>
    """

    def __init__(self, inner: Transport, release: Callable[[], None]) -> None:
        self._inner = inner
        self._release = release
        self._released = False

    @property
    def target(self) -> str:
        """RETURNS: str: Address or id of the wrapped transport's device."""
        return self._inner.target

    def capabilities(self) -> frozenset[Capability]:
        """RETURNS: frozenset[Capability]: Whatever the wrapped transport supports."""
        return self._inner.capabilities()

    def close(self) -> None:
        """Close the wrapped transport and release the device lock. Idempotent.

        The lock is released even if the inner close raises. Leaking it would
        strand the device: every later caller would see it as permanently busy,
        with nothing holding it.
        """
        try:
            self._inner.close()
        finally:
            if not self._released:
                self._released = True
                self._release()

    def is_online(self, timeout_s: float = 3.0) -> bool:
        """RETURNS: bool: Whether the device responded."""
        return self._inner.is_online(timeout_s=timeout_s)

    def exec(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """RETURNS: str: Stdout from the wrapped transport."""
        return self._inner.exec(command, effect=effect, timeout_s=timeout_s)

    def exec_ok(self, command: str, *, effect: Effect = Effect.MUTATING, timeout_s: float | None = None) -> str:
        """RETURNS: str: Stdout, or `""` if the command failed."""
        return self._inner.exec_ok(command, effect=effect, timeout_s=timeout_s)

    def put(self, local_path: Path, remote_path: str, *, effect: Effect = Effect.MUTATING) -> int:
        """RETURNS: int: Bytes written by the wrapped transport."""
        return self._inner.put(local_path, remote_path, effect=effect)

    def get(self, remote_path: str, local_path: Path) -> int:
        """RETURNS: int: Bytes read by the wrapped transport."""
        return self._inner.get(remote_path, local_path)

    def free_bytes(self, remote_path: str) -> int:
        """RETURNS: int: Free bytes reported by the wrapped transport."""
        return self._inner.free_bytes(remote_path)
