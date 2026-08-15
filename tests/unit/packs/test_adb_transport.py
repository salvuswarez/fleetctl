"""Tests for the ADB transport, against a stubbed adb_shell device.

No hardware. What is verified here is the logic layered *on top* of
`adb_shell`: the digest check, the timeout scaling, error translation, and
that a dropped connection is never reported as an empty success.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from fleetctl.core.effects import Capability, Effect
from fleetctl.core.errors import CommandFailedError, TransportError
from fleetctl.core.transport.base import Transport
from fleetctl.packs.android.keys import AdbKeyStore
from fleetctl.packs.android.transport import AdbTransport


class _StubDevice:
    """Stands in for `adb_shell`'s AdbDeviceTcp."""

    def __init__(self, responses: dict[str, str] | None = None, fail: set[str] | None = None) -> None:
        self.responses = responses or {}
        self.fail = fail or set()
        self.commands: list[str] = []
        self.timeouts: list[float] = []
        self.closed = False
        self.pushed: list[tuple[str, str]] = []
        self.pull_timeouts: list[float] = []
        self.push_timeouts: list[float] = []

    def shell(self, command: str, transport_timeout_s: float = 0, read_timeout_s: float = 0) -> str:
        self.commands.append(command)
        self.timeouts.append(transport_timeout_s)
        if command in self.fail:
            raise OSError("connection reset")
        return self.responses.get(command, "")

    def pull(self, remote: str, buffer: Any, transport_timeout_s: float = 0, read_timeout_s: float = 0) -> None:
        self.pull_timeouts.append(transport_timeout_s)
        if remote in self.fail:
            raise OSError("pull failed")
        buffer.write(self.responses.get(remote, "").encode("utf-8"))

    def push(self, local: str, remote: str, transport_timeout_s: float = 0) -> None:
        self.pushed.append((local, remote))
        self.push_timeouts.append(transport_timeout_s)

    def close(self) -> None:
        self.closed = True


def _transport(tmp_path: Path, device: _StubDevice, *, use_netcat: bool = False) -> AdbTransport:
    transport = AdbTransport("192.168.1.50", AdbKeyStore(tmp_path / "keys"), use_netcat=use_netcat)
    transport._device = device
    return transport


def test_adb_transport_satisfies_the_protocol(tmp_path: Path) -> None:
    assert isinstance(_transport(tmp_path, _StubDevice()), Transport)


def test_it_declares_the_full_capability_set(tmp_path: Path) -> None:
    # Act
    capabilities = _transport(tmp_path, _StubDevice()).capabilities()

    # Assert
    assert Capability.STATE in capabilities
    assert Capability.FILES in capabilities


def test_a_dropped_connection_raises_rather_than_returning_empty(tmp_path: Path) -> None:
    """A dropped connection during a destructive command must never look
    like a command that succeeded quietly."""
    # Arrange
    transport = _transport(tmp_path, _StubDevice(fail={"rm -rf /sdcard/x"}))

    # Act / Assert
    with pytest.raises(CommandFailedError) as caught:
        transport.exec("rm -rf /sdcard/x", effect=Effect.DESTRUCTIVE)
    assert caught.value.target == "192.168.1.50"
    assert caught.value.command == "rm -rf /sdcard/x"


def test_exec_ok_swallows_the_failure(tmp_path: Path) -> None:
    # Arrange
    transport = _transport(tmp_path, _StubDevice(fail={"boom"}))

    # Act / Assert
    assert transport.exec_ok("boom") == ""


def test_an_explicit_timeout_overrides_the_default(tmp_path: Path) -> None:
    """A flat timeout is how the predecessor silently truncated archives."""
    # Arrange
    device = _StubDevice(responses={"tar cf /sdcard/a.tar -C / x": ""})
    transport = _transport(tmp_path, device)

    # Act
    transport.exec("tar cf /sdcard/a.tar -C / x", timeout_s=900.0)

    # Assert
    assert device.timeouts == [900.0]


def test_using_the_transport_before_connecting_is_an_error(tmp_path: Path) -> None:
    # Arrange
    transport = AdbTransport("192.168.1.50", AdbKeyStore(tmp_path / "keys"))

    # Act / Assert
    with pytest.raises(TransportError):
        transport.exec("getprop ro.product.model")


def test_get_writes_the_pulled_bytes(tmp_path: Path) -> None:
    # Arrange
    transport = _transport(tmp_path, _StubDevice(responses={"/sdcard/a.xml": "<a/>"}))
    destination = tmp_path / "out" / "a.xml"

    # Act
    written = transport.get("/sdcard/a.xml", destination)

    # Assert
    assert written == 4
    assert destination.read_text(encoding="utf-8") == "<a/>"


def test_a_failed_pull_raises(tmp_path: Path) -> None:
    # Arrange
    transport = _transport(tmp_path, _StubDevice(fail={"/sdcard/missing"}))

    # Act / Assert
    with pytest.raises(TransportError):
        transport.get("/sdcard/missing", tmp_path / "x")


def test_the_pull_timeout_scales_with_the_file_size(tmp_path: Path) -> None:
    """A flat allowance is how the predecessor produced silently truncated
    archives: a Kodi profile runs to hundreds of MB, and 180s does not cover
    one at any throughput a set-top box actually sustains."""
    # Arrange — 300 MB, so 180s flat + 300s at the 1 MB/s floor.
    device = _StubDevice(responses={"stat -c %s /sdcard/big.tar.gz": "300000000", "/sdcard/big.tar.gz": "payload"})
    transport = _transport(tmp_path, device)

    # Act
    transport.get("/sdcard/big.tar.gz", tmp_path / "big.tar.gz")

    # Assert
    assert device.pull_timeouts == [480.0]


