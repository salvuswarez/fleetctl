"""Tests for the ADB transport, against a stubbed adb_shell device.

No hardware. What is verified here is the logic layered *on top* of
`adb_shell`: the digest check, the timeout scaling, error translation, and
that a dropped connection is never reported as an empty success.
"""

from __future__ import annotations

import hashlib
import os
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from adb_shell.adb_device import _open_bytesio

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
        self.push_read_timeouts: list[float] = []

    def shell(self, command: str, transport_timeout_s: float = 0, read_timeout_s: float = 0) -> str:
        self.commands.append(command)
        self.timeouts.append(transport_timeout_s)
        if command in self.fail:
            raise OSError("connection reset")
        return self.responses.get(command, "")

    def pull(self, remote: str, local_path: Any, transport_timeout_s: float = 0, read_timeout_s: float = 0) -> None:
        """Mirror `adb_shell.AdbDevice.pull`, including what it refuses.

        The real method chooses its opener with `_open_bytesio if
        isinstance(local_path, BytesIO) else open`, so it takes a BytesIO or a
        path and **opens the destination itself**. An already-open handle goes
        to `open()` and raises TypeError before a byte moves. A stub that
        accepted anything with `.write()` let exactly that ship.
        """
        self.pull_timeouts.append(transport_timeout_s)
        if not isinstance(local_path, (str, bytes, os.PathLike, BytesIO)):
            raise TypeError(f"expected str, bytes or os.PathLike object, not {type(local_path).__name__}")
        # Annotated loose because the real line is exactly this shape: the
        # opener differs per branch and only one of them takes a path.
        opener: Any = _open_bytesio if isinstance(local_path, BytesIO) else open
        with opener(local_path, "wb") as stream:
            if remote in self.fail:
                raise OSError("pull failed")
            stream.write(self.responses.get(remote, "").encode("utf-8"))

    def push(self, local: str, remote: str, transport_timeout_s: float = 0, read_timeout_s: float = 10.0) -> None:
        """Mirror `adb_shell.AdbDevice.push`, including its 10s default read timeout.

        `read_timeout_s` is the wait for the device's `OKAY` and does not
        inherit from `transport_timeout_s`. Defaulting it here rather than
        accepting anything is what makes a caller that forgets it visible.
        """
        self.pushed.append((local, remote))
        self.push_timeouts.append(transport_timeout_s)
        self.push_read_timeouts.append(read_timeout_s)

    def close(self) -> None:
        self.closed = True


def _transport(tmp_path: Path, device: _StubDevice, *, use_netcat: bool = False) -> AdbTransport:
    transport = AdbTransport("192.168.1.50", AdbKeyStore(tmp_path / "keys"), use_netcat=use_netcat)
    transport._device = device
    return transport


def _reconnects_to(monkeypatch: pytest.MonkeyPatch, transport: AdbTransport, device: _StubDevice) -> list[int]:
    """Make `connect` install `device` instead of dialling out. RETURNS: list[int]: One entry per reconnect."""
    calls: list[int] = []

    def _connect() -> None:
        calls.append(1)
        transport._device = device

    monkeypatch.setattr(transport, "connect", _connect)
    return calls


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