def test_the_pull_timeout_falls_back_when_the_size_is_unknown(tmp_path: Path) -> None:
    """`_remote_size` reports -1 when `stat` gives nothing usable. Scaling on
    that would produce a timeout shorter than the flat floor."""
    # Arrange — no `stat` response, so the size is unknown.
    device = _StubDevice(responses={"/sdcard/a.xml": "<a/>"})
    transport = _transport(tmp_path, device)

    # Act
    transport.get("/sdcard/a.xml", tmp_path / "a.xml")

    # Assert
    assert device.pull_timeouts == [180.0]


def test_put_verifies_the_digest_and_returns_the_size(tmp_path: Path) -> None:
    # Arrange
    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"payload" * 100)
    digest = hashlib.md5(payload.read_bytes()).hexdigest()
    device = _StubDevice(responses={"md5sum /sdcard/build.tar.gz": f"{digest}  /sdcard/build.tar.gz"})
    transport = _transport(tmp_path, device)

    # Act
    written = transport.put(payload, "/sdcard/build.tar.gz")

    # Assert
    assert written == payload.stat().st_size
    assert device.pushed == [(str(payload), "/sdcard/build.tar.gz")]


def test_a_short_write_is_caught_by_the_digest(tmp_path: Path) -> None:
    """`nc` drops its buffered tail if the sender closes too early, so
    transfers arrived 8-24 KB short. The digest is what makes that an error
    rather than a corrupt deploy."""
    # Arrange
    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"payload" * 100)
    device = _StubDevice(
        responses={
            "md5sum /sdcard/build.tar.gz": "0" * 32,
            "stat -c %s /sdcard/build.tar.gz": "512",
        }
    )
    transport = _transport(tmp_path, device)

    # Act / Assert
    with pytest.raises(TransportError) as caught:
        transport.put(payload, "/sdcard/build.tar.gz")
    message = str(caught.value)
    assert "corrupted" in message
    assert "512 bytes" in message


def test_free_bytes_parses_df_output(tmp_path: Path) -> None:
    # Arrange
    device = _StubDevice(responses={"df -k /sdcard": "Filesystem 1K-blocks Used Available\n/dev/fuse 1000000 400000 600000"})
    transport = _transport(tmp_path, device)

    # Act / Assert
    assert transport.free_bytes("/sdcard") == 600000 * 1024


def test_free_bytes_returns_zero_when_df_is_unparseable(tmp_path: Path) -> None:
    # Arrange
    transport = _transport(tmp_path, _StubDevice(responses={"df -k /sdcard": "nonsense"}))

    # Act / Assert
    assert transport.free_bytes("/sdcard") == 0


def test_close_is_idempotent(tmp_path: Path) -> None:
    # Arrange
    device = _StubDevice()
    transport = _transport(tmp_path, device)

    # Act
    transport.close()
    transport.close()

    # Assert
    assert device.closed is True


def test_the_key_store_generates_and_caches_a_signer(tmp_path: Path) -> None:
    # Arrange
    store = AdbKeyStore(tmp_path / "keys")

    # Act
    first = store.signer(target="192.168.1.50")
    second = store.signer(target="192.168.1.50")

    # Assert
    assert first is second
    assert (tmp_path / "keys" / "adbkey").is_file()
    assert (tmp_path / "keys" / "adbkey.pub").is_file()


def test_key_usage_is_audited_so_a_leak_can_be_scoped(tmp_path: Path) -> None:
    """The ADB private key is a standing credential with no expiry; without a
    record there is no way to bound what a leaked key touched."""
    # Arrange
    from fleetctl.core.observability.audit import AuditKind, ChainedAuditWriter, InMemoryAuditSink

    sink = InMemoryAuditSink()
    store = AdbKeyStore(tmp_path / "keys", ChainedAuditWriter(sink))

    # Act
    store.signer(target="192.168.1.50")

    # Assert
    recorded = sink.read_all()
    assert recorded[0].kind is AuditKind.AUTH
    assert recorded[0].target == "192.168.1.50"
    assert recorded[0].detail["fingerprint"] != "unknown"


def test_the_private_key_is_never_written_to_an_audit_record(tmp_path: Path) -> None:
    # Arrange
    from fleetctl.core.observability.audit import ChainedAuditWriter, InMemoryAuditSink

    sink = InMemoryAuditSink()
    store = AdbKeyStore(tmp_path / "keys", ChainedAuditWriter(sink))
    store.signer(target="192.168.1.50")
    private = (tmp_path / "keys" / "adbkey").read_text(encoding="utf-8")

    # Act
    serialized = str([event.to_dict() for event in sink.read_all()])

    # Assert
    assert "PRIVATE KEY" not in serialized
    assert private.strip().splitlines()[1] not in serialized


def test_a_listening_device_that_rejects_the_handshake_is_reported_as_unauthorized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ "Nothing there" and "it refused my key" need different actions, and
    only the second is fixable by the user."""
    # Arrange
    from fleetctl.core.errors import DeviceUnauthorizedError

    transport = AdbTransport("192.168.1.79", AdbKeyStore(tmp_path / "keys"))
    monkeypatch.setattr(transport, "is_online", lambda timeout_s=3.0: True)

    # Act / Assert
    with pytest.raises(DeviceUnauthorizedError):
        transport.connect()


def test_an_address_with_nothing_listening_is_a_plain_transport_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from fleetctl.core.errors import DeviceUnauthorizedError

    transport = AdbTransport("192.168.1.7", AdbKeyStore(tmp_path / "keys"))
    monkeypatch.setattr(transport, "is_online", lambda timeout_s=3.0: False)

    # Act / Assert
    with pytest.raises(TransportError) as caught:
        transport.connect()
    assert not isinstance(caught.value, DeviceUnauthorizedError)