def test_a_failed_pull_keeps_what_landed_and_says_how_much(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reset mid-transfer is the failure that matters here, and buffering in
    memory discarded every byte of evidence with it. The partial file and the
    byte count in the message are the only way to tell a consistent cutoff from
    a flaky one."""

    # Arrange — writes some bytes, then the connection drops.
    class _DiesMidPull(_StubDevice):
        def pull(self, remote: str, local_path: Any, transport_timeout_s: float = 0, read_timeout_s: float = 0) -> None:
            # Raised inside the `with`, as a real reset would be: the file is
            # closed on the way out and keeps whatever had been written.
            with open(local_path, "wb") as stream:
                stream.write(b"partial payload")
                raise ConnectionResetError(104, "Connection reset by peer")

    destination = tmp_path / "out" / "big.tar.gz"
    device = _DiesMidPull()
    transport = _transport(tmp_path, device)
    reconnects = _reconnects_to(monkeypatch, transport, device)

    # Act
    with pytest.raises(TransportError, match="after 15 bytes") as caught:
        transport.get("/sdcard/big.tar.gz", destination)

    # Assert
    assert caught.value.target == "192.168.1.50"
    assert destination.read_bytes() == b"partial payload"
    assert len(reconnects) == 1


def test_get_hands_pull_a_path_not_an_open_handle(tmp_path: Path) -> None:
    """`adb_shell.pull` opens the destination itself, so an already-open handle
    reaches `open()` and dies with TypeError before a byte moves. That shipped
    once: the stub accepted anything with `.write()` while the real library
    type-checks, so the suite stayed green and every capture failed."""
    # Arrange
    seen: list[object] = []

    class _RecordsDestination(_StubDevice):
        def pull(self, remote: str, local_path: Any, transport_timeout_s: float = 0, read_timeout_s: float = 0) -> None:
            seen.append(local_path)
            super().pull(remote, local_path, transport_timeout_s, read_timeout_s)

    transport = _transport(tmp_path, _RecordsDestination(responses={"/sdcard/a.xml": "<a/>"}))

    # Act
    transport.get("/sdcard/a.xml", tmp_path / "a.xml")

    # Assert
    assert seen and isinstance(seen[0], (str, bytes, os.PathLike))


def test_the_pull_timeout_scales_with_the_file_size(tmp_path: Path) -> None:
    """A flat allowance is how the predecessor produced silently truncated
    archives: a Kodi profile runs to hundreds of MB, and 180s does not cover
    one at any throughput a set-top box actually sustains."""
    # Arrange — 300 MB, so 180s flat + 300s at the 1 MB/s floor.
    device = _StubDevice(responses={"stat -c %s /sdcard/big.tar.gz": "300000000", "/sdcard/big.tar.gz": "payload"})
    transport = _transport(tmp_path, device)

    # Act — the stub delivers 7 bytes of the 300 MB it reports, which the
    # size check rightly rejects; only the timeout is under test here.
    with pytest.raises(TransportError, match="landed 7 of 300000000"):
        transport.get("/sdcard/big.tar.gz", tmp_path / "big.tar.gz")

    # Assert
    assert device.pull_timeouts == [480.0]


def test_a_native_push_scales_both_timeouts(tmp_path: Path) -> None:
    """`read_timeout_s` is the wait for the device's `OKAY` and defaults to 10s
    in the library. Passing only `transport_timeout_s` still gives a device ten
    seconds to acknowledge a multi-hundred-MB write, which failed a Shield
    deploy while native push itself was working fine."""
    # Arrange — 40 MB, so 180s flat + 40s at the 1 MB/s floor.
    device = _StubDevice(responses={"md5sum /sdcard/build.tar.gz": "0" * 32})
    transport = _transport(tmp_path, device, use_netcat=False)
    payload = tmp_path / "build.tar.gz"
    payload.write_bytes(b"x" * 40_000_000)

    # Act — the digest will not match; only the timeouts are under test.
    with pytest.raises(TransportError):
        transport.put(payload, "/sdcard/build.tar.gz")

    # Assert
    assert device.push_timeouts == [220.0]
    assert device.push_read_timeouts == [220.0]


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


class _HandshakeFails:
    """Stands in for `adb_shell`'s AdbDeviceTcp, failing `connect` with a scripted error."""

    error: BaseException = RuntimeError("unset")

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def connect(self, **kwargs: object) -> None:
        raise self.error


def _failing_handshake(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    import adb_shell.adb_device

    monkeypatch.setattr(_HandshakeFails, "error", error)
    monkeypatch.setattr(adb_shell.adb_device, "AdbDeviceTcp", _HandshakeFails)


def test_a_handshake_that_times_out_says_so_rather_than_blaming_the_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Shield on a lagging network (600ms pings) was reported as "did not authorize this key"."""
    # Arrange
    from adb_shell.exceptions import TcpTimeoutException

    from fleetctl.core.errors import DeviceHandshakeTimeoutError, DeviceUnauthorizedError

    _failing_handshake(monkeypatch, TcpTimeoutException("Reading from 192.168.1.50:5555 timed out (10.0 seconds)"))
    transport = AdbTransport("192.168.1.50", AdbKeyStore(tmp_path / "keys"))
    monkeypatch.setattr(transport, "is_online", lambda timeout_s=3.0: True)

    # Act
    with pytest.raises(DeviceHandshakeTimeoutError) as caught:
        transport.connect()

    # Assert
    message = str(caught.value)
    assert "timed out after 10s" in message and "network is too slow" in message and "key prompt" in message
    assert "did not authorize" not in message
    # Still flagged as needing attention, so a new device waiting at its prompt keeps its hint.
    assert isinstance(caught.value, DeviceUnauthorizedError)


def test_a_refused_handshake_is_still_reported_as_unauthorized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    from fleetctl.core.errors import DeviceHandshakeTimeoutError, DeviceUnauthorizedError

    _failing_handshake(monkeypatch, ConnectionResetError("Connection reset by peer"))
    transport = AdbTransport("192.168.1.50", AdbKeyStore(tmp_path / "keys"))
    monkeypatch.setattr(transport, "is_online", lambda timeout_s=3.0: True)

    # Act
    with pytest.raises(DeviceUnauthorizedError) as caught:
        transport.connect()

    # Assert
    assert not isinstance(caught.value, DeviceHandshakeTimeoutError)
    assert "did not authorize this key" in str(caught.value)


class _DropsFirstPull(_StubDevice):
    """Fails its first pull the way the Shield did on 2026-10-22, then works."""

    def __init__(self, responses: dict[str, str]) -> None:
        super().__init__(responses=responses)
        self.dropped = False

    def pull(self, remote: str, local_path: Any, transport_timeout_s: float = 0, read_timeout_s: float = 0) -> None:
        if not self.dropped:
            self.dropped = True
            raise BrokenPipeError(32, "Broken pipe")
        super().pull(remote, local_path, transport_timeout_s, read_timeout_s)


def test_a_pull_whose_connection_dropped_reconnects_and_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Shield capture built its archive in 70s, then the pull hit "Broken pipe" at byte 0 and the capture was lost."""
    # Arrange
    device = _DropsFirstPull(responses={"stat -c %s /sdcard/c.tar.gz": "7", "/sdcard/c.tar.gz": "archive"})
    transport = _transport(tmp_path, device)
    reconnects = _reconnects_to(monkeypatch, transport, device)

    # Act
    written = transport.get("/sdcard/c.tar.gz", tmp_path / "c.tar.gz")

    # Assert
    assert written == 7
    assert (tmp_path / "c.tar.gz").read_bytes() == b"archive"
    assert len(reconnects) == 1
    assert device.closed is True


def test_a_pull_that_fails_on_its_own_terms_is_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a lost connection is worth a reconnect; anything else would just fail twice."""
    # Arrange
    device = _StubDevice(fail={"/sdcard/missing"})
    transport = _transport(tmp_path, device)
    reconnects = _reconnects_to(monkeypatch, transport, device)

    # Act
    with pytest.raises(TransportError):
        transport.get("/sdcard/missing", tmp_path / "x")

    # Assert
    assert reconnects == []


def test_a_pull_that_lands_short_is_an_error(tmp_path: Path) -> None:
    """Size is the only check a pull gets; a short archive otherwise surfaces as a gzip error much later."""
    # Arrange
    transport = _transport(tmp_path, _StubDevice(responses={"stat -c %s /sdcard/a.tar.gz": "10", "/sdcard/a.tar.gz": "four"}))

    # Act / Assert
    with pytest.raises(TransportError, match="landed 4 of 10"):
        transport.get("/sdcard/a.tar.gz", tmp_path / "a.tar.gz")


class _FakeStream:
    """The reader's end of a netcat stream: serves `data` in chunks, optionally failing after `fail_after` bytes."""

    def __init__(self, data: bytes, fail_after: int | None = None) -> None:
        self.data, self.fail_after, self.sent, self.closed = data, fail_after, 0, False

    def settimeout(self, value: float) -> None:
        pass

    def recv(self, size: int) -> bytes:
        if self.fail_after is not None and self.sent >= self.fail_after:
            raise ConnectionResetError(104, "Connection reset by peer")
        chunk = self.data[self.sent : self.sent + min(size, 4)]
        self.sent += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class _FakeListener:
    commands: list[str] = []

    def __init__(self, address: str, keys: object, port: int, command: str) -> None:
        _FakeListener.commands.append(command)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _netcat(monkeypatch: pytest.MonkeyPatch, transport: AdbTransport, streams: list[_FakeStream]) -> None:
    import fleetctl.packs.android.transport as module

    _FakeListener.commands = []
    monkeypatch.setattr(module, "_NetcatListener", _FakeListener)
    monkeypatch.setattr(transport, "_connect_to_listener", lambda: streams.pop(0))


def test_a_netcat_device_streams_a_pull_through_nc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The ADB protocol's own pull died 0-17MB into a 363MB archive four times over Wi-Fi; netcat moved it."""
    # Arrange — the stream carries more than the file, so stopping at the reported size is under test.
    device = _StubDevice(responses={"stat -c %s /sdcard/c.tar.gz": "10"})
    transport = _transport(tmp_path, device, use_netcat=True)
    _netcat(monkeypatch, transport, [_FakeStream(b"0123456789trailing")])

    # Act
    written = transport.get("/sdcard/c.tar.gz", tmp_path / "c.tar.gz")

    # Assert
    assert written == 10
    assert (tmp_path / "c.tar.gz").read_bytes() == b"0123456789"
    assert _FakeListener.commands == ["toybox nc -l -p 5599 < /sdcard/c.tar.gz"]
    assert device.pull_timeouts == []


def test_a_netcat_stream_that_ends_early_fails_the_size_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    transport = _transport(tmp_path, _StubDevice(responses={"stat -c %s /sdcard/c.tar.gz": "10"}), use_netcat=True)
    _netcat(monkeypatch, transport, [_FakeStream(b"0123")])

    # Act / Assert
    with pytest.raises(TransportError, match="landed 4 of 10"):
        transport.get("/sdcard/c.tar.gz", tmp_path / "c.tar.gz")


def test_a_netcat_device_falls_back_to_adb_when_the_size_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading to a known size is what ends a netcat download; without one, the ADB pull is the safe path."""
    # Arrange
    device = _StubDevice(responses={"/sdcard/a.xml": "<a/>"})
    transport = _transport(tmp_path, device, use_netcat=True)
    _netcat(monkeypatch, transport, [])

    # Act
    transport.get("/sdcard/a.xml", tmp_path / "a.xml")

    # Assert
    assert _FakeListener.commands == []
    assert device.pull_timeouts == [180.0]


def test_a_netcat_stream_that_resets_reconnects_and_streams_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    device = _StubDevice(responses={"stat -c %s /sdcard/c.tar.gz": "10"})
    transport = _transport(tmp_path, device, use_netcat=True)
    _netcat(monkeypatch, transport, [_FakeStream(b"0123456789", fail_after=4), _FakeStream(b"0123456789")])
    reconnects = _reconnects_to(monkeypatch, transport, device)

    # Act
    written = transport.get("/sdcard/c.tar.gz", tmp_path / "c.tar.gz")

    # Assert
    assert written == 10
    assert (tmp_path / "c.tar.gz").read_bytes() == b"0123456789"
    assert len(reconnects) == 1
